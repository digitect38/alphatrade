import logging
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import redis.asyncio as aioredis

from app.config import settings
from app.models.ohlcv import OHLCVRecord

logger = logging.getLogger(__name__)

TOKEN_REDIS_KEY = "kis:access_token"


class KISClient:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=settings.http_timeout_default)
        self._redis: aioredis.Redis | None = None
        self._token: str | None = None

    async def initialize(self, redis_client: aioredis.Redis):
        self._redis = redis_client
        cached = await self._redis.get(TOKEN_REDIS_KEY)
        if cached:
            self._token = cached
            logger.info("KIS token loaded from Redis cache")

    async def close(self):
        await self.client.aclose()

    async def _ensure_token(self) -> str:
        """Get or refresh the OAuth access token."""
        if self._token:
            return self._token

        if not settings.kis_app_key or not settings.kis_app_secret:
            raise ValueError("KIS_APP_KEY and KIS_APP_SECRET must be configured")

        resp = await self.client.post(
            f"{settings.kis_base_url}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": settings.kis_app_key,
                "appsecret": settings.kis_app_secret,
            },
        )
        data = resp.json()

        if "access_token" not in data:
            raise RuntimeError(f"KIS token request failed: {data}")

        self._token = data["access_token"]

        if self._redis:
            await self._redis.setex(TOKEN_REDIS_KEY, settings.cache_kis_token_ttl, self._token)

        logger.info("KIS access token refreshed")
        return self._token

    def _auth_headers(self, token: str, tr_id: str) -> dict:
        return {
            "authorization": f"Bearer {token}",
            "appkey": settings.kis_app_key,
            "appsecret": settings.kis_app_secret,
            "tr_id": tr_id,
            "content-type": "application/json; charset=utf-8",
        }

    async def _request_with_retry(self, method: str, url: str, tr_id: str, **kwargs) -> dict:
        """Make an authenticated request with retry on 401 and transient network errors."""
        from app.utils.retry import retry_async

        async def _do_request():
            token = await self._ensure_token()
            headers = self._auth_headers(token, tr_id)
            resp = await self.client.request(method, url, headers=headers, **kwargs)

            if resp.status_code == 401:
                self._token = None
                token = await self._ensure_token()
                headers = self._auth_headers(token, tr_id)
                resp = await self.client.request(method, url, headers=headers, **kwargs)

            resp.raise_for_status()
            return resp.json()

        return await retry_async(_do_request, max_retries=3, base_delay=1.0)

    async def get_current_price(self, stock_code: str, pool=None) -> OHLCVRecord | None:
        """Get current price for a stock (주식현재가 시세).

        Priority: Redis cache → KIS API (saves to DB on success).
        If KIS fails, falls back to latest DB record.
        """
        try:
            data = await self._request_with_retry(
                "GET",
                f"{settings.kis_base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
                tr_id="FHKST01010100",
                params={
                    "fid_cond_mrkt_div_code": "J",
                    "fid_input_iscd": stock_code,
                },
            )

            output = data.get("output", {})
            if not output:
                return None

            now = datetime.now(timezone.utc)
            record = OHLCVRecord(
                time=now,
                stock_code=stock_code,
                open=Decimal(output.get("stck_oprc", "0")),
                high=Decimal(output.get("stck_hgpr", "0")),
                low=Decimal(output.get("stck_lwpr", "0")),
                close=Decimal(output.get("stck_prpr", "0")),
                volume=int(output.get("acml_vol", "0")),
                value=int(output.get("acml_tr_pbmn", "0")),
                interval="1d",
            )

            # Cache to DB (today's snapshot)
            if pool and record.close > 0:
                try:
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "INSERT INTO ohlcv (time, stock_code, open, high, low, close, volume, value, interval) "
                            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, '1m') ON CONFLICT DO NOTHING",
                            now, stock_code, record.close, record.close, record.close, record.close,
                            record.volume, record.value,
                        )
                except Exception:
                    pass

            return record
        except Exception as e:
            # Fallback: latest DB record
            if pool:
                try:
                    async with pool.acquire() as conn:
                        row = await conn.fetchrow(
                            "SELECT time, open, high, low, close, volume, value FROM ohlcv "
                            "WHERE stock_code = $1 AND interval = '1d' ORDER BY time DESC LIMIT 1",
                            stock_code,
                        )
                    if row and row["close"]:
                        logger.info("KIS failed for %s, using DB fallback (date=%s)", stock_code, str(row["time"])[:10])
                        return OHLCVRecord(
                            time=row["time"].replace(tzinfo=timezone.utc) if row["time"].tzinfo is None else row["time"],
                            stock_code=stock_code,
                            open=Decimal(str(row["open"])), high=Decimal(str(row["high"])),
                            low=Decimal(str(row["low"])), close=Decimal(str(row["close"])),
                            volume=int(row["volume"] or 0), value=int(row["value"] or 0), interval="1d",
                        )
                except Exception:
                    pass
            from app.exceptions import ExternalAPIError
            logger.error("KIS get_current_price failed for %s: %s", stock_code, e)
            raise ExternalAPIError(f"KIS API error for {stock_code}: {e}", retryable=True) from e

    async def get_daily_chart(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        pool=None,
    ) -> list[OHLCVRecord]:
        """Get daily OHLCV chart data with DB-first caching.

        1. Check DB for existing data in [start_date, end_date]
        2. Identify missing date ranges
        3. Fetch only missing data from KIS API
        4. Save new data to DB
        5. Return merged result
        """
        db_records: list[OHLCVRecord] = []
        existing_dates: set[str] = set()

        # Step 1: Load existing data from DB
        if pool:
            try:
                import asyncpg
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT time, open, high, low, close, volume, value FROM ohlcv "
                        "WHERE stock_code = $1 AND interval = '1d' "
                        "AND time::date >= $2::date AND time::date <= $3::date "
                        "ORDER BY time ASC",
                        stock_code, start_date, end_date,
                    )
                for r in rows:
                    dt_str = r["time"].strftime("%Y%m%d") if hasattr(r["time"], "strftime") else str(r["time"])[:10].replace("-", "")
                    existing_dates.add(dt_str)
                    db_records.append(OHLCVRecord(
                        time=r["time"] if hasattr(r["time"], "tzinfo") and r["time"].tzinfo else r["time"].replace(tzinfo=timezone.utc),
                        stock_code=stock_code,
                        open=Decimal(str(r["open"])), high=Decimal(str(r["high"])),
                        low=Decimal(str(r["low"])), close=Decimal(str(r["close"])),
                        volume=int(r["volume"] or 0), value=int(r["value"] or 0), interval="1d",
                    ))
                if existing_dates:
                    logger.info("KIS chart %s: %d days in DB, fetching gaps from API", stock_code, len(existing_dates))
            except Exception as e:
                logger.debug("DB pre-fetch failed for %s: %s", stock_code, e)

        # Step 2: Fetch from KIS API
        api_records: list[OHLCVRecord] = []
        try:
            data = await self._request_with_retry(
                "GET",
                f"{settings.kis_base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                tr_id="FHKST03010100",
                params={
                    "fid_cond_mrkt_div_code": "J",
                    "fid_input_iscd": stock_code,
                    "fid_input_date_1": start_date,
                    "fid_input_date_2": end_date,
                    "fid_period_div_code": "D",
                    "fid_org_adj_prc": "0",
                },
            )

            for item in data.get("output2", []):
                date_str = item.get("stck_bsop_date", "")
                if not date_str:
                    continue
                # Skip dates already in DB
                if date_str in existing_dates:
                    continue
                try:
                    time = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
                except ValueError:
                    continue

                rec = OHLCVRecord(
                    time=time, stock_code=stock_code,
                    open=Decimal(item.get("stck_oprc", "0")),
                    high=Decimal(item.get("stck_hgpr", "0")),
                    low=Decimal(item.get("stck_lwpr", "0")),
                    close=Decimal(item.get("stck_clpr", "0")),
                    volume=int(item.get("acml_vol", "0")),
                    value=int(item.get("acml_tr_pbmn", "0")),
                    interval="1d",
                )
                api_records.append(rec)
        except Exception as e:
            logger.error("KIS get_daily_chart failed for %s: %s", stock_code, e)

        # Step 3: Save new records to DB
        if api_records and pool:
            try:
                async with pool.acquire() as conn:
                    for rec in api_records:
                        await conn.execute(
                            "INSERT INTO ohlcv (time, stock_code, open, high, low, close, volume, value, interval) "
                            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, '1d') ON CONFLICT DO NOTHING",
                            rec.time, stock_code, rec.open, rec.high, rec.low, rec.close, rec.volume, rec.value,
                        )
                logger.info("KIS chart %s: saved %d new records to DB", stock_code, len(api_records))
            except Exception as e:
                logger.debug("DB save failed for %s chart: %s", stock_code, e)

        # Step 4: Merge and sort
        all_records = db_records + api_records
        all_records.sort(key=lambda r: r.time)
        return all_records

    async def get_account_balance(self) -> dict | None:
        """Get account balance (주식잔고조회) for broker reconciliation.

        Returns: {"cash": float, "positions": [{"stock_code", "quantity", "avg_price", "current_price"}]}
        """
        try:
            # 모의투자: VTTC8434R, 실전: TTTC8434R
            tr_id = "VTTC8434R" if "vts" in settings.kis_base_url else "TTTC8434R"
            data = await self._request_with_retry(
                "GET",
                f"{settings.kis_base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
                tr_id=tr_id,
                params={
                    "CANO": settings.kis_cano,
                    "ACNT_PRDT_CD": settings.kis_acnt_prdt_cd,
                    "AFHR_FLPR_YN": "N",
                    "OFL_YN": "",
                    "INQR_DVSN": "02",
                    "UNPR_DVSN": "01",
                    "FUND_STTL_ICLD_YN": "N",
                    "FNCG_AMT_AUTO_RDPT_YN": "N",
                    "PRCS_DVSN": "01",
                    "CTX_AREA_FK100": "",
                    "CTX_AREA_NK100": "",
                },
            )

            positions = []
            for item in data.get("output1", []):
                qty = int(item.get("hldg_qty", "0"))
                if qty <= 0:
                    continue
                positions.append({
                    "stock_code": item.get("pdno", ""),
                    "stock_name": item.get("prdt_name", ""),
                    "quantity": qty,
                    "avg_price": float(item.get("pchs_avg_pric", "0")),
                    "current_price": float(item.get("prpr", "0")),
                    "eval_amount": float(item.get("evlu_amt", "0")),
                })

            # output2 has account summary
            summary = data.get("output2", [{}])
            if isinstance(summary, list) and summary:
                summary = summary[0]
            cash = float(summary.get("dnca_tot_amt", "0")) if summary else 0

            return {"cash": cash, "positions": positions}

        except Exception as e:
            logger.error("KIS get_account_balance failed: %s", e)
            return None
