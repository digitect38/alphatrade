"""Market move detection and alert API.

Detects significant market changes from:
1. News surge — sudden increase in news articles for stocks/sectors
2. Index change — KOSPI/KOSDAQ index sharp moves
3. Volume spike — abnormal volume in universe stocks

Sends alerts via KakaoTalk + Telegram.
"""

import logging
from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, Depends

from app.config import settings
from app.deps import get_db, get_kis_client, get_notifier
from app.services.kis_api import KISClient
from app.services.notification import NotificationService

logger = logging.getLogger(__name__)
router = APIRouter()


async def _detect_news_surge(pool: asyncpg.Pool) -> list[dict]:
    """Detect stocks with unusual news activity in the last hour vs daily average."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH recent AS (
                SELECT unnest(stock_codes) as stock_code, count(*) as recent_count
                FROM news
                WHERE time > NOW() - INTERVAL '1 hour'
                GROUP BY stock_code
            ),
            daily_avg AS (
                SELECT unnest(stock_codes) as stock_code,
                       count(*) / GREATEST(EXTRACT(EPOCH FROM (NOW() - MIN(time))) / 3600, 1) as hourly_avg
                FROM news
                WHERE time > NOW() - INTERVAL '7 days'
                GROUP BY stock_code
            )
            SELECT r.stock_code, s.stock_name,
                   r.recent_count,
                   COALESCE(d.hourly_avg, 0) as hourly_avg
            FROM recent r
            LEFT JOIN daily_avg d ON r.stock_code = d.stock_code
            LEFT JOIN stocks s ON r.stock_code = s.stock_code
            WHERE r.recent_count >= 3
              AND r.recent_count > COALESCE(d.hourly_avg, 0) * 2
            ORDER BY r.recent_count DESC
            LIMIT 10
            """
        )
    return [
        {
            "stock_code": r["stock_code"],
            "stock_name": r["stock_name"] or r["stock_code"],
            "recent_news": r["recent_count"],
            "avg_hourly": round(float(r["hourly_avg"]), 1),
            "type": "news_surge",
        }
        for r in rows
    ]


async def _detect_price_moves(pool: asyncpg.Pool, kis_client: KISClient) -> list[dict]:
    """Detect universe stocks with significant price changes."""
    async with pool.acquire() as conn:
        universe = await conn.fetch(
            """
            SELECT u.stock_code, s.stock_name,
                   (SELECT close FROM ohlcv WHERE stock_code = u.stock_code AND interval = '1d'
                    ORDER BY time DESC LIMIT 1) as prev_close
            FROM universe u
            JOIN stocks s ON u.stock_code = s.stock_code
            WHERE u.is_active = TRUE
            """
        )

    moves = []
    for row in universe:
        prev_close = float(row["prev_close"]) if row["prev_close"] else 0
        if prev_close <= 0:
            continue

        try:
            current = await kis_client.get_current_price(row["stock_code"])
            if not current:
                continue
            price = float(current.close)
            change_pct = (price - prev_close) / prev_close * 100

            if abs(change_pct) >= settings.scanner_price_surge_alert_pct:
                moves.append({
                    "stock_code": row["stock_code"],
                    "stock_name": row["stock_name"],
                    "prev_close": prev_close,
                    "current_price": price,
                    "change_pct": round(change_pct, 2),
                    "volume": current.volume,
                    "type": "price_move",
                })
        except Exception:
            continue

    moves.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
    return moves[:10]


async def _detect_recent_disclosures(pool: asyncpg.Pool) -> list[dict]:
    """Detect major disclosures in the last hour."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT d.stock_code, s.stock_name, d.report_name, d.url, d.time
            FROM disclosures d
            LEFT JOIN stocks s ON d.stock_code = s.stock_code
            WHERE d.time > NOW() - INTERVAL '1 hour'
              AND d.is_major = TRUE
            ORDER BY d.time DESC
            LIMIT 5
            """
        )
    return [
        {
            "stock_code": r["stock_code"],
            "stock_name": r["stock_name"] or r["stock_code"],
            "report": r["report_name"],
            "url": r["url"],
            "type": "major_disclosure",
        }
        for r in rows
    ]


def _format_alert_message(alerts: list[dict]) -> str:
    """Format alert items into a KakaoTalk-friendly message."""
    if not alerts:
        return ""

    lines = ["📊 [AlphaTrade 시장 알림]", ""]

    news_alerts = [a for a in alerts if a["type"] == "news_surge"]
    price_alerts = [a for a in alerts if a["type"] == "price_move"]
    disc_alerts = [a for a in alerts if a["type"] == "major_disclosure"]

    if price_alerts:
        lines.append("🔔 급변 종목:")
        for a in price_alerts[:5]:
            arrow = "📈" if a["change_pct"] > 0 else "📉"
            lines.append(f"  {arrow} {a['stock_name']}({a['stock_code']}) {a['change_pct']:+.1f}%")
        lines.append("")

    if news_alerts:
        lines.append("📰 뉴스 급증:")
        for a in news_alerts[:5]:
            lines.append(f"  • {a['stock_name']} — {a['recent_news']}건 (평소 {a['avg_hourly']}/h)")
        lines.append("")

    if disc_alerts:
        lines.append("📋 주요 공시:")
        for a in disc_alerts[:3]:
            lines.append(f"  • {a['stock_name']}: {a['report'][:30]}")

    return "\n".join(lines)


@router.post("/scan")
async def scan_market_moves(
    pool: asyncpg.Pool = Depends(get_db),
    kis_client: KISClient = Depends(get_kis_client),
    notifier: NotificationService = Depends(get_notifier),
):
    """Scan for market moves and send alerts via KakaoTalk + Telegram.

    Detects: price surges, news volume spikes, major disclosures.
    Should be called periodically (e.g., every 10 minutes during market hours).
    """
    now = datetime.now(timezone.utc)
    all_alerts = []

    # 1. Price moves (from KIS API)
    try:
        price_moves = await _detect_price_moves(pool, kis_client)
        all_alerts.extend(price_moves)
    except Exception as e:
        logger.error("Price move detection failed: %s", e)

    # 2. News surge
    try:
        news_surges = await _detect_news_surge(pool)
        all_alerts.extend(news_surges)
    except Exception as e:
        logger.error("News surge detection failed: %s", e)

    # 3. Major disclosures
    try:
        disclosures = await _detect_recent_disclosures(pool)
        all_alerts.extend(disclosures)
    except Exception as e:
        logger.error("Disclosure detection failed: %s", e)

    # Send alert if anything detected
    sent = False
    if all_alerts:
        message = _format_alert_message(all_alerts)
        if message:
            await notifier.alert(message)
            sent = True
            logger.info("Market alert sent: %d items", len(all_alerts))

    return {
        "scanned_at": now.isoformat(),
        "alerts_count": len(all_alerts),
        "alerts": all_alerts,
        "notification_sent": sent,
    }
