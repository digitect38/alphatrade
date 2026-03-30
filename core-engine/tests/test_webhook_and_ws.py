"""Focused tests for webhook security and websocket bridge behavior."""

import asyncio
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, patch

import pytest


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


class FakePubSub:
    def __init__(self, messages):
        self.messages = messages

    async def subscribe(self, *_args):
        return None

    async def listen(self):
        for message in self.messages:
            yield message
        raise asyncio.CancelledError


class FakeRedisWS:
    def __init__(self, messages):
        self._messages = messages

    def pubsub(self):
        return FakePubSub(self._messages)


class TestWebhookSecurity:
    def test_verify_hmac_signature_valid(self):
        from app.routes.webhook import _verify_hmac_signature

        body = b'{"ticker":"005930","action":"buy"}'
        timestamp = str(int(time.time()))
        secret = "test_secret"
        signature = _sign(secret, timestamp, body)

        with patch("app.routes.webhook.settings.tradingview_webhook_secret", secret):
            assert _verify_hmac_signature(body, signature, timestamp) is True

    def test_verify_hmac_signature_expired(self):
        from app.routes.webhook import _verify_hmac_signature

        body = b'{"ticker":"005930","action":"buy"}'
        timestamp = str(int(time.time()) - 120)
        secret = "test_secret"
        signature = _sign(secret, timestamp, body)

        with patch("app.routes.webhook.settings.tradingview_webhook_secret", secret):
            assert _verify_hmac_signature(body, signature, timestamp) is False


class TestWebSocketBridge:
    @pytest.mark.asyncio
    async def test_redis_bridge_broadcasts_message(self):
        from app.routes.ws import manager, redis_to_websocket_bridge

        redis_client = FakeRedisWS([
            {"type": "subscribe", "data": 1},
            {"type": "message", "data": b'{"stock_code":"005930","price":60000}'},
        ])

        with patch.object(type(manager), "count", new=property(lambda self: 1)):
            with patch.object(manager, "broadcast", new=AsyncMock()) as mock_broadcast:
                await redis_to_websocket_bridge(redis_client)
                mock_broadcast.assert_awaited_once_with('{"stock_code":"005930","price":60000}')
