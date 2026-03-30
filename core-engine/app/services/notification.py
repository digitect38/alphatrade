"""Notification service — Telegram + KakaoTalk alerts.

Sends alerts on:
- Stock price surge/drop (>2%)
- Stop-loss / Take-profit triggers
- Trading cycle results
- System errors
"""

import logging
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.utils.market_calendar import KST

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=settings.http_timeout_notification)

    async def close(self):
        await self.client.aclose()

    # === Telegram ===

    async def send_telegram(self, message: str) -> bool:
        """Send message via Telegram Bot API."""
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            logger.debug("Telegram not configured, skipping")
            return False

        try:
            from app.utils.retry import retry_async
            resp = await retry_async(
                self.client.post,
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={"chat_id": settings.telegram_chat_id, "text": message, "parse_mode": "HTML"},
                max_retries=2,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error("Telegram send failed: %s", e)
            return False

    # === KakaoTalk (나에게 보내기) ===

    async def send_kakao(self, message: str) -> bool:
        """Send message via KakaoTalk 나에게 보내기 API."""
        if not settings.kakao_access_token:
            logger.debug("KakaoTalk not configured, skipping")
            return False

        try:
            import json
            template = {
                "object_type": "text",
                "text": message[:300],  # 카카오 텍스트 최대 300자
                "link": {
                    "web_url": "http://localhost:3000",
                    "mobile_web_url": "http://localhost:3000",
                },
            }
            resp = await self.client.post(
                "https://kapi.kakao.com/v2/api/talk/memo/default/send",
                headers={
                    "Authorization": f"Bearer {settings.kakao_access_token}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"template_object": json.dumps(template)},
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error("KakaoTalk send failed: %s", e)
            return False

    # === High-level Alert Methods ===

    async def alert(self, message: str):
        """Send alert to all configured channels."""
        await self.send_telegram(message)
        await self.send_kakao(message)

    async def alert_price_surge(self, stock_name: str, stock_code: str,
                                 change_pct: float, price: float, volume: int):
        """Alert when a stock has unusual price movement."""
        direction = "급등" if change_pct > 0 else "급락"
        emoji = "🔴" if change_pct > 0 else "🔵"

        msg = (
            f"{emoji} <b>[{direction} 알림]</b>\n"
            f"종목: {stock_name} ({stock_code})\n"
            f"변동: {change_pct:+.2f}%\n"
            f"현재가: {price:,.0f}원\n"
            f"거래량: {volume:,}\n"
            f"시간: {datetime.now(KST).strftime('%H:%M')}"
        )
        await self.alert(msg)

    async def alert_stop_loss(self, stock_name: str, stock_code: str,
                               pnl_pct: float, quantity: int):
        """Alert when stop-loss triggers."""
        msg = (
            f"🛑 <b>[손절 발동]</b>\n"
            f"종목: {stock_name} ({stock_code})\n"
            f"손실: {pnl_pct:.2f}%\n"
            f"수량: {quantity}주 전량 매도\n"
            f"시간: {datetime.now(KST).strftime('%H:%M')}"
        )
        await self.alert(msg)

    async def alert_take_profit(self, stock_name: str, stock_code: str,
                                 pnl_pct: float, quantity: int):
        """Alert when take-profit triggers."""
        msg = (
            f"✅ <b>[익절 발동]</b>\n"
            f"종목: {stock_name} ({stock_code})\n"
            f"수익: +{pnl_pct:.2f}%\n"
            f"수량: {quantity}주 전량 매도\n"
            f"시간: {datetime.now(KST).strftime('%H:%M')}"
        )
        await self.alert(msg)

    async def alert_order_filled(self, stock_name: str, stock_code: str,
                                  side: str, quantity: int, price: float):
        """Alert when an order is filled."""
        emoji = "🔴" if side == "BUY" else "🔵"
        action = "매수" if side == "BUY" else "매도"
        msg = (
            f"{emoji} <b>[{action} 체결]</b>\n"
            f"종목: {stock_name} ({stock_code})\n"
            f"수량: {quantity}주\n"
            f"가격: {price:,.0f}원\n"
            f"금액: {quantity * price:,.0f}원"
        )
        await self.alert(msg)

    async def alert_cycle_complete(self, orders: int, errors: int,
                                    total_value: float, daily_pnl: float):
        """Alert with trading cycle summary."""
        emoji = "📊" if errors == 0 else "⚠️"
        msg = (
            f"{emoji} <b>[매매 사이클 완료]</b>\n"
            f"주문: {orders}건\n"
            f"오류: {errors}건\n"
            f"총자산: {total_value:,.0f}원\n"
            f"일간손익: {daily_pnl:+,.0f}원"
        )
        await self.alert(msg)

    async def alert_system_error(self, error: str):
        """Alert on system error."""
        msg = (
            f"🚨 <b>[시스템 오류]</b>\n"
            f"{error[:200]}"
        )
        await self.alert(msg)
