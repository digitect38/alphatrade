import logging
from datetime import datetime, timezone

import asyncpg
from app.models.analysis import SectorOverview, SectorResult, StockRank

logger = logging.getLogger(__name__)


async def analyze_sector(sector: str | None = None, *, pool: asyncpg.Pool) -> SectorOverview:
    """Analyze sector performance and relative strength."""
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        # Get sectors with active stocks
        if sector:
            sector_rows = await conn.fetch(
                "SELECT DISTINCT sector FROM stocks WHERE sector = $1 AND is_active = TRUE",
                sector,
            )
        else:
            sector_rows = await conn.fetch(
                "SELECT DISTINCT sector FROM stocks WHERE sector IS NOT NULL AND is_active = TRUE ORDER BY sector"
            )

        if not sector_rows:
            return SectorOverview(sectors=[], computed_at=now)

        sectors = [r["sector"] for r in sector_rows]
        results = []

        for sec in sectors:
            result = await _analyze_single_sector(conn, sec)
            if result:
                results.append(result)

    return SectorOverview(sectors=results, computed_at=now)


async def _analyze_single_sector(conn, sector: str) -> SectorResult | None:
    """Analyze a single sector."""
    now = datetime.now(timezone.utc)

    # Get stocks in this sector
    stocks = await conn.fetch(
        "SELECT stock_code, stock_name FROM stocks WHERE sector = $1 AND is_active = TRUE",
        sector,
    )

    if not stocks:
        return None

    stock_codes = [s["stock_code"] for s in stocks]
    stock_names = {s["stock_code"]: s["stock_name"] for s in stocks}

    # Calculate returns for each stock (1d, 5d, 20d)
    stock_ranks = []
    sector_return_1d = []
    sector_return_5d = []
    sector_return_20d = []

    for code in stock_codes:
        # Get latest 21 daily closes
        rows = await conn.fetch(
            """
            SELECT time, close
            FROM ohlcv
            WHERE stock_code = $1 AND interval = '1d'
            ORDER BY time DESC
            LIMIT 21
            """,
            code,
        )

        if len(rows) < 2:
            continue

        closes = [float(r["close"]) for r in reversed(rows)]

        ret_1d = (closes[-1] / closes[-2] - 1) * 100 if len(closes) >= 2 and closes[-2] > 0 else None
        ret_5d = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 and closes[-6] > 0 else None
        ret_20d = (closes[-1] / closes[0] - 1) * 100 if len(closes) >= 21 and closes[0] > 0 else None

        stock_ranks.append(
            StockRank(
                stock_code=code,
                stock_name=stock_names.get(code, ""),
                return_1d=round(ret_1d, 2) if ret_1d is not None else None,
                return_5d=round(ret_5d, 2) if ret_5d is not None else None,
                return_20d=round(ret_20d, 2) if ret_20d is not None else None,
            )
        )

        if ret_1d is not None:
            sector_return_1d.append(ret_1d)
        if ret_5d is not None:
            sector_return_5d.append(ret_5d)
        if ret_20d is not None:
            sector_return_20d.append(ret_20d)

    if not stock_ranks:
        return None

    avg_1d = round(sum(sector_return_1d) / len(sector_return_1d), 2) if sector_return_1d else None
    avg_5d = round(sum(sector_return_5d) / len(sector_return_5d), 2) if sector_return_5d else None
    avg_20d = round(sum(sector_return_20d) / len(sector_return_20d), 2) if sector_return_20d else None

    # Sort stocks by 1-day return
    top = sorted(
        [s for s in stock_ranks if s.return_1d is not None],
        key=lambda x: x.return_1d or 0,
        reverse=True,
    )[:5]
    bottom = sorted(
        [s for s in stock_ranks if s.return_1d is not None],
        key=lambda x: x.return_1d or 0,
    )[:5]

    return SectorResult(
        sector=sector,
        return_1d=avg_1d,
        return_5d=avg_5d,
        return_20d=avg_20d,
        relative_strength=None,  # Requires KOSPI index data
        top_stocks=top,
        bottom_stocks=bottom,
        computed_at=now,
    )
