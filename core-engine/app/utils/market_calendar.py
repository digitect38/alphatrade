"""KOSPI/KOSDAQ market calendar — session detection, holiday awareness, schedule info.

Market hours (KST = UTC+9):
- Pre-market order acceptance: 08:00-08:30
- Opening auction (동시호가): 08:30-09:00
- Regular session (정규장): 09:00-15:20
- Closing auction (종가 동시호가): 15:20-15:30
- After-hours single price (시간외 단일가): 15:40-16:00
"""

import enum
from datetime import date, datetime, time, timedelta, timezone

KST = timezone(timedelta(hours=9))


class MarketSession(str, enum.Enum):
    """Current market session phase."""

    PRE_MARKET = "PRE_MARKET"  # 08:00-08:30 주문 접수
    OPENING_AUCTION = "OPENING_AUCTION"  # 08:30-09:00 동시호가
    REGULAR = "REGULAR"  # 09:00-15:20 정규장
    CLOSING_AUCTION = "CLOSING_AUCTION"  # 15:20-15:30 종가 동시호가
    AFTER_HOURS = "AFTER_HOURS"  # 15:40-16:00 시간외 단일가
    CLOSED = "CLOSED"  # 장 마감 / 휴장


# ---------------------------------------------------------------------------
# Session time boundaries
# ---------------------------------------------------------------------------

_SESSION_BOUNDARIES = {
    MarketSession.PRE_MARKET: (time(8, 0), time(8, 30)),
    MarketSession.OPENING_AUCTION: (time(8, 30), time(9, 0)),
    MarketSession.REGULAR: (time(9, 0), time(15, 20)),
    MarketSession.CLOSING_AUCTION: (time(15, 20), time(15, 30)),
    MarketSession.AFTER_HOURS: (time(15, 40), time(16, 0)),
}

_SESSION_DESCRIPTIONS = {
    MarketSession.PRE_MARKET: "장전 주문 접수 (08:00-08:30)",
    MarketSession.OPENING_AUCTION: "동시호가 (08:30-09:00)",
    MarketSession.REGULAR: "정규장 (09:00-15:20)",
    MarketSession.CLOSING_AUCTION: "종가 동시호가 (15:20-15:30)",
    MarketSession.AFTER_HOURS: "시간외 단일가 (15:40-16:00)",
    MarketSession.CLOSED: "장 마감",
}

# ---------------------------------------------------------------------------
# Korean public holidays (fixed-date)
# ---------------------------------------------------------------------------

_FIXED_HOLIDAYS: list[tuple[int, int, str]] = [
    (1, 1, "신정"),
    (3, 1, "삼일절"),
    (5, 5, "어린이날"),
    (6, 6, "현충일"),
    (8, 15, "광복절"),
    (10, 3, "개천절"),
    (10, 9, "한글날"),
    (12, 25, "성탄절"),
]

# Lunar-calendar holidays vary each year.
# We maintain a lookup of (month, day) sets keyed by year for 설날 and 추석.
# Each entry includes the holiday itself plus the day before and after.
_LUNAR_HOLIDAYS: dict[int, list[tuple[int, int, str]]] = {
    2024: [
        (2, 9, "설날 연휴"),
        (2, 10, "설날"),
        (2, 11, "설날 연휴"),
        (2, 12, "설날 대체공휴일"),
        (9, 16, "추석 연휴"),
        (9, 17, "추석"),
        (9, 18, "추석 연휴"),
        (5, 15, "부처님오신날"),
    ],
    2025: [
        (1, 28, "설날 연휴"),
        (1, 29, "설날"),
        (1, 30, "설날 연휴"),
        (10, 5, "추석 연휴"),
        (10, 6, "추석"),
        (10, 7, "추석 연휴"),
        (10, 8, "추석 대체공휴일"),
        (5, 5, "부처님오신날"),  # coincides with 어린이날
        (6, 3, "대체공휴일(현충일)"),
    ],
    2026: [
        (2, 16, "설날 연휴"),
        (2, 17, "설날"),
        (2, 18, "설날 연휴"),
        (9, 24, "추석 연휴"),
        (9, 25, "추석"),
        (9, 26, "추석 연휴"),
        (5, 24, "부처님오신날"),
    ],
    2027: [
        (2, 5, "설날 연휴"),
        (2, 6, "설날"),
        (2, 7, "설날 연휴"),
        (2, 8, "설날 대체공휴일"),
        (10, 14, "추석 연휴"),
        (10, 15, "추석"),
        (10, 16, "추석 연휴"),
        (5, 13, "부처님오신날"),
    ],
    2028: [
        (1, 25, "설날 연휴"),
        (1, 26, "설날"),
        (1, 27, "설날 연휴"),
        (10, 2, "추석 연휴"),
        (10, 3, "추석"),
        (10, 4, "추석 연휴"),
        (5, 2, "부처님오신날"),
    ],
}

# KRX also closes on Dec 31 (연말 휴장) — added as a fixed rule.
_KRX_EXTRA_HOLIDAYS: list[tuple[int, int, str]] = [
    (12, 31, "연말 휴장"),
]


def _get_holidays_for_year(year: int) -> dict[date, str]:
    """Build a {date: name} mapping of all known holidays for a given year."""
    holidays: dict[date, str] = {}

    # Fixed
    for month, day, name in _FIXED_HOLIDAYS:
        holidays[date(year, month, day)] = name

    # KRX extra
    for month, day, name in _KRX_EXTRA_HOLIDAYS:
        holidays[date(year, month, day)] = name

    # Lunar
    for month, day, name in _LUNAR_HOLIDAYS.get(year, []):
        holidays[date(year, month, day)] = name

    return holidays


# Cache per year
_holiday_cache: dict[int, dict[date, str]] = {}


def _holidays(year: int) -> dict[date, str]:
    if year not in _holiday_cache:
        _holiday_cache[year] = _get_holidays_for_year(year)
    return _holiday_cache[year]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_trading_day(d: date | None = None) -> bool:
    """Return True if the given date is a KRX trading day (weekday + not a holiday)."""
    if d is None:
        d = datetime.now(KST).date()

    # Weekend
    if d.weekday() >= 5:
        return False

    # Holiday
    if d in _holidays(d.year):
        return False

    return True


def get_holiday_name(d: date) -> str | None:
    """Return the holiday name if the date is a known holiday, else None."""
    return _holidays(d.year).get(d)


def get_current_session(now: datetime | None = None) -> tuple[MarketSession, str]:
    """Determine the current market session based on KST time.

    Returns:
        (session_enum, human_readable_description)
    """
    if now is None:
        now = datetime.now(KST)
    else:
        now = now.astimezone(KST)

    today = now.date()

    # Non-trading day
    if not is_trading_day(today):
        holiday = get_holiday_name(today)
        if today.weekday() >= 5:
            desc = "주말 (장 휴무)"
        elif holiday:
            desc = f"공휴일: {holiday}"
        else:
            desc = "장 마감"
        return MarketSession.CLOSED, desc

    current_time = now.time()

    # Walk through ordered sessions
    for session, (start, end) in _SESSION_BOUNDARIES.items():
        if start <= current_time < end:
            return session, _SESSION_DESCRIPTIONS[session]

    # Gap between closing auction and after-hours (15:30-15:40)
    if time(15, 30) <= current_time < time(15, 40):
        return MarketSession.CLOSED, "장 마감 (시간외 단일가 대기 15:40~)"

    # Before pre-market
    if current_time < time(8, 0):
        return MarketSession.CLOSED, "장 개시 전 (08:00 이후 주문 접수)"

    # After all sessions
    return MarketSession.CLOSED, "장 마감"


def get_session_times(d: date | None = None) -> dict:
    """Return all session boundary times for a given date.

    Returns dict with keys matching MarketSession names and (start, end) time pairs,
    plus metadata about whether the day is a trading day.
    """
    if d is None:
        d = datetime.now(KST).date()

    trading = is_trading_day(d)
    holiday = get_holiday_name(d)

    result: dict = {
        "date": d.isoformat(),
        "is_trading_day": trading,
        "holiday": holiday,
        "sessions": {},
    }

    if not trading:
        return result

    tz = KST
    for session, (start, end) in _SESSION_BOUNDARIES.items():
        result["sessions"][session.value] = {
            "start": datetime.combine(d, start, tzinfo=tz).isoformat(),
            "end": datetime.combine(d, end, tzinfo=tz).isoformat(),
            "description": _SESSION_DESCRIPTIONS[session],
        }

    return result


def next_session_open(now: datetime | None = None) -> datetime:
    """Return the datetime (KST) when the next trading session opens.

    "Next session open" means the next PRE_MARKET start (08:00 KST) on a trading day.
    If we are currently before 08:00 on a trading day, returns today 08:00.
    """
    if now is None:
        now = datetime.now(KST)
    else:
        now = now.astimezone(KST)

    today = now.date()

    # If today is a trading day and we haven't passed all sessions yet
    if is_trading_day(today):
        pre_market_start = datetime.combine(today, time(8, 0), tzinfo=KST)
        if now < pre_market_start:
            return pre_market_start

        # If we're still within any session, "next" means next day
        after_hours_end = datetime.combine(today, time(16, 0), tzinfo=KST)
        if now < after_hours_end:
            # Currently in a session — next open is tomorrow (or next trading day)
            pass
        # else: past 16:00, look for next day

    # Search forward up to 10 days (covers weekends + holiday clusters)
    candidate = today + timedelta(days=1)
    for _ in range(10):
        if is_trading_day(candidate):
            return datetime.combine(candidate, time(8, 0), tzinfo=KST)
        candidate += timedelta(days=1)

    # Fallback: should not reach here unless holidays table is incomplete
    return datetime.combine(candidate, time(8, 0), tzinfo=KST)
