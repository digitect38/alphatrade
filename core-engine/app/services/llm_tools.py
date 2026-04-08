"""LLM Chat — Tool execution engine."""

import json
import logging
from datetime import datetime, timedelta, timezone

import asyncpg
import redis.asyncio as aioredis

from app.utils.redis_cache import get_realtime_price

logger = logging.getLogger(__name__)


async def execute_tools(
    tool_calls: list[tuple[str, str]],
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
) -> list[tuple[str, str]]:
    """Execute tool calls and return (tool_name, result_text) pairs."""
    results = []
    for tool_name, args_str in tool_calls:
        args = args_str.split(":")
        try:
            if tool_name == "kis_price":
                result = await _tool_kis_price(args[0], redis, pool)
            elif tool_name == "backtest":
                result = await _tool_backtest(args, pool)
            elif tool_name == "signal":
                result = await _tool_signal(args[0], pool)
            elif tool_name == "news":
                result = await _tool_news(args[0], pool)
            elif tool_name == "ohlcv_monthly":
                result = await _tool_ohlcv_monthly(args, pool)
            elif tool_name == "ohlcv_daily":
                result = await _tool_ohlcv_daily(args, pool)
            else:
                result = f"알 수 없는 도구: {tool_name}"
        except Exception as e:
            result = f"도구 실행 실패: {e}"
        results.append((tool_name, result))
    return results


async def _tool_kis_price(code: str, redis: aioredis.Redis, pool: asyncpg.Pool) -> str:
    rt = await get_realtime_price(redis, code)
    if rt and rt["price"] > 0:
        return (
            f"종목: {code}\n현재가: {rt['price']:,.0f}원\n등락률: {rt['change_pct']:+.2f}%\n"
            f"거래량: {rt['volume']:,}\n출처: 실시간 (Redis 캐시)"
        )
    try:
        from app.services.kis_api import KISClient
        kis = KISClient()
        price_data = await kis.get_current_price(code)
        await kis.close()
        if price_data and price_data.price > 0:
            return (
                f"종목: {code}\n현재가: {price_data.price:,.0f}원\n시가: {price_data.open:,.0f}원\n"
                f"고가: {price_data.high:,.0f}원\n저가: {price_data.low:,.0f}원\n"
                f"거래량: {price_data.volume:,}\n출처: KIS API 실시간"
            )
    except Exception:
        pass
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT close, volume, time FROM ohlcv WHERE stock_code = $1 AND interval = '1d' ORDER BY time DESC LIMIT 1", code,
        )
    if row:
        return f"종목: {code}\n종가: {float(row['close']):,.0f}원\n거래량: {int(row['volume']):,}\n기준일: {str(row['time'])[:10]}\n⚠ DB 기준, 실시간 아님"
    return f"종목 {code}의 시세를 찾을 수 없습니다."


async def _tool_backtest(args: list[str], pool: asyncpg.Pool) -> str:
    code = args[0] if args else "005930"
    strategy = args[1] if len(args) > 1 else "ensemble"
    duration = args[2] if len(args) > 2 else "1Y"
    duration_map = {"3M": 90, "6M": 180, "1Y": 365, "2Y": 730, "3Y": 1095, "5Y": 1825, "MAX": 3650}
    days = duration_map.get(duration, 365)
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    from app.strategy.backtest import run_backtest
    result = await run_backtest(stock_code=code, strategy=strategy, initial_capital=10_000_000, start_date=start, benchmark="buy_and_hold", pool=pool)
    warns = "\n⚠ " + " / ".join(result.statistical_warnings) if result.statistical_warnings else ""
    return (
        f"백테스트 결과 ({code}, {strategy}, {duration})\n기간: {result.period_bars}봉\n"
        f"총 수익률: {result.total_return:+.2f}%\n벤치마크(B&H): {result.benchmark_return or 0:.2f}%\n"
        f"최대 낙폭(MDD): {result.max_drawdown:.2f}%\n샤프 비율: {result.sharpe_ratio or 0:.4f}\n"
        f"승률: {result.win_rate:.1f}%\n총 거래: {result.total_trades}건\n"
        f"연간 수익률: {result.annual_return or 0:.2f}%\n"
        f"초기자본: 1,000만원 → 최종: {result.final_capital:,.0f}원{warns}"
    )


async def _tool_signal(code: str, pool: asyncpg.Pool) -> str:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT signal, strength, strategy_name, reasons, time "
            "FROM strategy_signals WHERE stock_code = $1 ORDER BY time DESC LIMIT 1", code,
        )
    if not row:
        return f"종목 {code}의 시그널이 없습니다."
    reasons_str = ""
    if row["reasons"]:
        try:
            reasons = json.loads(row["reasons"]) if isinstance(row["reasons"], str) else row["reasons"]
            if isinstance(reasons, dict):
                reasons_str = "\n  " + "\n  ".join(f"{k}: {v}" for k, v in reasons.items())
            elif isinstance(reasons, list):
                reasons_str = "\n  " + "\n  ".join(str(r) for r in reasons[:5])
        except Exception:
            pass
    return (
        f"종목: {code}\n시그널: {row['signal']}\n강도: {float(row['strength']):.4f}\n"
        f"전략: {row['strategy_name']}\n시점: {str(row['time'])[:19]}{reasons_str}"
    )


async def _tool_news(code: str, pool: asyncpg.Pool) -> str:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT title, time, source FROM news WHERE $1 = ANY(stock_codes) ORDER BY time DESC LIMIT 8", code,
        )
    if not rows:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT title, time, source FROM news ORDER BY time DESC LIMIT 5")
    if not rows:
        return f"종목 {code} 관련 뉴스가 없습니다."
    lines = [f"종목 {code} 관련 뉴스 ({len(rows)}건):"]
    for r in rows:
        lines.append(f"  [{str(r['time'])[:10]}] {r['title'][:70]} ({r['source']})")
    return "\n".join(lines)


async def _tool_ohlcv_monthly(args: list[str], pool: asyncpg.Pool) -> str:
    code = args[0] if args else "005930"
    duration = args[1] if len(args) > 1 else "1Y"
    duration_map = {"3M": 90, "6M": 180, "1Y": 365, "2Y": 730, "3Y": 1095, "5Y": 1825, "MAX": 3650}
    days = duration_map.get(duration, 365)
    start_dt = datetime.now(timezone.utc) - timedelta(days=days)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DATE_TRUNC('month', time) as month, "
            "(array_agg(close ORDER BY time DESC))[1] as month_close "
            "FROM ohlcv WHERE stock_code = $1 AND interval = '1d' AND time >= $2 "
            "GROUP BY DATE_TRUNC('month', time) ORDER BY month ASC",
            code, start_dt,
        )
        name_row = await conn.fetchrow("SELECT stock_name FROM stocks WHERE stock_code = $1", code)
    if not rows:
        return f"종목 {code}의 월별 데이터가 없습니다."
    label = f"{name_row['stock_name']}({code})" if name_row else code
    lines = [f"{label} 월별 Buy & Hold 성과 ({duration})", "",
             f"{'월':10s} {'월말 종가':>12s} {'월간 수익률':>10s} {'누적 수익률':>10s}", "-" * 46]
    base_price = float(rows[0]["month_close"])
    prev_close = base_price
    for r in rows:
        close = float(r["month_close"])
        monthly_ret = round((close / prev_close - 1) * 100, 2) if prev_close > 0 else 0
        cumul_ret = round((close / base_price - 1) * 100, 2) if base_price > 0 else 0
        lines.append(f"{r['month'].strftime('%Y-%m'):10s} {close:>12,.0f} {monthly_ret:>+9.2f}% {cumul_ret:>+9.2f}%")
        prev_close = close
    final = float(rows[-1]["month_close"])
    total_ret = round((final / base_price - 1) * 100, 2)
    lines.extend(["-" * 46, f"{'합계':10s} {'':>12s} {'':>10s} {total_ret:>+9.2f}%",
                  f"\n시작가: {base_price:,.0f}원 → 최종가: {final:,.0f}원"])
    return "\n".join(lines)


async def _tool_ohlcv_daily(args: list[str], pool: asyncpg.Pool) -> str:
    code = args[0] if args else "005930"
    duration = args[1] if len(args) > 1 else "1M"
    duration_map = {"1W": 7, "2W": 14, "1M": 30, "3M": 90, "6M": 180, "1Y": 365}
    days = duration_map.get(duration, 30)
    start_dt = datetime.now(timezone.utc) - timedelta(days=days)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT time, open, high, low, close, volume FROM ohlcv "
            "WHERE stock_code = $1 AND interval = '1d' AND time >= $2 ORDER BY time ASC",
            code, start_dt,
        )
        name_row = await conn.fetchrow("SELECT stock_name FROM stocks WHERE stock_code = $1", code)
    if not rows:
        return f"종목 {code}의 일별 데이터가 없습니다."
    label = f"{name_row['stock_name']}({code})" if name_row else code
    lines = [f"{label} 일별 OHLCV ({duration}, {len(rows)}일)", "",
             f"{'날짜':12s} {'시가':>10s} {'고가':>10s} {'저가':>10s} {'종가':>10s} {'거래량':>12s}", "-" * 68]
    for r in rows[-30:]:
        dt = str(r["time"])[:10]
        lines.append(
            f"{dt:12s} {float(r['open']):>10,.0f} {float(r['high']):>10,.0f} "
            f"{float(r['low']):>10,.0f} {float(r['close']):>10,.0f} {int(r['volume']):>12,}"
        )
    if len(rows) > 30:
        lines.append(f"  ... ({len(rows) - 30}일 추가 생략)")
    return "\n".join(lines)
