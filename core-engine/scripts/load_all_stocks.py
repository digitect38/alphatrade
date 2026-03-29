"""Load all KOSPI + KOSDAQ stocks from KRX into the stocks table.

Usage: python scripts/load_all_stocks.py
"""

import asyncio
import logging
from datetime import datetime

import asyncpg
from pykrx import stock as pykrx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main():
    from app.config import settings

    pool = await asyncpg.create_pool(dsn=settings.database_url, min_size=1, max_size=3)

    today = datetime.now().strftime("%Y%m%d")

    # Fetch all tickers from KRX
    logger.info("Fetching KOSPI tickers...")
    kospi_tickers = pykrx.get_market_ticker_list(today, market="KOSPI")
    logger.info("Found %d KOSPI tickers", len(kospi_tickers))

    logger.info("Fetching KOSDAQ tickers...")
    kosdaq_tickers = pykrx.get_market_ticker_list(today, market="KOSDAQ")
    logger.info("Found %d KOSDAQ tickers", len(kosdaq_tickers))

    inserted = 0
    updated = 0
    errors = 0

    async with pool.acquire() as conn:
        for market, tickers in [("KOSPI", kospi_tickers), ("KOSDAQ", kosdaq_tickers)]:
            for ticker in tickers:
                try:
                    name = pykrx.get_market_ticker_name(ticker)
                    if not name:
                        continue

                    # Get market cap and sector info
                    try:
                        cap_df = pykrx.get_market_cap(today, today, ticker)
                        market_cap = int(cap_df["시가총액"].iloc[0]) if len(cap_df) > 0 else None
                        listed_shares = int(cap_df["상장주식수"].iloc[0]) if len(cap_df) > 0 else None
                    except Exception:
                        market_cap = None
                        listed_shares = None

                    # Try to get sector
                    try:
                        sector_df = pykrx.get_market_ticker_and_name(today, market)
                        # pykrx doesn't directly provide sector, we'll set it later
                        sector = None
                    except Exception:
                        sector = None

                    # Upsert
                    result = await conn.execute(
                        """
                        INSERT INTO stocks (stock_code, stock_name, market, sector, market_cap, listed_shares, is_active)
                        VALUES ($1, $2, $3, $4, $5, $6, TRUE)
                        ON CONFLICT (stock_code) DO UPDATE SET
                            stock_name = EXCLUDED.stock_name,
                            market = EXCLUDED.market,
                            market_cap = COALESCE(EXCLUDED.market_cap, stocks.market_cap),
                            listed_shares = COALESCE(EXCLUDED.listed_shares, stocks.listed_shares),
                            is_active = TRUE,
                            updated_at = NOW()
                        """,
                        ticker, name, market, sector, market_cap, listed_shares,
                    )

                    if "INSERT" in result:
                        inserted += 1
                    else:
                        updated += 1

                except Exception as e:
                    logger.error("Failed for %s: %s", ticker, e)
                    errors += 1

            logger.info("%s done: inserted=%d, updated=%d so far", market, inserted, updated)

    # Now try to add sector info using KRX sector API
    logger.info("Fetching sector information...")
    try:
        for market_name, market_code in [("KOSPI", "KOSPI"), ("KOSDAQ", "KOSDAQ")]:
            sector_df = pykrx.get_index_ticker_list(today, market=market_code)
            for idx_ticker in sector_df:
                try:
                    idx_name = pykrx.get_index_ticker_name(idx_ticker)
                    # Get component stocks of this sector index
                    components = pykrx.get_index_portfolio_deposit_file(idx_ticker, today)
                    if components is not None and len(components) > 0:
                        async with pool.acquire() as conn:
                            for stock_code in components:
                                await conn.execute(
                                    "UPDATE stocks SET sector = $1 WHERE stock_code = $2 AND sector IS NULL",
                                    idx_name, stock_code,
                                )
                except Exception:
                    continue
    except Exception as e:
        logger.warning("Sector fetch partially failed: %s", e)

    # Final count
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT count(*) FROM stocks WHERE is_active = TRUE")
        kospi_count = await conn.fetchval("SELECT count(*) FROM stocks WHERE market = 'KOSPI' AND is_active = TRUE")
        kosdaq_count = await conn.fetchval("SELECT count(*) FROM stocks WHERE market = 'KOSDAQ' AND is_active = TRUE")
        with_sector = await conn.fetchval("SELECT count(*) FROM stocks WHERE sector IS NOT NULL AND is_active = TRUE")

    logger.info("=== Complete ===")
    logger.info("Total: %d (KOSPI: %d, KOSDAQ: %d)", total, kospi_count, kosdaq_count)
    logger.info("With sector: %d", with_sector)
    logger.info("Inserted: %d, Updated: %d, Errors: %d", inserted, updated, errors)

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
