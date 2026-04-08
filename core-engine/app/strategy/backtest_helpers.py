"""Backtest helper functions — slippage, tick size, equity series, monthly returns."""

import math
from datetime import datetime

import asyncpg
import numpy as np
import pandas as pd

from app.config import settings
from app.utils.market_calendar import KST


def effective_slippage(price: float, bar_volume: float, base_rate: float) -> float:
    """Volume-aware slippage: illiquid bars get higher slippage."""
    if bar_volume <= 0 or bar_volume < 10_000:
        return base_rate * 3
    if bar_volume < 50_000:
        return base_rate * 1.5
    return base_rate


def tick_size(price: float) -> float:
    """Korean stock market tick size rules (KRX 호가 단위)."""
    if price < 2_000: return 1
    if price < 5_000: return 5
    if price < 20_000: return 10
    if price < 50_000: return 50
    if price < 200_000: return 100
    if price < 500_000: return 500
    return 1_000


def snap_tick(price: float, up: bool = True) -> float:
    """Snap price to nearest valid tick."""
    t = tick_size(price)
    if up:
        return float(math.ceil(price / t) * t)
    return float(math.floor(price / t) * t)


def is_entry_bar_allowed(ts: datetime, interval: str) -> bool:
    """Apply lightweight session gating for intraday backtests."""
    if interval == "1d":
        return True
    from app.utils.market_calendar import MarketSession, get_current_session
    session, _ = get_current_session(ts.astimezone(KST))
    if session != MarketSession.REGULAR:
        return False
    current_time = ts.astimezone(KST).time()
    open_with_delay = datetime.strptime(f"09:{settings.risk_session_open_delay_min:02d}", "%H:%M").time()
    close_buffer_hour = 15
    close_buffer_min = 20 - settings.risk_session_close_buffer_min
    if close_buffer_min < 0:
        close_buffer_hour = 14
        close_buffer_min = 60 + close_buffer_min
    close_with_buffer = datetime.strptime(f"{close_buffer_hour:02d}:{close_buffer_min:02d}", "%H:%M").time()
    return open_with_delay <= current_time < close_with_buffer


async def fetch_kospi_benchmark(pool: asyncpg.Pool, df: pd.DataFrame) -> list[float] | None:
    """Fetch KOSPI closing prices aligned to the stock's date range."""
    if len(df) == 0:
        return None
    first_date = pd.Timestamp(df["time"].iloc[0]).to_pydatetime()
    last_date = pd.Timestamp(df["time"].iloc[-1]).to_pydatetime()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT time::date as dt, close FROM ohlcv "
                "WHERE stock_code = 'KOSPI' AND interval = '1d' "
                "AND time >= $1 AND time <= $2 ORDER BY time ASC",
                first_date, last_date,
            )
        if len(rows) < 2:
            return None
        kospi_map = {str(r["dt"]): float(r["close"]) for r in rows if r["close"]}
        result = []
        last_val = None
        for i in range(len(df)):
            dt_str = str(pd.Timestamp(df["time"].iloc[i]).date())
            if dt_str in kospi_map:
                last_val = kospi_map[dt_str]
            result.append(last_val if last_val is not None else 0.0)
        return result if any(v > 0 for v in result) else None
    except Exception:
        return None


def build_equity_series(
    df: pd.DataFrame, equity_curve: list[float], benchmark_return: float | None,
    kospi_series: list[float] | None = None, skip_benchmark: bool = False,
) -> list[dict]:
    """Build equity series with actual timestamps, benchmark, and drawdown."""
    if not equity_curve or len(df) == 0:
        return []
    series = []
    first_close = float(df["close"].iloc[0])
    initial_equity = equity_curve[0]
    peak = initial_equity
    use_kospi = kospi_series is not None and len(kospi_series) == len(equity_curve)
    kospi_base = kospi_series[0] if use_kospi and kospi_series[0] > 0 else 0.0

    for i in range(len(equity_curve)):
        ts = pd.Timestamp(df["time"].iloc[i]).to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=KST)
        else:
            ts = ts.astimezone(KST)
        equity_val = equity_curve[i]
        peak = max(peak, equity_val)
        dd = round((equity_val - peak) / peak * 100, 4) if peak > 0 else 0.0
        bench_val = None
        if not skip_benchmark:
            if use_kospi and kospi_base > 0:
                bench_val = round(initial_equity * kospi_series[i] / kospi_base, 0)
            elif first_close > 0:
                bench_val = round(initial_equity * float(df["close"].iloc[i]) / first_close, 0)
        series.append({"time": ts.isoformat(), "equity": equity_val, "benchmark": bench_val, "drawdown": dd})
    return series


def build_monthly_returns(df: pd.DataFrame, equity_curve: list[float]) -> list[dict]:
    """Group equity changes by month to build monthly return series."""
    if not equity_curve or len(df) == 0:
        return []
    monthly: dict[str, tuple[float, float]] = {}
    for i in range(len(equity_curve)):
        ts = pd.Timestamp(df["time"].iloc[i]).to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=KST)
        else:
            ts = ts.astimezone(KST)
        month_key = ts.strftime("%Y-%m")
        eq = equity_curve[i]
        if month_key not in monthly:
            monthly[month_key] = (eq, eq)
        else:
            monthly[month_key] = (monthly[month_key][0], eq)

    result = []
    prev_end = None
    for month_key in sorted(monthly.keys()):
        first_eq, last_eq = monthly[month_key]
        base = prev_end if prev_end is not None else first_eq
        ret_pct = round((last_eq / base - 1) * 100, 2) if base > 0 else 0.0
        result.append({"month": month_key, "return_pct": ret_pct})
        prev_end = last_eq
    return result
