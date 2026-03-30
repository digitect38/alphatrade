"""Webhook endpoints with HMAC signature verification (v1.31 16.5.5)."""

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import settings
from app.deps import get_redis
from app.models.strategy import TradingViewWebhook
from app.services.redis_publisher import RedisPublisher

logger = logging.getLogger(__name__)
router = APIRouter()

WEBHOOK_TIMESTAMP_TOLERANCE = 60  # seconds


def _verify_hmac_signature(body: bytes, signature: str | None, timestamp: str | None) -> bool:
    """Verify HMAC-SHA256 signature with timestamp tolerance.

    Expected headers: X-Signature: <hex digest>, X-Timestamp: <unix epoch>
    If webhook secret is not configured, skip verification.
    """
    secret = settings.tradingview_webhook_secret
    if not secret:
        return True  # No secret = no verification (dev mode)

    if not signature or not timestamp:
        return False

    # Timestamp tolerance check (v1.31: 60 seconds)
    try:
        ts = int(timestamp)
        age = abs(time.time() - ts)
        if age > WEBHOOK_TIMESTAMP_TOLERANCE:
            logger.warning("Webhook timestamp too old: %d seconds", age)
            return False
    except (ValueError, TypeError):
        return False

    # HMAC-SHA256: sign(secret, timestamp + "." + body)
    message = f"{timestamp}.".encode() + body
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/tradingview")
async def receive_tradingview_webhook(
    request: Request,
    redis: aioredis.Redis = Depends(get_redis),
):
    """Receive TradingView Alert webhook with HMAC verification.

    Authentication methods (checked in order):
    1. HMAC signature: X-Signature + X-Timestamp headers
    2. Legacy: secret field in request body
    """
    body = await request.body()

    # Try HMAC verification first
    signature = request.headers.get("X-Signature")
    timestamp = request.headers.get("X-Timestamp")

    if signature:
        if not _verify_hmac_signature(body, signature, timestamp):
            raise HTTPException(status_code=403, detail="Invalid HMAC signature or expired timestamp")
    else:
        # Fallback: legacy body secret verification
        try:
            body_json = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        if settings.tradingview_webhook_secret:
            if body_json.get("secret") != settings.tradingview_webhook_secret:
                raise HTTPException(status_code=403, detail="Invalid webhook secret")

    # Parse webhook data
    data = TradingViewWebhook.model_validate_json(body)
    now = datetime.now(timezone.utc)

    logger.info(
        "TradingView webhook: ticker=%s action=%s price=%s",
        data.ticker, data.action, data.price,
    )

    # Publish to Redis for downstream consumers
    try:
        publisher = RedisPublisher(redis)
        await publisher.publish_event("tradingview", {
            "ticker": data.ticker, "action": data.action,
            "price": data.price, "message": data.message,
            "received_at": now.isoformat(),
        })
    except Exception as e:
        logger.error("Failed to publish TradingView event: %s", e)

    return {
        "status": "received",
        "ticker": data.ticker,
        "action": data.action,
        "received_at": now.isoformat(),
    }
