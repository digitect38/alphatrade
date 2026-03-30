"""Event-driven scanner — fast path for market-move response.

Unlike the batch trading cycle (full universe scan), this scanner:
1. Receives a specific event (price spike, news, disclosure)
2. Classifies the event type
3. Re-evaluates ONLY impacted symbols
4. Generates actionable candidates with priority scores

This is the core of the "event-first" architecture shift.
"""

import logging
from datetime import datetime, timezone
from enum import Enum

import asyncpg
import redis.asyncio as aioredis

from app.config import settings
from app.services.market_state import MarketStateCache

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    PRICE_SPIKE = "price_spike"
    VOLUME_SURGE = "volume_surge"
    NEWS_CLUSTER = "news_cluster"
    DISCLOSURE = "disclosure"
    SECTOR_SYMPATHY = "sector_sympathy"
    TRADINGVIEW = "tradingview"


class EventCandidate:
    def __init__(self, stock_code: str, event_type: EventType, priority: float, details: dict):
        self.stock_code = stock_code
        self.event_type = event_type
        self.priority = priority  # 0-100
        self.details = details
        self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "stock_code": self.stock_code,
            "event_type": self.event_type.value,
            "priority": round(self.priority, 1),
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


async def scan_price_events(redis: aioredis.Redis, pool: asyncpg.Pool) -> list[EventCandidate]:
    """Scan cached market state for price spike events."""
    cache = MarketStateCache(redis)
    movers = await cache.get_top_movers(50)
    candidates = []

    for m in movers:
        change_pct = float(m.get("change_pct", 0))
        volume = int(m.get("volume", 0))
        code = m["stock_code"]

        # Price spike: > 3% move
        if abs(change_pct) >= settings.scanner_price_surge_alert_pct:
            priority = min(abs(change_pct) * 10, 100)
            candidates.append(EventCandidate(
                stock_code=code,
                event_type=EventType.PRICE_SPIKE,
                priority=priority,
                details={"change_pct": change_pct, "price": float(m.get("price", 0))},
            ))

        # Volume surge: check against 20-day average
        if volume > 0:
            async with pool.acquire() as conn:
                avg = await conn.fetchval(
                    "SELECT AVG(volume) FROM ohlcv WHERE stock_code = $1 AND interval = '1d' AND time > NOW() - INTERVAL '30 days'",
                    code,
                )
            if avg and float(avg) > 0 and volume / float(avg) > settings.scanner_volume_surge_ratio:
                ratio = volume / float(avg)
                priority = min(ratio * 15, 100)
                candidates.append(EventCandidate(
                    stock_code=code,
                    event_type=EventType.VOLUME_SURGE,
                    priority=priority,
                    details={"volume": volume, "avg_volume": float(avg), "ratio": round(ratio, 1)},
                ))

    return candidates


async def scan_news_events(pool: asyncpg.Pool) -> list[EventCandidate]:
    """Scan for stocks with unusual news activity."""
    candidates = []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT unnest(stock_codes) as stock_code, count(*) as cnt
            FROM news WHERE time > NOW() - INTERVAL '30 minutes'
            GROUP BY stock_code HAVING count(*) >= 2
            ORDER BY cnt DESC LIMIT 20
            """
        )
    for r in rows:
        priority = min(int(r["cnt"]) * 20, 100)
        candidates.append(EventCandidate(
            stock_code=r["stock_code"],
            event_type=EventType.NEWS_CLUSTER,
            priority=priority,
            details={"news_count_30min": int(r["cnt"])},
        ))
    return candidates


async def scan_disclosure_events(pool: asyncpg.Pool) -> list[EventCandidate]:
    """Scan for major disclosures in the last 30 minutes."""
    candidates = []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT stock_code, report_name FROM disclosures
            WHERE is_major = TRUE AND time > NOW() - INTERVAL '30 minutes'
            ORDER BY time DESC LIMIT 10
            """
        )
    for r in rows:
        candidates.append(EventCandidate(
            stock_code=r["stock_code"],
            event_type=EventType.DISCLOSURE,
            priority=80,
            details={"report": r["report_name"]},
        ))
    return candidates


async def run_event_scan(
    redis: aioredis.Redis,
    pool: asyncpg.Pool,
) -> dict:
    """Run full event scan — returns prioritized candidates.

    This is the FAST PATH: reads from cache, only re-evaluates impacted stocks.
    """
    now = datetime.now(timezone.utc)

    # Gather events from all sources
    price_events = await scan_price_events(redis, pool)
    news_events = await scan_news_events(pool)
    disc_events = await scan_disclosure_events(pool)

    all_candidates = price_events + news_events + disc_events

    # Deduplicate by stock_code (keep highest priority)
    best = {}
    for c in all_candidates:
        if c.stock_code not in best or c.priority > best[c.stock_code].priority:
            best[c.stock_code] = c

    # Sort by priority descending
    ranked = sorted(best.values(), key=lambda x: x.priority, reverse=True)

    # Enrich with stock names
    codes = [c.stock_code for c in ranked]
    name_map = {}
    if codes:
        async with pool.acquire() as conn:
            names = await conn.fetch(
                "SELECT stock_code, stock_name, sector FROM stocks WHERE stock_code = ANY($1::text[])",
                codes,
            )
        name_map = {r["stock_code"]: r for r in names}

    results = []
    for c in ranked[:30]:
        d = c.to_dict()
        info = name_map.get(c.stock_code, {})
        d["stock_name"] = info.get("stock_name", "")
        d["sector"] = info.get("sector", "")
        results.append(d)

    return {
        "scanned_at": now.isoformat(),
        "total_events": len(all_candidates),
        "unique_stocks": len(best),
        "candidates": results,
        "by_type": {
            "price_spike": len(price_events),
            "volume_surge": len([c for c in price_events if c.event_type == EventType.VOLUME_SURGE]),
            "news_cluster": len(news_events),
            "disclosure": len(disc_events),
        },
    }
