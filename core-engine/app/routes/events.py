"""Market events API — collect and serve major events for chart annotation."""

import logging

import asyncpg
from fastapi import APIRouter, Depends, Query

from app.deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/range")
async def api_events_range(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    min_importance: int = Query(default=2, ge=1, le=5),
    pool: asyncpg.Pool = Depends(get_db),
):
    """Get market events for a date range (used by chart component)."""
    from app.services.event_collector import get_events_for_range
    events = await get_events_for_range(
        pool=pool, start_date=start_date, end_date=end_date,
        min_importance=min_importance,
    )
    return {"events": events, "count": len(events)}


@router.post("/collect")
async def api_collect_events(
    period: str = Query(default="1개월"),
    pool: asyncpg.Pool = Depends(get_db),
):
    """Collect recent events via OpenAI API.

    Should be called daily (via n8n or cron).
    """
    from app.services.event_collector import collect_recent_events
    return await collect_recent_events(pool=pool, period=period)


@router.post("/seed")
async def api_seed_events(
    start_year: int = Query(default=1997),
    end_year: int = Query(default=2026),
    pool: asyncpg.Pool = Depends(get_db),
):
    """Seed historical events via OpenAI API.

    One-time call to populate database with major historical events.
    """
    from app.services.event_collector import seed_historical_events
    return await seed_historical_events(pool=pool, start_year=start_year, end_year=end_year)


@router.get("/stats")
async def api_events_stats(pool: asyncpg.Pool = Depends(get_db)):
    """Get event database statistics."""
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM market_events")
        by_category = await conn.fetch(
            "SELECT category, COUNT(*) as cnt FROM market_events GROUP BY category ORDER BY cnt DESC"
        )
        by_year = await conn.fetch(
            "SELECT EXTRACT(YEAR FROM date)::int as year, COUNT(*) as cnt "
            "FROM market_events GROUP BY year ORDER BY year DESC LIMIT 10"
        )
        latest = await conn.fetch(
            "SELECT date, label, category, importance FROM market_events ORDER BY date DESC LIMIT 5"
        )

    return {
        "total": total,
        "by_category": [{"category": r["category"], "count": r["cnt"]} for r in by_category],
        "by_year": [{"year": r["year"], "count": r["cnt"]} for r in by_year],
        "latest": [{"date": str(r["date"]), "label": r["label"], "category": r["category"], "importance": r["importance"]} for r in latest],
    }
