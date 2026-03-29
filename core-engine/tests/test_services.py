"""Tests for external service clients with mocked HTTP responses.

Covers: KISClient, DARTClient, NaverNewsClient, NotificationService.
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx


# === KISClient ===


class TestKISClient:
    @pytest.fixture
    def kis(self):
        from app.services.kis_api import KISClient
        client = KISClient()
        client._token = "test_token"
        return client

    @pytest.mark.asyncio
    async def test_get_current_price_success(self, kis):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "output": {
                "stck_oprc": "60000",
                "stck_hgpr": "61000",
                "stck_lwpr": "59000",
                "stck_prpr": "60500",
                "acml_vol": "15000000",
                "acml_tr_pbmn": "900000000000",
            }
        }
        mock_resp.raise_for_status = MagicMock()
        kis.client = MagicMock()
        kis.client.request = AsyncMock(return_value=mock_resp)

        result = await kis.get_current_price("005930")
        assert result is not None
        assert result.stock_code == "005930"
        assert result.close == Decimal("60500")
        assert result.volume == 15000000

    @pytest.mark.asyncio
    async def test_get_current_price_empty_output(self, kis):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"output": {}}
        mock_resp.raise_for_status = MagicMock()
        kis.client = MagicMock()
        kis.client.request = AsyncMock(return_value=mock_resp)

        # Empty output returns None, which now raises ExternalAPIError
        # because we changed the behavior. Actually let me check...
        # The code: if not output: return None
        # Then except catches and raises ExternalAPIError
        # Wait - output is {} which is falsy, returns None before except block
        # Actually {} is truthy in Python... let me re-check
        # No, {} is falsy: bool({}) == False. But wait, `not {}` is True? No:
        # In Python, `not {}` is True because empty dict is falsy.
        # So `if not output: return None` will return None for {}.
        # But the outer except catches Exception... no, return None exits normally.
        # Let me re-read the code:
        # output = data.get("output", {})
        # if not output: return None
        # Wait, the output check is inside the try, and None would be returned
        # before the except block. So this returns None without raising.
        # But the caller of get_current_price might handle None.
        # Actually, looking at the code again after our changes:
        # except Exception as e: raise ExternalAPIError(...)
        # But returning None exits the try normally, doesn't go to except.
        # So get_current_price("...") with empty output returns None. Fine.
        result = await kis.get_current_price("005930")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_current_price_network_error(self, kis):
        from app.exceptions import ExternalAPIError
        kis.client = MagicMock()
        kis.client.request = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        with pytest.raises(ExternalAPIError):
            await kis.get_current_price("005930")

    @pytest.mark.asyncio
    async def test_ensure_token_success(self, kis):
        kis._token = None
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "new_token"}
        kis.client = MagicMock()
        kis.client.post = AsyncMock(return_value=mock_resp)

        with patch("app.services.kis_api.settings") as mock_settings:
            mock_settings.kis_app_key = "key"
            mock_settings.kis_app_secret = "secret"
            mock_settings.kis_base_url = "https://test"
            mock_settings.cache_kis_token_ttl = 80000
            token = await kis._ensure_token()

        assert token == "new_token"

    @pytest.mark.asyncio
    async def test_ensure_token_no_keys(self, kis):
        kis._token = None
        with patch("app.services.kis_api.settings") as mock_settings:
            mock_settings.kis_app_key = ""
            mock_settings.kis_app_secret = ""
            with pytest.raises(ValueError):
                await kis._ensure_token()

    @pytest.mark.asyncio
    async def test_auth_headers(self, kis):
        headers = kis._auth_headers("test_token", "FHKST01010100")
        assert headers["authorization"] == "Bearer test_token"
        assert headers["tr_id"] == "FHKST01010100"

    @pytest.mark.asyncio
    async def test_get_daily_chart_success(self, kis):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "output2": [
                {
                    "stck_bsop_date": "20260101",
                    "stck_oprc": "60000", "stck_hgpr": "61000",
                    "stck_lwpr": "59000", "stck_clpr": "60500",
                    "acml_vol": "15000000", "acml_tr_pbmn": "900000000000",
                },
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        kis.client = MagicMock()
        kis.client.request = AsyncMock(return_value=mock_resp)

        records = await kis.get_daily_chart("005930", "20260101", "20260101")
        assert len(records) == 1
        assert records[0].close == Decimal("60500")

    @pytest.mark.asyncio
    async def test_get_daily_chart_empty(self, kis):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"output2": []}
        mock_resp.raise_for_status = MagicMock()
        kis.client = MagicMock()
        kis.client.request = AsyncMock(return_value=mock_resp)

        records = await kis.get_daily_chart("005930", "20260101", "20260101")
        assert records == []


# === DARTClient ===


class TestDARTClient:
    @pytest.fixture
    def dart(self):
        from app.services.dart_api import DARTClient
        return DARTClient()

    @pytest.mark.asyncio
    async def test_get_disclosure_list_no_key(self, dart):
        with patch("app.services.dart_api.settings") as mock_settings:
            mock_settings.dart_api_key = ""
            result = await dart.get_disclosure_list()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_disclosure_list_success(self, dart):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "status": "000",
            "list": [
                {
                    "corp_code": "00126380",
                    "corp_name": "삼성전자",
                    "stock_code": "005930",
                    "report_nm": "주요사항보고서(자기주식취득결정)",
                    "rcept_no": "20260101000001",
                    "flr_nm": "삼성전자",
                    "rcept_dt": "20260101",
                    "rm": "",
                    "dcm_no": "",
                },
            ],
        }
        dart.client = MagicMock()
        dart.client.get = AsyncMock(return_value=mock_resp)

        with patch("app.services.dart_api.settings") as mock_settings:
            mock_settings.dart_api_key = "test_key"
            result = await dart.get_disclosure_list()

        assert len(result) == 1
        assert result[0].stock_code == "005930"
        assert result[0].is_major is True

    @pytest.mark.asyncio
    async def test_get_disclosure_list_bad_status(self, dart):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "013", "message": "조회된 데이터가 없습니다"}
        dart.client = MagicMock()
        dart.client.get = AsyncMock(return_value=mock_resp)

        with patch("app.services.dart_api.settings") as mock_settings:
            mock_settings.dart_api_key = "test_key"
            result = await dart.get_disclosure_list()
        assert result == []


# === NaverNewsClient ===


class TestNaverNewsClient:
    @pytest.fixture
    def naver(self):
        from app.services.naver_news import NaverNewsClient
        return NaverNewsClient()

    @pytest.mark.asyncio
    async def test_fetch_rss_news_success(self, naver):
        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><item>
            <title>테스트 뉴스</title>
            <link>http://test.com/1</link>
            <description>테스트 내용</description>
            <pubDate>Mon, 30 Mar 2026 00:00:00 GMT</pubDate>
        </item></channel></rss>"""

        mock_resp = MagicMock()
        mock_resp.text = rss_xml
        naver.client = MagicMock()
        naver.client.get = AsyncMock(return_value=mock_resp)

        records = await naver.fetch_rss_news()
        assert len(records) == 1
        assert records[0].title == "테스트 뉴스"
        assert records[0].source == "google_news"

    @pytest.mark.asyncio
    async def test_fetch_rss_news_empty(self, naver):
        mock_resp = MagicMock()
        mock_resp.text = "<rss><channel></channel></rss>"
        naver.client = MagicMock()
        naver.client.get = AsyncMock(return_value=mock_resp)

        records = await naver.fetch_rss_news()
        assert records == []

    @pytest.mark.asyncio
    async def test_fetch_stock_news_success(self, naver):
        html = """
        <table class="type5"><tbody>
        <tr>
            <td class="title"><a href="/news?id=1">삼성 호재</a></td>
            <td class="info">매일경제</td>
            <td class="date">2026.03.30</td>
        </tr>
        </tbody></table>
        """
        mock_resp = MagicMock()
        mock_resp.text = html
        naver.client = MagicMock()
        naver.client.get = AsyncMock(return_value=mock_resp)

        records = await naver.fetch_stock_news("005930")
        assert len(records) == 1
        assert "삼성 호재" in records[0].title


# === NotificationService ===


class TestNotificationService:
    @pytest.fixture
    def notifier(self):
        from app.services.notification import NotificationService
        return NotificationService()

    @pytest.mark.asyncio
    async def test_send_telegram_success(self, notifier):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        notifier.client = MagicMock()
        notifier.client.post = AsyncMock(return_value=mock_resp)

        with patch("app.services.notification.settings") as mock_settings:
            mock_settings.telegram_bot_token = "bot123"
            mock_settings.telegram_chat_id = "chat456"
            result = await notifier.send_telegram("test message")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_telegram_not_configured(self, notifier):
        with patch("app.services.notification.settings") as mock_settings:
            mock_settings.telegram_bot_token = ""
            mock_settings.telegram_chat_id = ""
            result = await notifier.send_telegram("test")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_telegram_failure(self, notifier):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        notifier.client = MagicMock()
        notifier.client.post = AsyncMock(return_value=mock_resp)

        with patch("app.services.notification.settings") as mock_settings:
            mock_settings.telegram_bot_token = "bot123"
            mock_settings.telegram_chat_id = "chat456"
            result = await notifier.send_telegram("test")
        assert result is False

    @pytest.mark.asyncio
    async def test_alert_methods(self, notifier):
        notifier.send_telegram = AsyncMock(return_value=True)
        notifier.send_kakao = AsyncMock(return_value=True)

        await notifier.alert_price_surge("삼성전자", "005930", 5.0, 65000, 0)
        await notifier.alert_stop_loss("삼성전자", "005930", -3.5, 10)
        await notifier.alert_take_profit("삼성전자", "005930", 12.0, 10)
        await notifier.alert_system_error("Test error")

        assert notifier.send_telegram.call_count >= 4
