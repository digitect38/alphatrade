"""KIS WebSocket client for real-time stock price streaming.

한국투자증권 실시간 시세 WebSocket API:
- 모의투자: ws://ops.koreainvestment.com:31000
- 실전: ws://ops.koreainvestment.com:21000

Protocol:
1. REST로 승인키(approval_key) 발급
2. WebSocket 연결
3. 종목 구독 요청 (TR_ID: H0STCNT0 = 실시간 체결가)
4. 서버가 체결 데이터 push
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# KIS 실시간 TR_ID
TR_REALTIME_PRICE = "H0STCNT0"  # 실시간 체결가 (모의: H0STCNT0, 실전: H0STCNT0)


class KISWebSocketClient:
    """KIS real-time WebSocket client.

    Subscribes to stock price updates and publishes to Redis Pub/Sub.
    """

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
        self._approval_key: str | None = None
        self._ws = None
        self._subscribed: set[str] = set()
        self._running = False
        self._reconnect_delay = 5

    async def get_approval_key(self) -> str:
        """Get WebSocket approval key from KIS REST API."""
        if self._approval_key:
            return self._approval_key

        if not settings.kis_app_key or not settings.kis_app_secret:
            raise ValueError("KIS_APP_KEY and KIS_APP_SECRET required for WebSocket")

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{settings.kis_base_url}/oauth2/Approval",
                json={
                    "grant_type": "client_credentials",
                    "appkey": settings.kis_app_key,
                    "secretkey": settings.kis_app_secret,
                },
            )
            data = resp.json()

        if "approval_key" not in data:
            raise RuntimeError(f"KIS approval key request failed: {data}")

        self._approval_key = data["approval_key"]
        logger.info("KIS WebSocket approval key obtained")
        return self._approval_key

    def _build_subscribe_message(self, stock_code: str, subscribe: bool = True) -> str:
        """Build subscription/unsubscription message."""
        return json.dumps({
            "header": {
                "approval_key": self._approval_key,
                "custtype": "P",
                "tr_type": "1" if subscribe else "2",
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": TR_REALTIME_PRICE,
                    "tr_key": stock_code,
                },
            },
        })

    def _parse_realtime_data(self, raw: str) -> dict | None:
        """Parse KIS real-time price data.

        KIS sends pipe-separated data after the header.
        Format: TR_ID|count|data_fields...
        """
        try:
            # KIS sends JSON for control messages, pipe-separated for data
            if raw.startswith("{"):
                msg = json.loads(raw)
                header = msg.get("header", {})
                tr_id = header.get("tr_id", "")
                if header.get("tr_key"):
                    logger.debug("KIS WS control: tr_id=%s tr_key=%s", tr_id, header.get("tr_key"))
                return None

            # Pipe-separated real-time data
            parts = raw.split("|")
            if len(parts) < 4:
                return None

            tr_id = parts[0]
            data_count = int(parts[1])
            data_str = parts[3]

            if tr_id != TR_REALTIME_PRICE:
                return None

            # H0STCNT0 fields (체결가):
            # 0:종목코드 1:체결시간 2:현재가 3:전일대비부호 4:전일대비
            # 5:전일대비율 6:가중평균가 7:시가 8:고가 9:저가
            # 10:매도호가 11:매수호가 12:체결량 13:누적거래량 14:누적거래대금
            fields = data_str.split("^")
            if len(fields) < 15:
                return None

            return {
                "stock_code": fields[0],
                "time": fields[1],  # HHMMSS
                "price": float(fields[2]),
                "change_sign": fields[3],
                "change": float(fields[4]),
                "change_pct": float(fields[5]),
                "open": float(fields[7]),
                "high": float(fields[8]),
                "low": float(fields[9]),
                "volume": int(fields[13]),
                "value": int(float(fields[14])) if fields[14] else 0,
                "received_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.debug("KIS WS parse error: %s (raw=%s)", e, raw[:100])
            return None

    async def _publish_tick(self, tick: dict):
        """Publish parsed tick to Redis Pub/Sub and update market state cache."""
        channel = f"realtime:{tick['stock_code']}"
        payload = json.dumps(tick, default=str)
        await self.redis.publish(channel, payload)
        await self.redis.publish("realtime:all", payload)

        # Update market state cache (zero-fetch API reads from this)
        from app.services.market_state import MarketStateCache
        cache = MarketStateCache(self.redis)
        await cache.update_tick(tick)

    async def subscribe(self, stock_codes: list[str]):
        """Subscribe to real-time prices for given stock codes."""
        if not self._ws:
            logger.warning("WebSocket not connected, cannot subscribe")
            return

        for code in stock_codes:
            if code not in self._subscribed:
                msg = self._build_subscribe_message(code, subscribe=True)
                await self._ws.send(msg)
                self._subscribed.add(code)
                logger.info("Subscribed to real-time: %s", code)
                await asyncio.sleep(0.1)  # Rate limit subscriptions

    async def unsubscribe(self, stock_codes: list[str]):
        """Unsubscribe from real-time prices."""
        if not self._ws:
            return
        for code in stock_codes:
            if code in self._subscribed:
                msg = self._build_subscribe_message(code, subscribe=False)
                await self._ws.send(msg)
                self._subscribed.discard(code)

    async def run(self, stock_codes: list[str] | None = None):
        """Main loop: connect, subscribe, receive, publish.

        Reconnects automatically on disconnection.
        """
        import websockets

        self._running = True
        while self._running:
            try:
                approval_key = await self.get_approval_key()
                logger.info("Connecting to KIS WebSocket: %s", settings.kis_ws_url)

                async with websockets.connect(
                    settings.kis_ws_url,
                    ping_interval=30,
                    ping_timeout=10,
                ) as ws:
                    self._ws = ws
                    self._reconnect_delay = 5
                    logger.info("KIS WebSocket connected")

                    # Subscribe to stocks
                    codes = stock_codes or []
                    if codes:
                        await self.subscribe(codes)

                    # Receive loop
                    async for message in ws:
                        if not self._running:
                            break
                        tick = self._parse_realtime_data(message)
                        if tick:
                            await self._publish_tick(tick)

            except asyncio.CancelledError:
                self._running = False
                break
            except Exception as e:
                logger.error("KIS WebSocket error: %s, reconnecting in %ds", e, self._reconnect_delay)
                self._ws = None
                self._subscribed.clear()
                self._approval_key = None
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)

        self._ws = None
        logger.info("KIS WebSocket client stopped")

    def stop(self):
        """Signal the run loop to stop."""
        self._running = False
