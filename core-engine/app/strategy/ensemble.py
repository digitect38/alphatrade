import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

import asyncpg
import redis.asyncio as aioredis

from app.analysis.sentiment import analyze_stock_sentiment
from app.metrics import SIGNALS_TOTAL
from app.services.audit import log_event
from app.analysis.technical import compute_technical
from app.analysis.volume import analyze_volume
from app.models.strategy import StrategyComponent, StrategySignalResult
from app.services.redis_publisher import RedisPublisher
from app.strategy.signals import (
    mean_reversion_signal,
    momentum_signal,
    sentiment_signal,
    volume_signal,
)

from app.config import settings

logger = logging.getLogger(__name__)


def _get_weights() -> dict:
    return {
        "momentum": settings.strategy_weight_momentum,
        "mean_reversion": settings.strategy_weight_mean_reversion,
        "volume": settings.strategy_weight_volume,
        "sentiment": settings.strategy_weight_sentiment,
    }


async def generate_signal(
    stock_code: str, interval: str = "1d",
    *, pool: asyncpg.Pool, redis: aioredis.Redis,
) -> StrategySignalResult:
    """Generate ensemble trading signal by combining all analysis modules."""
    now = datetime.now(timezone.utc)

    # Run all analyses
    technical = await compute_technical(stock_code, interval, pool=pool, redis=redis)
    vol = await analyze_volume(stock_code, interval, pool=pool)

    # Sentiment is optional (may have no data)
    try:
        sent = await analyze_stock_sentiment(stock_code, days=7, pool=pool)
    except Exception:
        sent = None

    # Calculate individual strategy scores
    mom_score = momentum_signal(technical)
    mr_score = mean_reversion_signal(technical)
    vol_score = volume_signal(vol)
    sent_score = sentiment_signal(sent)

    weights = _get_weights()
    components = [
        StrategyComponent(name="momentum", score=mom_score, weight=weights["momentum"]),
        StrategyComponent(name="mean_reversion", score=mr_score, weight=weights["mean_reversion"]),
        StrategyComponent(name="volume", score=vol_score, weight=weights["volume"]),
        StrategyComponent(name="sentiment", score=sent_score, weight=weights["sentiment"]),
    ]

    # Weighted ensemble score
    ensemble_score = sum(c.score * c.weight for c in components)
    ensemble_score = round(max(-1.0, min(1.0, ensemble_score)), 4)

    # Determine signal
    if ensemble_score > settings.strategy_buy_threshold:
        signal = "BUY"
    elif ensemble_score < settings.strategy_sell_threshold:
        signal = "SELL"
    else:
        signal = "HOLD"

    strength = round(min(abs(ensemble_score) / 0.5, 1.0), 4)

    # Build reasons
    reasons = []
    for c in sorted(components, key=lambda x: abs(x.score), reverse=True):
        direction = "긍정" if c.score > 0.1 else "부정" if c.score < -0.1 else "중립"
        reasons.append(f"{c.name}: {direction} ({c.score:+.2f})")

    SIGNALS_TOTAL.labels(signal=signal).inc()

    result = StrategySignalResult(
        stock_code=stock_code,
        signal=signal,
        strength=strength,
        ensemble_score=ensemble_score,
        components=components,
        reasons=reasons,
        computed_at=now,
    )

    # Store in DB
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO strategy_signals (time, stock_code, signal, strength, strategy_name, reasons, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                now,
                stock_code,
                signal,
                Decimal(str(strength)),
                "ensemble",
                json.dumps(reasons, ensure_ascii=False),
                json.dumps({c.name: c.score for c in components}),
            )
    except Exception as e:
        logger.error("Failed to store signal: %s", e)

    # Publish to Redis
    try:
        publisher = RedisPublisher(redis)
        await publisher.publish_event(
            "strategy_signal",
            {"stock_code": stock_code, "signal": signal, "strength": strength, "score": ensemble_score},
        )
    except Exception:
        pass

    # Audit log for strategy decisions (v1.31 A-6)
    if signal != "HOLD":
        await log_event(
            pool, source="strategy", event_type=f"signal_{signal.lower()}",
            symbol=stock_code, strategy_id="ensemble",
            payload={"signal": signal, "strength": strength, "score": ensemble_score,
                     "components": {c.name: c.score for c in components}},
        )

        # Callback to n8n for WF-05 trade alert (v1.3 engine→n8n)
        from app.services.n8n_callback import on_signal_generated
        await on_signal_generated(stock_code, signal, strength, ensemble_score)

    return result
