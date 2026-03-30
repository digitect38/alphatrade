import logging
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.utils.market_calendar import KST
from app.models.disclosure import DisclosureRecord

logger = logging.getLogger(__name__)

DART_BASE_URL = "https://opendart.fss.or.kr/api"

# 주요 공시 키워드
MAJOR_KEYWORDS = [
    "주요사항보고",
    "최대주주변경",
    "합병",
    "분할",
    "유상증자",
    "무상증자",
    "전환사채",
    "자기주식",
    "영업양수",
    "영업양도",
    "임원변경",
    "상장폐지",
    "회생절차",
    "부도",
    "감자",
    "공개매수",
]


class DARTClient:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=settings.http_timeout_default)

    async def close(self):
        await self.client.aclose()

    async def get_disclosure_list(
        self,
        bgn_de: str | None = None,
        end_de: str | None = None,
        corp_code: str | None = None,
        page_count: int = 100,
    ) -> list[DisclosureRecord]:
        """Fetch recent disclosures from DART API."""
        if not settings.dart_api_key:
            logger.warning("DART_API_KEY not configured, skipping")
            return []

        today = datetime.now(KST).strftime("%Y%m%d")
        params = {
            "crtfc_key": settings.dart_api_key,
            "bgn_de": bgn_de or today,
            "end_de": end_de or today,
            "page_count": str(page_count),
            "sort": "date",
            "sort_mth": "desc",
        }
        if corp_code:
            params["corp_code"] = corp_code

        records = []
        try:
            from app.utils.retry import retry_async
            resp = await retry_async(self.client.get, f"{DART_BASE_URL}/list.json", params=params)
            data = resp.json()

            if data.get("status") != "000":
                logger.warning("DART API returned status=%s: %s", data.get("status"), data.get("message"))
                return []

            for item in data.get("list", []):
                rcept_dt = item.get("rcept_dt", today)
                try:
                    time = datetime.strptime(rcept_dt, "%Y%m%d").replace(tzinfo=KST)
                except ValueError:
                    time = datetime.now(timezone.utc)

                report_nm = item.get("report_nm", "")
                stock_code = item.get("stock_code", "")

                if not stock_code:
                    continue

                records.append(
                    DisclosureRecord(
                        time=time,
                        stock_code=stock_code,
                        report_name=report_nm,
                        report_type=item.get("pblntf_ty", ""),
                        rcept_no=item.get("rcept_no", ""),
                        dcm_no=item.get("dcm_no", ""),
                        url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no', '')}",
                        is_major=self.is_major_disclosure(report_nm),
                    )
                )
        except Exception as e:
            from app.exceptions import ExternalAPIError
            logger.error("DART API request failed: %s", e)
            raise ExternalAPIError(f"DART API error: {e}", retryable=True) from e

        return records

    @staticmethod
    def is_major_disclosure(report_name: str) -> bool:
        return any(kw in report_name for kw in MAJOR_KEYWORDS)
