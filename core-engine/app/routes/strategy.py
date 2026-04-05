import logging
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.deps import get_db, get_redis
from app.models.strategy import (
    BacktestRequest,
    BacktestResult,
    BatchSignalRequest,
    BatchSignalResult,
    StrategySignalRequest,
    StrategySignalResult,
)
from app.strategy.backtest import run_backtest
from app.strategy.ensemble import generate_signal
from app.strategy.presets import list_presets, get_preset

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory active strategy config (persisted in Redis)
ACTIVE_STRATEGY_KEY = "strategy:active_config"


@router.post("/signal", response_model=StrategySignalResult)
async def api_strategy_signal(
    request: StrategySignalRequest,
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Generate ensemble trading signal for a stock."""
    return await generate_signal(
        stock_code=request.stock_code,
        interval=request.interval,
        pool=pool,
        redis=redis,
    )


@router.post("/signals/batch", response_model=BatchSignalResult)
async def api_batch_signals(
    request: BatchSignalRequest,
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Generate signals for multiple stocks or active universe."""
    now = datetime.now(timezone.utc)

    stock_codes = request.stock_codes
    if not stock_codes:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT stock_code FROM universe WHERE is_active = TRUE"
            )
            stock_codes = [r["stock_code"] for r in rows]

    signals = []
    for code in stock_codes:
        try:
            result = await generate_signal(code, request.interval, pool=pool, redis=redis)
            signals.append(result)
        except Exception as e:
            logger.error("Signal generation failed for %s: %s", code, e)

    buy_count = sum(1 for s in signals if s.signal == "BUY")
    sell_count = sum(1 for s in signals if s.signal == "SELL")
    hold_count = sum(1 for s in signals if s.signal == "HOLD")

    return BatchSignalResult(
        signals=signals,
        buy_count=buy_count,
        sell_count=sell_count,
        hold_count=hold_count,
        computed_at=now,
    )


@router.post("/backtest", response_model=BacktestResult)
async def api_backtest(
    request: BacktestRequest,
    pool: asyncpg.Pool = Depends(get_db),
):
    """Run backtest on historical data."""
    return await run_backtest(
        stock_code=request.stock_code,
        initial_capital=request.initial_capital,
        strategy=request.strategy,
        interval=request.interval,
        start_date=request.start_date,
        end_date=request.end_date,
        buy_fee_rate=request.buy_fee_rate,
        sell_fee_rate=request.sell_fee_rate,
        sell_tax_rate=request.sell_tax_rate,
        slippage_rate=request.slippage_rate,
        capital_fraction=request.capital_fraction,
        max_drawdown_stop=request.max_drawdown_stop,
        benchmark=request.benchmark,
        pool=pool,
    )


@router.post("/walk-forward")
async def api_walk_forward(
    request: BacktestRequest,
    train_days: int = 252,
    test_days: int = 63,
    pool: asyncpg.Pool = Depends(get_db),
):
    """Run walk-forward out-of-sample strategy validation.

    Splits data into rolling train/test windows and evaluates
    strategy performance only on unseen (out-of-sample) data.

    Query params:
    - train_days: Training window size (default 252 = 1 year)
    - test_days: Test window size (default 63 = 3 months)
    """
    from app.strategy.walk_forward import run_walk_forward
    return await run_walk_forward(
        stock_code=request.stock_code,
        initial_capital=request.initial_capital,
        strategy=request.strategy,
        interval=request.interval,
        train_days=train_days,
        test_days=test_days,
        pool=pool,
    )


class PortfolioBacktestRequest(BaseModel):
    stock_codes: list[str]
    initial_capital: float = 10_000_000
    strategy: str = "ensemble"
    interval: str = "1d"
    start_date: str | None = None
    end_date: str | None = None
    allocation: str = "equal"  # "equal" = 균등 배분


@router.post("/backtest/portfolio")
async def api_portfolio_backtest(
    request: PortfolioBacktestRequest,
    pool: asyncpg.Pool = Depends(get_db),
):
    """Run backtest on multiple stocks with capital allocation.

    Returns individual results + portfolio-level aggregated metrics.
    """
    import asyncio
    n = len(request.stock_codes)
    if n == 0:
        return {"error": "No stock codes provided"}
    if n > 10:
        return {"error": "Maximum 10 stocks allowed"}

    per_stock_capital = request.initial_capital / n

    tasks = [
        run_backtest(
            stock_code=code,
            initial_capital=per_stock_capital,
            strategy=request.strategy,
            interval=request.interval,
            start_date=request.start_date,
            end_date=request.end_date,
            benchmark="kospi",
            pool=pool,
        )
        for code in request.stock_codes
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    individual = []
    total_final = 0.0
    total_initial = 0.0
    all_trades = []
    for code, res in zip(request.stock_codes, results):
        if isinstance(res, Exception):
            individual.append({"stock_code": code, "error": str(res)})
            total_final += per_stock_capital
            total_initial += per_stock_capital
        else:
            individual.append({
                "stock_code": res.stock_code,
                "total_return": res.total_return,
                "max_drawdown": res.max_drawdown,
                "sharpe_ratio": res.sharpe_ratio,
                "win_rate": res.win_rate,
                "total_trades": res.total_trades,
                "final_capital": res.final_capital,
            })
            total_final += res.final_capital
            total_initial += res.initial_capital
            all_trades.extend(res.trades)

    portfolio_return = round((total_final / total_initial - 1) * 100, 2) if total_initial > 0 else 0.0

    return {
        "portfolio": {
            "initial_capital": request.initial_capital,
            "final_capital": round(total_final, 0),
            "total_return": portfolio_return,
            "stock_count": n,
            "total_trades": len(all_trades),
        },
        "individual": individual,
    }


@router.get("/benchmark")
async def api_benchmark_compare(
    stock_code: str = "005930",
    period: int = 60,
    pool: asyncpg.Pool = Depends(get_db),
):
    """Compare stock returns vs KOSPI/KOSDAQ benchmarks.

    Returns normalized return series (base=100) for the stock and indexes.
    """
    async with pool.acquire() as conn:
        # Stock data
        stock_rows = await conn.fetch(
            "SELECT time::date as dt, close FROM ohlcv WHERE stock_code = $1 AND interval = '1d' ORDER BY time DESC LIMIT $2",
            stock_code, period,
        )
        # KOSPI data
        kospi_rows = await conn.fetch(
            "SELECT time::date as dt, close FROM ohlcv WHERE stock_code = 'KOSPI' AND interval = '1d' ORDER BY time DESC LIMIT $1",
            period,
        )
        # KOSDAQ data
        kosdaq_rows = await conn.fetch(
            "SELECT time::date as dt, close FROM ohlcv WHERE stock_code = 'KOSDAQ' AND interval = '1d' ORDER BY time DESC LIMIT $1",
            period,
        )
        # Stock name + sector
        name_row = await conn.fetchrow("SELECT stock_name, sector FROM stocks WHERE stock_code = $1", stock_code)

        # Sector average: avg close of same-sector stocks
        sector = name_row["sector"] if name_row else None
        sector_rows = []
        if sector:
            sector_rows = await conn.fetch(
                """
                WITH sector_daily AS (
                    SELECT o.time::date as dt, AVG(o.close) as avg_close
                    FROM ohlcv o
                    JOIN stocks s ON o.stock_code = s.stock_code
                    WHERE s.sector = $1 AND o.interval = '1d' AND s.is_active = TRUE
                    GROUP BY dt ORDER BY dt DESC LIMIT $2
                )
                SELECT dt, avg_close as close FROM sector_daily ORDER BY dt
                """,
                sector, period,
            )

        # My portfolio: use total_value (like a price) for proper normalization
        portfolio_rows = await conn.fetch(
            """SELECT DISTINCT ON (time::date) time::date as dt, total_value as close
            FROM portfolio_snapshots ORDER BY time::date DESC, time DESC LIMIT $1""",
            period,
        )

    stock_name = name_row["stock_name"] if name_row else stock_code

    def to_series(rows, value_key="close"):
        data = sorted([(str(r["dt"]), float(r[value_key])) for r in rows if r[value_key] is not None], key=lambda x: x[0])
        if not data or len(data) < 2:
            return []
        base = data[0][1]
        if base == 0:
            return []
        return [{"date": d, "value": round((v / base - 1) * 100, 2)} for d, v in data]

    stock_series = to_series(stock_rows)
    kospi_series = to_series(kospi_rows)
    kosdaq_series = to_series(kosdaq_rows)
    sector_series = to_series(sector_rows) if sector_rows else []
    portfolio_series = to_series(portfolio_rows)

    # Calculate summary
    stock_return = stock_series[-1]["value"] if stock_series else 0
    kospi_return = kospi_series[-1]["value"] if kospi_series else 0
    kosdaq_return = kosdaq_series[-1]["value"] if kosdaq_series else 0
    sector_return = sector_series[-1]["value"] if sector_series else None
    portfolio_return = portfolio_series[-1]["value"] if portfolio_series else None
    alpha_vs_kospi = round(stock_return - kospi_return, 2)
    alpha_vs_kosdaq = round(stock_return - kosdaq_return, 2)

    series = {
        stock_code: stock_series,
        "KOSPI": kospi_series,
        "KOSDAQ": kosdaq_series,
    }
    if sector_series:
        series["sector"] = sector_series
    if portfolio_series:
        series["portfolio"] = portfolio_series

    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "sector": sector,
        "period": period,
        "series": series,
        "summary": {
            f"{stock_code}_return": stock_return,
            "kospi_return": kospi_return,
            "kosdaq_return": kosdaq_return,
            "sector_return": sector_return,
            "portfolio_return": portfolio_return,
            "alpha_vs_kospi": alpha_vs_kospi,
            "alpha_vs_kosdaq": alpha_vs_kosdaq,
        },
    }


@router.get("/presets")
async def api_strategy_presets():
    """List all available strategy presets."""
    return {"presets": list_presets()}


@router.get("/active")
async def api_get_active_strategy(redis: aioredis.Redis = Depends(get_redis)):
    """Get currently active strategy configuration."""
    import json
    raw = await redis.get(ACTIVE_STRATEGY_KEY)
    if raw:
        return json.loads(raw)
    # Default: ensemble
    preset = get_preset("ensemble")
    return {"preset": "ensemble", **preset}


@router.post("/active")
async def api_set_active_strategy(
    body: dict,
    redis: aioredis.Redis = Depends(get_redis),
):
    """Set active strategy configuration.

    Body options:
    1. {"preset": "momentum"} — use a preset
    2. {"preset": "custom", "weights": {...}, "buy_threshold": 0.2, "sell_threshold": -0.1}
    """
    import json
    preset_name = body.get("preset", "ensemble")
    preset = get_preset(preset_name)
    if not preset:
        return {"error": f"Unknown preset: {preset_name}"}

    config = {"preset": preset_name, **preset}

    # Override with custom values if provided
    if body.get("weights"):
        config["weights"] = body["weights"]
    if body.get("buy_threshold") is not None:
        config["buy_threshold"] = body["buy_threshold"]
    if body.get("sell_threshold") is not None:
        config["sell_threshold"] = body["sell_threshold"]

    await redis.set(ACTIVE_STRATEGY_KEY, json.dumps(config, ensure_ascii=False))
    logger.info("Active strategy changed to: %s", preset_name)
    return {"status": "ok", "active": config}
