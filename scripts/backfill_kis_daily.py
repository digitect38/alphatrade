#!/usr/bin/env python3
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
CORE_ENGINE_DIR = ROOT / "core-engine"
if str(CORE_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_ENGINE_DIR))

from app.config import settings  # noqa: E402
from app.services.kis_api import KISClient  # noqa: E402


async def _load_active_universe(pool: asyncpg.Pool) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT stock_code FROM universe WHERE is_active = TRUE ORDER BY stock_code")
    return [row["stock_code"] for row in rows]


async def _replace_daily_bars(pool: asyncpg.Pool, stock_code: str, records) -> int:
    if not records:
        return 0

    earliest = min(record.time for record in records)
    latest = max(record.time for record in records) + timedelta(days=1)

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                DELETE FROM ohlcv
                WHERE stock_code = $1
                  AND interval = '1d'
                  AND time >= $2
                  AND time < $3
                """,
                stock_code,
                earliest,
                latest,
            )

            inserted = 0
            for record in records:
                await conn.execute(
                    """
                    INSERT INTO ohlcv (time, stock_code, open, high, low, close, volume, value, interval)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, '1d')
                    """,
                    record.time,
                    record.stock_code,
                    record.open,
                    record.high,
                    record.low,
                    record.close,
                    record.volume,
                    record.value,
                )
                inserted += 1
    return inserted


async def main() -> int:
    pool = await asyncpg.create_pool(settings.database_url)
    kis = KISClient()

    start_date = (datetime.now(timezone.utc) - timedelta(days=370)).strftime("%Y%m%d")
    end_date = datetime.now(timezone.utc).strftime("%Y%m%d")

    try:
        stock_codes = await _load_active_universe(pool)
        total_inserted = 0
        failures: list[str] = []

        print(f"Backfilling daily OHLCV for {len(stock_codes)} active symbols: {start_date}..{end_date}")

        for index, stock_code in enumerate(stock_codes, start=1):
            try:
                records = await kis.get_daily_chart(stock_code, start_date, end_date)
                inserted = await _replace_daily_bars(pool, stock_code, records)
                total_inserted += inserted
                print(f"[{index}/{len(stock_codes)}] {stock_code}: inserted {inserted} daily bars")
            except Exception as exc:
                failures.append(f"{stock_code}: {exc}")
                print(f"[{index}/{len(stock_codes)}] {stock_code}: FAILED - {exc}")

        print(f"Done. Inserted {total_inserted} daily bars.")
        if failures:
            print("Failures:")
            for item in failures:
                print(f" - {item}")
            return 1
        return 0
    finally:
        await kis.close()
        await pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
