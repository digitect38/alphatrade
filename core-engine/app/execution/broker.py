import logging
from datetime import datetime, timezone

from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)


class BrokerResponse(BaseModel):
    success: bool
    order_no: str | None = None
    filled_qty: int = 0
    filled_price: float | None = None
    message: str = ""


class BrokerClient:
    """한국투자증권 OpenAPI 주문 인터페이스.

    모의투자 모드(기본)에서는 즉시 체결을 시뮬레이션합니다.
    실전 모드에서는 한투 API를 호출합니다.
    """

    def __init__(self, kis_client=None):
        self.is_paper = "vts" in settings.kis_base_url  # 모의투자 URL 포함 여부
        self.kis_client = kis_client

    async def submit_order(
        self,
        stock_code: str,
        side: str,  # BUY or SELL
        quantity: int,
        order_type: str = "MARKET",
        price: float | None = None,
    ) -> BrokerResponse:
        """Submit order to broker."""
        if not settings.kis_app_key:
            # No API key: simulate immediate fill
            return await self._simulate_fill(stock_code, side, quantity, price)

        try:
            if self.is_paper:
                return await self._submit_paper_order(stock_code, side, quantity, order_type, price)
            else:
                return await self._submit_real_order(stock_code, side, quantity, order_type, price)
        except Exception as e:
            logger.error("Broker order failed: %s", e)
            return BrokerResponse(success=False, message=str(e))

    async def _simulate_fill(
        self, stock_code: str, side: str, quantity: int, price: float | None
    ) -> BrokerResponse:
        """Simulate immediate fill (no API key mode)."""
        # Get current price from API
        if not price and self.kis_client:
            record = await self.kis_client.get_current_price(stock_code)
            if record:
                price = float(record.close)

        if not price:
            # Use last DB price
            from app.database import get_db
            pool = get_db()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT close FROM ohlcv WHERE stock_code = $1 ORDER BY time DESC LIMIT 1",
                    stock_code,
                )
            price = float(row["close"]) if row else 0

        now = datetime.now(timezone.utc)
        order_no = f"SIM-{now.strftime('%Y%m%d%H%M%S')}-{stock_code}"

        return BrokerResponse(
            success=True,
            order_no=order_no,
            filled_qty=quantity,
            filled_price=price,
            message="시뮬레이션 체결",
        )

    async def _submit_paper_order(
        self, stock_code: str, side: str, quantity: int, order_type: str, price: float | None
    ) -> BrokerResponse:
        """Submit order to 한투 모의투자 API."""
        tr_id = "VTTC0802U" if side == "BUY" else "VTTC0801U"
        ord_dvsn = "01" if order_type == "LIMIT" else "00"  # 00=지정가, 01=시장가... 한투 모의투자 제한

        data = await self.kis_client._request_with_retry(
            "POST",
            f"{settings.kis_base_url}/uapi/domestic-stock/v1/trading/order-cash",
            tr_id=tr_id,
            json={
                "CANO": settings.kis_cano,
                "ACNT_PRDT_CD": settings.kis_acnt_prdt_cd,
                "PDNO": stock_code,
                "ORD_DVSN": ord_dvsn,
                "ORD_QTY": str(quantity),
                "ORD_UNPR": str(int(price)) if price else "0",
            },
        )

        output = data.get("output", {})
        rt_cd = data.get("rt_cd", "1")

        if rt_cd == "0":
            return BrokerResponse(
                success=True,
                order_no=output.get("ODNO", ""),
                filled_qty=quantity,
                filled_price=price,
                message=data.get("msg1", "주문 접수"),
            )
        else:
            return BrokerResponse(
                success=False,
                message=data.get("msg1", "주문 실패"),
            )

    async def _submit_real_order(
        self, stock_code: str, side: str, quantity: int, order_type: str, price: float | None
    ) -> BrokerResponse:
        """Submit order to 한투 실전 API."""
        tr_id = "TTTC0802U" if side == "BUY" else "TTTC0801U"
        ord_dvsn = "00" if order_type == "LIMIT" else "01"

        data = await self.kis_client._request_with_retry(
            "POST",
            f"{settings.kis_base_url}/uapi/domestic-stock/v1/trading/order-cash",
            tr_id=tr_id,
            json={
                "CANO": settings.kis_cano,
                "ACNT_PRDT_CD": settings.kis_acnt_prdt_cd,
                "PDNO": stock_code,
                "ORD_DVSN": ord_dvsn,
                "ORD_QTY": str(quantity),
                "ORD_UNPR": str(int(price)) if price else "0",
            },
        )

        output = data.get("output", {})
        rt_cd = data.get("rt_cd", "1")

        if rt_cd == "0":
            return BrokerResponse(
                success=True,
                order_no=output.get("ODNO", ""),
                filled_qty=quantity,
                filled_price=price,
                message=data.get("msg1", "주문 접수"),
            )
        else:
            return BrokerResponse(
                success=False,
                message=data.get("msg1", "주문 실패"),
            )
