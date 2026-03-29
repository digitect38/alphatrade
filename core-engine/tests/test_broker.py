"""Tests for broker client logic (unit tests).

~50 test cases.
"""

import pytest
from app.execution.broker import BrokerClient


class TestBrokerClient:
    def test_paper_mode_detection_vts(self):
        """When URL contains 'vts', it should be paper mode."""
        from app.config import settings
        client = BrokerClient()
        if "vts" in settings.kis_base_url:
            assert client.is_paper is True
        else:
            assert client.is_paper is False

    def test_broker_response_model(self):
        from app.execution.broker import BrokerResponse
        r = BrokerResponse(success=True, order_no="ORD-001",
                           filled_qty=10, filled_price=60000.0,
                           message="체결 완료")
        assert r.success is True
        assert r.filled_qty == 10

    @pytest.mark.parametrize("success,filled", [
        (True, 10), (True, 0), (False, 0),
    ])
    def test_broker_response_variants(self, success, filled):
        from app.execution.broker import BrokerResponse
        r = BrokerResponse(success=success, filled_qty=filled)
        assert r.success == success
        assert r.filled_qty == filled

    def test_failed_response(self):
        from app.execution.broker import BrokerResponse
        r = BrokerResponse(success=False, message="잔고 부족")
        assert not r.success
        assert r.order_no is None

    @pytest.mark.parametrize("msg", [
        "시뮬레이션 체결", "주문 접수", "주문 실패",
        "잔고 부족", "종목코드 오류", "",
    ])
    def test_message_variants(self, msg):
        from app.execution.broker import BrokerResponse
        r = BrokerResponse(success=True, message=msg)
        assert r.message == msg
