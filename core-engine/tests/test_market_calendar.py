"""Unit tests for KOSPI/KOSDAQ market calendar and session awareness.

Covers:
- MarketSession classification at specific KST times
- Trading day checks (weekends, Korean public holidays)
- Session boundary times returned by get_session_times
- TradingGuard integration with market sessions
"""

import pytest
from datetime import datetime, date, time, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

# KST timezone constant
KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def kst_datetime(year, month, day, hour, minute, second=0):
    """Build a KST-aware datetime for test convenience."""
    return datetime(year, month, day, hour, minute, second, tzinfo=KST)


def _patch_now(target_module: str, dt: datetime):
    """Return a patch context that makes datetime.now(tz) return *dt*.

    Preserves normal datetime construction so code like
    ``datetime(2026, 1, 1)`` still works.
    """
    mock_dt = MagicMock(wraps=datetime)
    mock_dt.now.return_value = dt
    mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
    return patch(f"{target_module}.datetime", mock_dt)


# ===================================================================
# 1. Session classification for specific KST times
# ===================================================================

_MODULE = "app.utils.market_calendar"
_GUARD_MODULE = "app.execution.trading_guard"


def _patch_now_all(dt: datetime):
    """Patch datetime.now in BOTH market_calendar AND trading_guard."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        with _patch_now(_MODULE, dt), _patch_now(_GUARD_MODULE, dt):
            yield

    return _ctx()


class TestSessionClassification:
    """get_current_session should map wall-clock KST to the correct enum."""

    @pytest.mark.parametrize(
        "hour, minute, expected_session",
        [
            (7, 0, "CLOSED"),
            (8, 15, "PRE_MARKET"),
            (8, 45, "OPENING_AUCTION"),
            (9, 30, "REGULAR"),
            (15, 15, "REGULAR"),
            (15, 25, "CLOSING_AUCTION"),
            (15, 45, "AFTER_HOURS"),
            (16, 30, "CLOSED"),
        ],
        ids=[
            "07:00-CLOSED",
            "08:15-PRE_MARKET",
            "08:45-OPENING_AUCTION",
            "09:30-REGULAR",
            "15:15-REGULAR",
            "15:25-CLOSING_AUCTION",
            "15:45-AFTER_HOURS",
            "16:30-CLOSED",
        ],
    )
    def test_session_at_time(self, hour, minute, expected_session):
        from app.utils.market_calendar import get_current_session, MarketSession

        # Use a known trading weekday: 2026-03-30 is Monday
        fake_now = kst_datetime(2026, 3, 30, hour, minute)
        with _patch_now(_MODULE, fake_now):
            session, label = get_current_session()
            assert session == MarketSession[expected_session], (
                f"At {hour:02d}:{minute:02d} KST expected {expected_session}, got {session.name}"
            )

    def test_session_returns_label_string(self):
        from app.utils.market_calendar import get_current_session

        fake_now = kst_datetime(2026, 3, 30, 10, 0)
        with _patch_now(_MODULE, fake_now):
            session, label = get_current_session()
            assert isinstance(label, str)
            assert len(label) > 0

    def test_session_on_weekend_is_closed(self):
        """Even at 10:00 KST, Saturday should be CLOSED."""
        from app.utils.market_calendar import get_current_session, MarketSession

        fake_now = kst_datetime(2026, 3, 28, 10, 0)  # Saturday
        with _patch_now(_MODULE, fake_now):
            session, _ = get_current_session()
            assert session == MarketSession.CLOSED

    def test_session_on_holiday_is_closed(self):
        """Even at 10:00 KST, a public holiday should be CLOSED."""
        from app.utils.market_calendar import get_current_session, MarketSession

        # 2026-05-05 (어린이날) is Tuesday — a weekday holiday
        fake_now = kst_datetime(2026, 5, 5, 10, 0)
        with _patch_now(_MODULE, fake_now):
            session, _ = get_current_session()
            assert session == MarketSession.CLOSED


# ===================================================================
# 2. Trading day checks
# ===================================================================


class TestIsTradingDay:
    """is_trading_day should account for weekends and Korean public holidays."""

    def test_monday_is_trading_day(self):
        from app.utils.market_calendar import is_trading_day

        assert is_trading_day(date(2026, 3, 30)) is True  # Monday

    def test_tuesday_is_trading_day(self):
        from app.utils.market_calendar import is_trading_day

        assert is_trading_day(date(2026, 3, 31)) is True  # Tuesday

    def test_saturday_not_trading_day(self):
        from app.utils.market_calendar import is_trading_day

        assert is_trading_day(date(2026, 3, 28)) is False  # Saturday

    def test_sunday_not_trading_day(self):
        from app.utils.market_calendar import is_trading_day

        assert is_trading_day(date(2026, 3, 29)) is False  # Sunday

    # --- Korean public holidays (공휴일) ---

    def test_new_year_holiday(self):
        """신정 (New Year's Day) — 2026-01-01 (Thursday)."""
        from app.utils.market_calendar import is_trading_day

        assert is_trading_day(date(2026, 1, 1)) is False

    def test_independence_movement_day(self):
        """삼일절 — 2025-03-01 is Saturday so test 2027-03-01 (Monday)."""
        from app.utils.market_calendar import is_trading_day

        assert is_trading_day(date(2027, 3, 1)) is False

    def test_childrens_day(self):
        """어린이날 — 2026-05-05 (Tuesday)."""
        from app.utils.market_calendar import is_trading_day

        assert is_trading_day(date(2026, 5, 5)) is False

    def test_christmas(self):
        """성탄절 — 2026-12-25 (Friday)."""
        from app.utils.market_calendar import is_trading_day

        assert is_trading_day(date(2026, 12, 25)) is False

    def test_lunar_new_year(self):
        """설날 연휴 — 2026 Lunar New Year falls around 2026-02-17.

        The exact dates depend on the implementation's holiday table.
        We test that at least one of the typical 3-day span is marked False.
        """
        from app.utils.market_calendar import is_trading_day

        # 2026 Lunar New Year: Feb 16 (Mon), 17 (Tue, 설날), 18 (Wed)
        lunar_dates = [date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18)]
        non_trading = [d for d in lunar_dates if not is_trading_day(d)]
        assert len(non_trading) >= 1, "At least one Lunar New Year day should be non-trading"

    def test_chuseok(self):
        """추석 연휴 — 2026 Chuseok falls around 2026-09-24/25/26.

        We test that at least one day of the span is marked False.
        """
        from app.utils.market_calendar import is_trading_day

        chuseok_dates = [date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 26)]
        non_trading = [d for d in chuseok_dates if not is_trading_day(d)]
        assert len(non_trading) >= 1, "At least one Chuseok day should be non-trading"

    def test_normal_weekday_is_trading(self):
        """A regular Tuesday with no holidays should be a trading day."""
        from app.utils.market_calendar import is_trading_day

        # 2026-04-07 (Tuesday) — no Korean holiday
        assert is_trading_day(date(2026, 4, 7)) is True

    def test_memorial_day_2026_is_saturday_no_effect(self):
        """현충일 2026-06-06 is Saturday — already non-trading as weekend."""
        from app.utils.market_calendar import is_trading_day

        assert is_trading_day(date(2026, 6, 6)) is False

    def test_national_foundation_day_2026_is_saturday(self):
        """개천절 2026-10-03 is Saturday — already non-trading as weekend."""
        from app.utils.market_calendar import is_trading_day

        assert is_trading_day(date(2026, 10, 3)) is False


# ===================================================================
# 3. Session boundary times (get_session_times)
# ===================================================================


class TestGetSessionTimes:
    """get_session_times should return correct time boundaries or CLOSED info."""

    def test_trading_day_returns_all_sessions(self):
        from app.utils.market_calendar import get_session_times

        result = get_session_times(date(2026, 3, 30))  # Monday
        assert result["is_trading_day"] is True
        sessions = result["sessions"]
        assert "PRE_MARKET" in sessions
        assert "OPENING_AUCTION" in sessions
        assert "REGULAR" in sessions
        assert "CLOSING_AUCTION" in sessions
        assert "AFTER_HOURS" in sessions

    def test_trading_day_time_ordering(self):
        """Session boundaries must be in chronological order."""
        from app.utils.market_calendar import get_session_times

        result = get_session_times(date(2026, 3, 30))
        sessions = result["sessions"]
        keys_ordered = [
            "PRE_MARKET",
            "OPENING_AUCTION",
            "REGULAR",
            "CLOSING_AUCTION",
            "AFTER_HOURS",
        ]
        starts = [sessions[k]["start"] for k in keys_ordered]
        for i in range(len(starts) - 1):
            assert starts[i] < starts[i + 1], (
                f"{keys_ordered[i]} start ({starts[i]}) should be before "
                f"{keys_ordered[i+1]} start ({starts[i+1]})"
            )

    def test_regular_session_boundaries(self):
        """Regular session should span 09:00 - 15:20."""
        from app.utils.market_calendar import get_session_times

        result = get_session_times(date(2026, 3, 30))
        regular = result["sessions"]["REGULAR"]
        # Regular starts at 09:00 (ISO format contains T09:00)
        assert "T09:00" in regular["start"]
        # Regular ends at 15:20
        assert "T15:20" in regular["end"]

    def test_holiday_returns_closed(self):
        """get_session_times on a holiday should indicate market is closed."""
        from app.utils.market_calendar import get_session_times

        result = get_session_times(date(2026, 1, 1))  # 신정
        assert result["is_trading_day"] is False
        assert len(result["sessions"]) == 0

    def test_weekend_returns_closed(self):
        from app.utils.market_calendar import get_session_times

        result = get_session_times(date(2026, 3, 28))  # Saturday
        assert result["is_trading_day"] is False
        assert len(result["sessions"]) == 0


# ===================================================================
# 4. MarketSession enum completeness
# ===================================================================


class TestMarketSessionEnum:
    """The MarketSession enum should have all expected members."""

    def test_all_sessions_exist(self):
        from app.utils.market_calendar import MarketSession

        expected = {
            "PRE_MARKET",
            "OPENING_AUCTION",
            "REGULAR",
            "CLOSING_AUCTION",
            "AFTER_HOURS",
            "CLOSED",
        }
        actual = {s.name for s in MarketSession}
        assert expected.issubset(actual), f"Missing sessions: {expected - actual}"

    def test_enum_members_are_unique(self):
        from app.utils.market_calendar import MarketSession

        values = [s.value for s in MarketSession]
        assert len(values) == len(set(values))


# ===================================================================
# 5. TradingGuard integration with market sessions
# ===================================================================


class MockRedis:
    """Minimal async Redis mock for TradingGuard."""

    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value):
        self._store[key] = value

    async def delete(self, key):
        self._store.pop(key, None)

    async def incr(self, key):
        self._store[key] = str(int(self._store.get(key, "0")) + 1)
        return int(self._store[key])

    async def expire(self, *a, **kw):
        pass

    async def publish(self, *a, **kw):
        return 0


class MockConn:
    def __init__(self, fetch=None, fetchrow=None, fetchval=None):
        self._fetch = fetch or []
        self._fetchrow = fetchrow
        self._fetchval = fetchval

    async def fetch(self, *a, **kw):
        return self._fetch

    async def fetchrow(self, *a, **kw):
        return self._fetchrow

    async def fetchval(self, *a, **kw):
        return self._fetchval

    async def execute(self, *a, **kw):
        pass


class MockPool:
    def __init__(self, conn=None):
        self.conn = conn or MockConn()

    def acquire(self):
        return _MockAcquire(self.conn)


class _MockAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        pass


class TestTradingGuardSessionIntegration:
    """TradingGuard should respect market calendar sessions for order gating."""

    @pytest.fixture
    def guard(self):
        from app.execution.trading_guard import TradingGuard

        class SmartConn(MockConn):
            async def fetchrow(self, query, *a, **kw):
                if "portfolio_snapshots" in query:
                    return {"total_value": 10000000, "daily_pnl": 0, "cash": 5000000}
                if "stocks" in query:
                    return {"stock_code": "005930", "stock_name": "삼성전자"}
                if "ohlcv" in query:
                    return {"close": 60000, "time": datetime.now(timezone.utc)}
                return self._fetchrow

        conn = SmartConn(fetchval=None)
        pool = MockPool(conn)
        redis = MockRedis()
        return TradingGuard(pool=pool, redis=redis)

    @pytest.mark.asyncio
    async def test_regular_session_allows_buy(self, guard):
        """During REGULAR hours (09:05-15:00), BUY orders should pass session check."""
        fake_now = kst_datetime(2026, 3, 30, 10, 30)  # Monday 10:30 KST
        with _patch_now_all(fake_now):
            ok, msg, info = guard.is_trading_session()
            assert ok is True, f"REGULAR session should allow trading, got: {msg}"

    @pytest.mark.asyncio
    async def test_closed_session_blocks_buy(self, guard):
        """During CLOSED hours, BUY orders should be blocked."""
        fake_now = kst_datetime(2026, 3, 30, 7, 0)  # Monday 07:00 KST
        with _patch_now_all(fake_now):
            ok, msg, info = guard.is_trading_session()
            assert ok is False, "CLOSED session should block trading"

    @pytest.mark.asyncio
    async def test_pre_market_blocks_new_entries(self, guard):
        """During PRE_MARKET (before open), new entry orders should be blocked."""
        fake_now = kst_datetime(2026, 3, 30, 8, 15)  # Monday 08:15 KST
        with _patch_now_all(fake_now):
            ok, msg, info = guard.is_trading_session()
            assert ok is False, "PRE_MARKET should block new entries"

    @pytest.mark.asyncio
    async def test_closing_auction_blocks_new_entries(self, guard):
        """During CLOSING_AUCTION, new entry orders should be blocked."""
        fake_now = kst_datetime(2026, 3, 30, 15, 25)  # Monday 15:25 KST
        with _patch_now_all(fake_now):
            ok, msg, info = guard.is_trading_session()
            assert ok is False, "CLOSING_AUCTION should block new entries"

    @pytest.mark.asyncio
    async def test_weekend_blocks_via_pre_trade_check(self, guard):
        """Full pre_trade_check should fail on weekends."""
        fake_now = kst_datetime(2026, 3, 28, 11, 0)  # Saturday 11:00
        with _patch_now_all(fake_now):
            ok, violations = await guard.pre_trade_check("005930")
            assert ok is False
            # Should contain a message about weekend or non-trading
            violation_text = " ".join(violations)
            assert any(
                kw in violation_text for kw in ("주말", "장 시간", "휴장", "세션", "CLOSED")
            ), f"Expected weekend/session violation, got: {violations}"

    @pytest.mark.asyncio
    async def test_holiday_blocks_via_pre_trade_check(self, guard):
        """Full pre_trade_check should fail on a public holiday."""
        fake_now = kst_datetime(2026, 5, 5, 10, 30)  # 어린이날 10:30
        with _patch_now_all(fake_now):
            ok, violations = await guard.pre_trade_check("005930")
            assert ok is False

    @pytest.mark.asyncio
    async def test_after_hours_blocks_trading(self, guard):
        """AFTER_HOURS should block new orders through is_trading_session."""
        fake_now = kst_datetime(2026, 3, 30, 15, 45)  # Monday 15:45
        with _patch_now_all(fake_now):
            ok, msg, info = guard.is_trading_session()
            assert ok is False, "AFTER_HOURS should block new entries"


# ===================================================================
# 6. Edge cases and boundary times
# ===================================================================


class TestSessionEdgeCases:
    """Test exact boundary transitions between sessions."""

    def test_exact_regular_open_0900(self):
        """09:00 should be classified as REGULAR (market open)."""
        from app.utils.market_calendar import get_current_session, MarketSession

        fake_now = kst_datetime(2026, 3, 30, 9, 0, 0)
        with _patch_now_all(fake_now):
            session, _ = get_current_session()
            assert session == MarketSession.REGULAR

    def test_one_second_before_regular(self):
        """08:59:59 should still be OPENING_AUCTION, not REGULAR."""
        from app.utils.market_calendar import get_current_session, MarketSession

        fake_now = kst_datetime(2026, 3, 30, 8, 59, 59)
        with _patch_now_all(fake_now):
            session, _ = get_current_session()
            assert session != MarketSession.REGULAR
            assert session == MarketSession.OPENING_AUCTION

    def test_exact_close_1530(self):
        """15:30 is in the gap between closing auction and after-hours → CLOSED."""
        from app.utils.market_calendar import get_current_session, MarketSession

        fake_now = kst_datetime(2026, 3, 30, 15, 30, 0)
        with _patch_now_all(fake_now):
            session, _ = get_current_session()
            assert session == MarketSession.CLOSED

    def test_midnight_is_closed(self):
        from app.utils.market_calendar import get_current_session, MarketSession

        fake_now = kst_datetime(2026, 3, 30, 0, 0)
        with _patch_now_all(fake_now):
            session, _ = get_current_session()
            assert session == MarketSession.CLOSED

    def test_2359_is_closed(self):
        from app.utils.market_calendar import get_current_session, MarketSession

        fake_now = kst_datetime(2026, 3, 30, 23, 59)
        with _patch_now_all(fake_now):
            session, _ = get_current_session()
            assert session == MarketSession.CLOSED
