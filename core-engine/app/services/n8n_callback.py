"""Engine → n8n callback service (v1.3 Section 4.2).

Sends webhook callbacks to n8n when:
- New news collected (triggers WF-03 sentiment analysis)
- Strategy signal generated (triggers WF-05 trade alert)
- TradingView webhook received (triggers WF-08 strategy routing)
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# n8n webhook base URL (internal Docker network)
N8N_WEBHOOK_BASE = "http://n8n:5678/webhook"


async def notify_n8n(webhook_path: str, payload: dict) -> bool:
    """Send callback to n8n webhook endpoint.

    Args:
        webhook_path: path after /webhook/ (e.g., "news-collected")
        payload: JSON payload to send
    """
    url = f"{N8N_WEBHOOK_BASE}/{webhook_path}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code < 300:
            logger.debug("n8n callback OK: %s", webhook_path)
            return True
        else:
            logger.warning("n8n callback %s returned %d", webhook_path, resp.status_code)
            return False
    except Exception as e:
        # n8n callback failure should not block engine operations
        logger.debug("n8n callback %s failed (non-critical): %s", webhook_path, e)
        return False


async def on_news_collected(inserted: int, stock_codes: list[str]):
    """Callback after news collection — triggers WF-03 sentiment analysis."""
    if inserted > 0:
        await notify_n8n("news-collected", {
            "inserted": inserted,
            "stock_codes": stock_codes,
            "trigger": "WF-01",
        })


async def on_signal_generated(stock_code: str, signal: str, strength: float, score: float):
    """Callback after strategy signal — triggers WF-05 trade alert."""
    if signal in ("BUY", "SELL"):
        await notify_n8n("signal-generated", {
            "stock_code": stock_code,
            "signal": signal,
            "strength": strength,
            "score": score,
            "trigger": "strategy_engine",
        })


async def on_tradingview_received(ticker: str, action: str, price: float | None):
    """Callback after TradingView webhook — triggers WF-08 routing."""
    await notify_n8n("tradingview-signal", {
        "ticker": ticker,
        "action": action,
        "price": price,
        "trigger": "tradingview",
    })
