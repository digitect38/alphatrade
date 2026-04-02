from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.ohlcv import OHLCVRecord
from app.routes.collect import _normalize_intraday_snapshot as normalize_collect_snapshot
from app.trading.loop import _normalize_intraday_snapshot as normalize_trading_snapshot


def _make_record(interval: str = "1m") -> OHLCVRecord:
    return OHLCVRecord(
        time=datetime.now(timezone.utc),
        stock_code="005930",
        open=Decimal("192600"),
        high=Decimal("193600"),
        low=Decimal("177300"),
        close=Decimal("178400"),
        volume=12345,
        value=0,
        interval=interval,
    )


def test_collect_snapshot_normalization_uses_last_price_for_intraday():
    record = normalize_collect_snapshot(_make_record("1m"))
    assert record.open == record.close
    assert record.high == record.close
    assert record.low == record.close


def test_collect_snapshot_normalization_keeps_daily_ohlc():
    record = normalize_collect_snapshot(_make_record("1d"))
    assert record.open == Decimal("192600")
    assert record.high == Decimal("193600")
    assert record.low == Decimal("177300")


def test_trading_snapshot_normalization_uses_last_price_for_intraday():
    record = normalize_trading_snapshot(_make_record("1m"))
    assert record.open == record.close
    assert record.high == record.close
    assert record.low == record.close


class FakeConn:
    def __init__(self):
        self.args = None

    async def execute(self, query, *args):
        self.args = args
        return "INSERT 0 1"


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        pass


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return FakeAcquire(self.conn)


class FakePublisher:
    async def publish_ohlcv(self, *args, **kwargs):
        return 1


@pytest.mark.asyncio
async def test_collect_ohlcv_for_codes_stores_intraday_as_snapshot_bar():
    from app.routes.collect import _collect_ohlcv_for_codes

    conn = FakeConn()
    pool = FakePool(conn)
    kis = MagicMock()
    kis.get_current_price = AsyncMock(return_value=_make_record("1d"))
    publisher = FakePublisher()
    errors = []

    inserted, published = await _collect_ohlcv_for_codes(["005930"], "1m", pool, kis, publisher, errors)

    assert inserted == 1
    assert published == 1
    assert errors == []
    assert conn.args[2] == Decimal("178400")
    assert conn.args[3] == Decimal("178400")
    assert conn.args[4] == Decimal("178400")
    assert conn.args[5] == Decimal("178400")
