import logging
from datetime import datetime, timezone

import feedparser

from app.utils.market_calendar import KST
import httpx
from bs4 import BeautifulSoup

from app.models.news import NewsRecord

logger = logging.getLogger(__name__)

# 네이버 금융 뉴스 RSS
NAVER_FINANCE_RSS = "https://news.google.com/rss/search?q=한국+주식+시장&hl=ko&gl=KR&ceid=KR:ko"
NAVER_STOCK_NEWS_URL = "https://finance.naver.com/item/news_news.naver"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


class NaverNewsClient:
    def __init__(self):
        from app.config import settings
        self.client = httpx.AsyncClient(headers=HEADERS, timeout=settings.http_timeout_default, follow_redirects=True)

    async def close(self):
        await self.client.aclose()

    async def fetch_rss_news(self) -> list[NewsRecord]:
        """Fetch market news from Google News RSS (Korean stock market)."""
        records = []
        try:
            from app.utils.retry import retry_async
            resp = await retry_async(self.client.get, NAVER_FINANCE_RSS)
            feed = feedparser.parse(resp.text)

            for entry in feed.entries[:30]:
                published = datetime.now(timezone.utc)
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

                records.append(
                    NewsRecord(
                        time=published,
                        source="google_news",
                        title=entry.get("title", ""),
                        content=entry.get("summary", ""),
                        url=entry.get("link", ""),
                        category="market",
                    )
                )
        except Exception as e:
            logger.error("RSS fetch failed: %s", e)

        return records

    async def fetch_stock_news(self, stock_code: str) -> list[NewsRecord]:
        """Fetch news for a specific stock from Naver Finance."""
        records = []
        try:
            from app.utils.retry import retry_async
            resp = await retry_async(
                self.client.get, NAVER_STOCK_NEWS_URL,
                params={"code": stock_code, "page": 1, "sm": "title_entity_id.basic"},
            )
            soup = BeautifulSoup(resp.text, "lxml")

            rows = soup.select("table.type5 tbody tr")
            for row in rows:
                link_tag = row.select_one("td.title a")
                date_tag = row.select_one("td.date")
                source_tag = row.select_one("td.info")

                if not link_tag or not date_tag:
                    continue

                title = link_tag.get_text(strip=True)
                url = link_tag.get("href", "")
                if url.startswith("/"):
                    url = f"https://finance.naver.com{url}"

                date_str = date_tag.get_text(strip=True)
                try:
                    time = datetime.strptime(date_str, "%Y.%m.%d %H:%M")
                    time = time.replace(tzinfo=KST)
                except ValueError:
                    time = datetime.now(timezone.utc)

                source = source_tag.get_text(strip=True) if source_tag else "naver"

                records.append(
                    NewsRecord(
                        time=time,
                        source=source,
                        title=title,
                        url=url,
                        stock_codes=[stock_code],
                        category="stock",
                    )
                )
        except Exception as e:
            logger.error("Naver stock news fetch failed for %s: %s", stock_code, e)

        return records
