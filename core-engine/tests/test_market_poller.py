from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.ohlcv import OHLCVRecord
from app.services.market_poller import refresh_market_state_once


class FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.sorted_sets = {}
        self.strings = {}

    async def hset(self, key, mapping):
        self.hashes[key] = dict(mapping)

    async def expire(self, key, ttl):
        return True

    async def zadd(self, key, mapping):
        self.sorted_sets.setdefault(key, {}).update(mapping)

    async def set(self, key, value):
        self.strings[key] = value


class FakeConn:
    def __init__(self):
        self.prev_close = Decimal("1000")

    async def fetch(self, query, *args):
        return [{"stock_code": "005930"}, {"stock_code": "000660"}]

    async def fetchrow(self, query, *args):
        return {"close": self.prev_close}

    async def execute(self, query, *args):
        return "INSERT 0 1"


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        pass


class FakePool:
    def __init__(self):
        self.conn = FakeConn()

    def acquire(self):
        return FakeAcquire(self.conn)


@pytest.mark.asyncio
async def test_refresh_market_state_once_updates_cache_from_polled_prices():
    pool = FakePool()
    redis = FakeRedis()
    kis = MagicMock()
    kis.get_current_price = AsyncMock(
        side_effect=[
            OHLCVRecord(
                time=datetime.now(timezone.utc),
                stock_code="005930",
                open=Decimal("1100"),
                high=Decimal("1120"),
                low=Decimal("1090"),
                close=Decimal("1110"),
                volume=12345,
                value=0,
                interval="1d",
            ),
            OHLCVRecord(
                time=datetime.now(timezone.utc),
                stock_code="000660",
                open=Decimal("980"),
                high=Decimal("1010"),
                low=Decimal("970"),
                close=Decimal("990"),
                volume=67890,
                value=0,
                interval="1d",
            ),
        ]
    )

    result = await refresh_market_state_once(pool=pool, redis=redis, kis_client=kis)

    assert result == {"updated": 2, "failed": 0, "count": 2}
    assert redis.hashes["market:state:005930"]["price"] == "1110.0"
    assert redis.hashes["market:state:005930"]["change_pct"] == "11.0"
    assert redis.hashes["market:state:000660"]["price"] == "990.0"
    assert "market:meta:updated_at" in redis.strings


@pytest.mark.asyncio
async def test_refresh_market_state_once_counts_failed_symbols():
    pool = FakePool()
    redis = FakeRedis()
    kis = MagicMock()
    kis.get_current_price = AsyncMock(side_effect=[RuntimeError("boom"), None])

    result = await refresh_market_state_once(pool=pool, redis=redis, kis_client=kis)

    assert result == {"updated": 0, "failed": 2, "count": 2}
    assert redis.hashes == {}
