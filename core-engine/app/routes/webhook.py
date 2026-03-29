import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.deps import get_redis
from app.models.strategy import TradingViewWebhook
from app.services.redis_publisher import RedisPublisher

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/tradingview")
async def receive_tradingview_webhook(data: TradingViewWebhook, redis: aioredis.Redis = Depends(get_redis)):
    """Receive TradingView Alert webhook and publish as event."""
    # Verify secret if configured
    if settings.tradingview_webhook_secret:
        if data.secret != settings.tradingview_webhook_secret:
            raise HTTPException(status_code=403, detail="Invalid webhook secret")

    now = datetime.now(timezone.utc)

    logger.info(
        "TradingView webhook: ticker=%s action=%s price=%s",
        data.ticker,
        data.action,
        data.price,
    )

    # Publish to Redis for downstream consumers
    try:
        publisher = RedisPublisher(redis)
        await publisher.publish_event(
            "tradingview",
            {
                "ticker": data.ticker,
                "action": data.action,
                "price": data.price,
                "message": data.message,
                "received_at": now.isoformat(),
            },
        )
    except Exception as e:
        logger.error("Failed to publish TradingView event: %s", e)

    return {
        "status": "received",
        "ticker": data.ticker,
        "action": data.action,
        "received_at": now.isoformat(),
    }
