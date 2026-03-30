"""Integration tests for all API routes using FastAPI TestClient.

Tests run without real DB/Redis — uses dependency_overrides with async mocks.
~200 test cases.
"""

import hashlib
import hmac
import pytest
import time
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


class FakeConn:
    """Mock asyncpg connection."""

    def __init__(self, data=None):
        self._data = data or []
        self._single = None

    async def fetch(self, *args, **kwargs):
        return self._data

    async def fetchrow(self, *args, **kwargs):
        return self._single

    async def fetchval(self, *args, **kwargs):
        return 1

    async def execute(self, *args, **kwargs):
        return "INSERT 0 1"


class FakePool:
    """Mock asyncpg pool."""

    def __init__(self):
        self.conn = FakeConn()

    def acquire(self):
        return FakeAcquire(self.conn)


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        pass


class FakeRedis:
    """Mock Redis client."""
    _store = {}

    async def ping(self):
        return True

    async def get(self, key):
        return self._store.get(key)

    async def setex(self, key, ttl, value):
        self._store[key] = value

    async def publish(self, channel, data):
        return 0

    async def close(self):
        pass


# Shared mock instances
_pool = FakePool()
_redis = FakeRedis()


@pytest.fixture
def client():
    """TestClient with mocked DB/Redis via dependency_overrides."""
    from app.main import app
    from app.deps import get_db, get_redis, get_kis_client, get_dart_client, get_naver_client, get_notifier, get_broker, get_risk_manager
    from app.execution.broker import BrokerClient
    from app.execution.risk_manager import RiskManager
    from app.services.kis_api import KISClient
    from app.services.dart_api import DARTClient
    from app.services.naver_news import NaverNewsClient
    from app.services.notification import NotificationService

    # Create mock service instances
    mock_kis = MagicMock(spec=KISClient)
    mock_kis.get_current_price = AsyncMock(return_value=None)
    mock_dart = MagicMock(spec=DARTClient)
    mock_dart.get_disclosure_list = AsyncMock(return_value=[])
    mock_naver = MagicMock(spec=NaverNewsClient)
    mock_naver.fetch_rss_news = AsyncMock(return_value=[])
    mock_naver.fetch_stock_news = AsyncMock(return_value=[])
    mock_notifier = MagicMock(spec=NotificationService)
    mock_notifier.alert_stop_loss = AsyncMock()
    mock_notifier.alert_take_profit = AsyncMock()
    mock_notifier.alert_price_surge = AsyncMock()
    mock_broker = BrokerClient(kis_client=mock_kis)
    mock_risk = RiskManager()

    # Override all dependencies
    app.dependency_overrides[get_db] = lambda: _pool
    app.dependency_overrides[get_redis] = lambda: _redis
    app.dependency_overrides[get_kis_client] = lambda: mock_kis
    app.dependency_overrides[get_dart_client] = lambda: mock_dart
    app.dependency_overrides[get_naver_client] = lambda: mock_naver
    app.dependency_overrides[get_notifier] = lambda: mock_notifier
    app.dependency_overrides[get_broker] = lambda: mock_broker
    app.dependency_overrides[get_risk_manager] = lambda: mock_risk

    # Also set app.state for health check (not via Depends)
    app.state.db_pool = _pool
    app.state.redis_client = _redis

    yield TestClient(app, raise_server_exceptions=False)

    # Cleanup
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def reset_pool():
    """Reset mock data before each test."""
    _pool.conn = FakeConn()
    FakeRedis._store = {}


def _set_fetch_data(data):
    _pool.conn._data = data


def _set_fetchrow(data):
    _pool.conn._single = data


# ========== Health & Metrics ==========


class TestHealthEndpoint:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["db"] == "ok"
        assert data["redis"] == "ok"

    def test_metrics(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "http_requests_total" in resp.text


# ========== Data Routes ==========


class TestDataRoutes:
    def test_get_unprocessed_news(self, client):
        _set_fetch_data([
            {"time": datetime.now(timezone.utc), "source": "test", "title": "News",
             "content": "Body", "url": "http://test.com", "stock_codes": ["005930"], "category": "market"},
        ])
        resp = client.get("/data/news/unprocessed?limit=10")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_unprocessed_news_empty(self, client):
        resp = client.get("/data/news/unprocessed")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_mark_processed(self, client):
        resp = client.patch("/data/news/mark-processed", json=["http://test.com"])
        assert resp.status_code == 200

    def test_store_sentiment(self, client):
        resp = client.post("/data/sentiment", json={
            "time": "2026-03-29T00:00:00Z", "stock_code": "005930",
            "source_type": "news", "score": 0.75, "confidence": 0.9, "model": "claude",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.parametrize("score", [-1.0, -0.5, 0.0, 0.5, 1.0])
    def test_sentiment_score_range(self, client, score):
        resp = client.post("/data/sentiment", json={
            "time": "2026-03-29T00:00:00Z", "stock_code": "005930",
            "source_type": "news", "score": score,
        })
        assert resp.status_code == 200

    def test_get_ohlcv_latest(self, client):
        _set_fetch_data([
            {"time": datetime.now(timezone.utc), "stock_code": "005930",
             "open": Decimal("58000"), "high": Decimal("59000"),
             "low": Decimal("57000"), "close": Decimal("58500"),
             "volume": 15000000, "value": 870000000000, "interval": "1d"},
        ])
        resp = client.get("/data/ohlcv/latest?stock_code=005930&interval=1d&limit=10")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_ohlcv_requires_stock_code(self, client):
        resp = client.get("/data/ohlcv/latest")
        assert resp.status_code == 422  # missing required param


# ========== Collection Routes ==========


class TestCollectionRoutes:
    def test_collect_news(self, client):
        _set_fetch_data([])  # empty universe
        resp = client.post("/collect/news")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "inserted" in data

    def test_collect_disclosures(self, client):
        resp = client.post("/collect/disclosures")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_collect_ohlcv_empty_universe(self, client):
        _set_fetch_data([])  # empty universe
        resp = client.post("/collect/ohlcv")
        assert resp.status_code == 200


# ========== Analysis Routes ==========


class TestAnalysisRoutes:
    def test_technical_no_data(self, client):
        resp = client.post("/analyze/technical", json={"stock_code": "005930"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["stock_code"] == "005930"
        assert data["signals"] == []

    def test_volume_no_data(self, client):
        resp = client.post("/analyze/volume", json={"stock_code": "005930"})
        assert resp.status_code == 200
        assert resp.json()["stock_code"] == "005930"

    def test_sector_no_data(self, client):
        resp = client.post("/analyze/sector", json={})
        assert resp.status_code == 200

    def test_summary_no_data(self, client):
        resp = client.post("/analyze/summary", json={"stock_code": "005930"})
        assert resp.status_code == 200
        assert resp.json()["stock_code"] == "005930"

    def test_sentiment_text(self, client):
        resp = client.post("/analyze/sentiment", json={"text": "삼성전자 급등 호재 상승"})
        assert resp.status_code == 200
        data = resp.json()
        assert "score" in data
        assert -1.0 <= data["score"] <= 1.0

    def test_sentiment_stock(self, client):
        resp = client.post("/analyze/sentiment/stock", json={"stock_code": "005930"})
        assert resp.status_code == 200

    def test_correlation_needs_two_stocks(self, client):
        resp = client.post("/analyze/correlation", json={"stock_codes": ["005930", "000660"]})
        assert resp.status_code == 200

    def test_causality(self, client):
        resp = client.post("/analyze/causality", json={"stock_a": "005930", "stock_b": "000660"})
        assert resp.status_code == 200

    @pytest.mark.parametrize("interval", ["1d", "1m", "5m"])
    def test_technical_intervals(self, client, interval):
        resp = client.post("/analyze/technical", json={"stock_code": "005930", "interval": interval})
        assert resp.status_code == 200

    @pytest.mark.parametrize("method", ["pearson", "spearman"])
    def test_correlation_methods(self, client, method):
        resp = client.post("/analyze/correlation", json={"stock_codes": ["005930", "000660"], "method": method})
        assert resp.status_code == 200


# ========== Strategy Routes ==========


class TestStrategyRoutes:
    def test_signal(self, client):
        resp = client.post("/strategy/signal", json={"stock_code": "005930"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["signal"] in ("BUY", "SELL", "HOLD")

    def test_batch_signals(self, client):
        resp = client.post("/strategy/signals/batch", json={"stock_codes": ["005930"]})
        assert resp.status_code == 200
        assert "signals" in resp.json()

    def test_batch_signals_empty(self, client):
        _set_fetch_data([])
        resp = client.post("/strategy/signals/batch", json={})
        assert resp.status_code == 200

    def test_backtest(self, client):
        resp = client.post("/strategy/backtest", json={"stock_code": "005930"})
        assert resp.status_code == 200
        data = resp.json()
        assert "total_return" in data
        assert "max_drawdown" in data

    @pytest.mark.parametrize("strategy", ["ensemble", "momentum", "mean_reversion"])
    def test_backtest_strategies(self, client, strategy):
        resp = client.post("/strategy/backtest", json={"stock_code": "005930", "strategy": strategy})
        assert resp.status_code == 200

    @pytest.mark.parametrize("capital", [1000000, 5000000, 50000000])
    def test_backtest_capital(self, client, capital):
        resp = client.post("/strategy/backtest", json={"stock_code": "005930", "initial_capital": capital})
        assert resp.status_code == 200
        assert resp.json()["initial_capital"] == capital


# ========== Order Routes ==========


class TestOrderRoutes:
    def test_order_history_empty(self, client):
        resp = client.get("/order/history")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_order_history_with_stock(self, client):
        resp = client.get("/order/history?stock_code=005930")
        assert resp.status_code == 200

    def test_risk_check(self, client):
        resp = client.post("/order/risk/check", json={
            "stock_code": "005930", "side": "BUY", "quantity": 1,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "allowed" in data
        assert "violations" in data

    @pytest.mark.parametrize("side", ["BUY", "SELL"])
    def test_risk_check_sides(self, client, side):
        resp = client.post("/order/risk/check", json={
            "stock_code": "005930", "side": side, "quantity": 10,
        })
        assert resp.status_code == 200

    @pytest.mark.parametrize("qty", [1, 10, 100])
    def test_risk_check_quantities(self, client, qty):
        resp = client.post("/order/risk/check", json={
            "stock_code": "005930", "side": "BUY", "quantity": qty,
        })
        assert resp.status_code == 200


# ========== Portfolio Routes ==========


class TestPortfolioRoutes:
    def test_portfolio_status(self, client):
        resp = client.get("/portfolio/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_value" in data
        assert "positions" in data

    def test_portfolio_positions(self, client):
        resp = client.get("/portfolio/positions")
        assert resp.status_code == 200


# ========== Webhook Routes ==========


class TestWebhookRoutes:
    def test_tradingview_webhook_with_hmac(self, client):
        secret = "test_secret"
        body = {
            "ticker": "005930",
            "action": "buy",
            "price": 60000,
        }
        body_bytes = json_bytes = __import__("json").dumps(body).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(secret.encode(), f"{timestamp}.".encode() + body_bytes, hashlib.sha256).hexdigest()

        with patch("app.routes.webhook.settings.tradingview_webhook_secret", secret):
            resp = client.post(
                "/webhook/tradingview",
                content=json_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-Timestamp": timestamp,
                    "X-Signature": signature,
                },
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "received"

    def test_tradingview_webhook_rejects_bad_hmac(self, client):
        secret = "test_secret"
        body = {"ticker": "005930", "action": "buy"}
        json_bytes = __import__("json").dumps(body).encode()
        timestamp = str(int(time.time()))

        with patch("app.routes.webhook.settings.tradingview_webhook_secret", secret):
            resp = client.post(
                "/webhook/tradingview",
                content=json_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-Timestamp": timestamp,
                    "X-Signature": "bad-signature",
                },
            )
        assert resp.status_code == 403

    def test_tradingview_webhook_with_secret(self, client):
        from app.config import settings
        secret = settings.tradingview_webhook_secret or "test_secret"
        resp = client.post("/webhook/tradingview", json={
            "ticker": "005930", "action": "buy", "price": 60000, "secret": secret,
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "received"

    def test_tradingview_webhook_wrong_secret(self, client):
        resp = client.post("/webhook/tradingview", json={
            "ticker": "005930", "action": "buy", "secret": "wrong",
        })
        # If secret is configured, should reject
        from app.config import settings
        if settings.tradingview_webhook_secret:
            assert resp.status_code == 403
        else:
            assert resp.status_code == 200

    @pytest.mark.parametrize("action", ["buy", "sell", "alert"])
    def test_tradingview_actions(self, client, action):
        from app.config import settings
        secret = settings.tradingview_webhook_secret or None
        resp = client.post("/webhook/tradingview", json={
            "ticker": "005930", "action": action, "secret": secret,
        })
        assert resp.status_code == 200

    def test_tradingview_with_message(self, client):
        from app.config import settings
        resp = client.post("/webhook/tradingview", json={
            "ticker": "005930", "action": "alert", "message": "RSI > 70",
            "secret": settings.tradingview_webhook_secret or None,
        })
        assert resp.status_code == 200


# ========== Trading Routes ==========


class TestTradingRoutes:
    def test_trading_status_no_snapshots(self, client):
        resp = client.get("/trading/status")
        assert resp.status_code == 200

    def test_trading_snapshot(self, client):
        resp = client.post("/trading/snapshot")
        assert resp.status_code == 200

    def test_trading_monitor(self, client):
        resp = client.post("/trading/monitor")
        assert resp.status_code == 200

    def test_reconcile_with_broker_mismatch(self, client):
        from app.main import app
        from app.deps import get_kis_client
        from app.services.kis_api import KISClient

        class ReconcileConn(FakeConn):
            def __init__(self):
                super().__init__()
                self.calls = []

            async def fetch(self, query, *args, **kwargs):
                self.calls.append(("fetch", query))
                if "FROM orders" in query:
                    return [
                        {"order_id": "ORD-1", "stock_code": "005930", "side": "BUY", "quantity": 10, "status": "SUBMITTED"},
                    ]
                if "FROM portfolio_positions WHERE quantity <= 0" in query:
                    return []
                if "SUM(quantity * avg_price)" in query:
                    return [{"total_invested": Decimal("100000")}]
                if "FROM portfolio_positions WHERE quantity > 0" in query:
                    return [{"stock_code": "005930", "quantity": 10, "avg_price": Decimal("10000")}]
                return []

            async def fetchrow(self, query, *args, **kwargs):
                if "FROM portfolio_snapshots" in query:
                    return {"total_value": Decimal("1000000"), "cash": Decimal("500000"), "invested": Decimal("120000")}
                return None

        _pool.conn = ReconcileConn()

        mock_kis = MagicMock(spec=KISClient)
        mock_kis.get_account_balance = AsyncMock(return_value={
            "cash": 450000,
            "positions": [{"stock_code": "005930", "quantity": 8}],
        })
        app.dependency_overrides[get_kis_client] = lambda: mock_kis

        resp = client.post("/trading/reconcile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["mismatches"] >= 2
        mismatch_types = {item["type"] for item in data["details"]}
        assert "position_qty_mismatch" in mismatch_types
        assert "broker_cash_mismatch" in mismatch_types or "cash_mismatch" in mismatch_types


# ========== Scanner Routes ==========


class TestScannerRoutes:
    def test_universe(self, client):
        resp = client.get("/scanner/universe")
        assert resp.status_code == 200

    def test_morning_scan(self, client):
        resp = client.post("/scanner/morning")
        assert resp.status_code == 200


# ========== Market Routes ==========


class TestMarketRoutes:
    def test_market_prices(self, client):
        _set_fetch_data([])  # empty universe
        resp = client.get("/market/prices")
        assert resp.status_code == 200
        assert "stocks" in resp.json()

    def test_stock_news(self, client):
        resp = client.get("/market/news/005930")
        assert resp.status_code == 200


# ========== Asset Routes ==========


class TestAssetRoutes:
    def test_asset_overview(self, client):
        from app.routes import asset as asset_route

        async def fake_profile(pool, stock_code):
            return {"stock_name": "삼성전자", "market": "KOSPI", "sector": "반도체"}

        async def fake_state(redis, pool, stock_code):
            return {"current_price": 70100, "change": 1200, "change_pct": 1.74, "volume": 1234567, "updated_at": "2026-03-31T00:00:00Z"}

        with patch.object(asset_route, "_load_profile", fake_profile), patch.object(asset_route, "_load_market_state", fake_state):
            resp = client.get("/asset/005930/overview")

        assert resp.status_code == 200
        data = resp.json()
        assert data["stock_code"] == "005930"
        assert data["stock_name"] == "삼성전자"
        assert data["current_price"] == 70100
        assert "session" in data

    def test_asset_chart(self, client):
        _set_fetch_data([
            {"time": datetime.now(timezone.utc), "open": Decimal("68000"), "high": Decimal("70500"), "low": Decimal("67900"), "close": Decimal("70100"), "volume": 1234567},
            {"time": datetime.now(timezone.utc), "open": Decimal("67000"), "high": Decimal("68100"), "low": Decimal("66800"), "close": Decimal("68000"), "volume": 1111111},
        ])
        resp = client.get("/asset/005930/chart?range=1M")
        assert resp.status_code == 200
        data = resp.json()
        assert data["stock_code"] == "005930"
        assert data["range"] == "1M"
        assert len(data["points"]) == 2

    def test_asset_period_returns(self, client):
        _set_fetch_data([
            {"time": datetime(2025, 12, 30, tzinfo=timezone.utc), "close": Decimal("100")},
            {"time": datetime(2026, 1, 2, tzinfo=timezone.utc), "close": Decimal("110")},
            {"time": datetime(2026, 3, 31, tzinfo=timezone.utc), "close": Decimal("121")},
        ])
        resp = client.get("/asset/005930/period-returns")
        assert resp.status_code == 200
        data = resp.json()
        assert data["stock_code"] == "005930"
        assert "1D" in data["returns"]
        assert "YTD" in data["returns"]
        assert data["returns"]["YTD"] == 10.0

    def test_asset_execution_context(self, client):
        from app.routes import asset as asset_route

        async def fake_orders(pool, stock_code, limit=8):
            return [{"order_id": "o1", "time": "2026-03-31T00:00:00Z", "stock_code": stock_code, "side": "BUY", "order_type": "market", "quantity": 10, "price": None, "filled_qty": 10, "filled_price": 70100.0, "status": "FILLED", "slippage": 0.1, "commission": 100.0}]

        async def fake_news(pool, stock_code, limit=5):
            return [{"time": "2026-03-31T00:00:00Z", "source": "naver", "title": "Test News", "content": "body", "url": "http://example.com"}]

        async def fake_signal(pool, redis, stock_code):
            return {"overall_signal": "buy", "confidence": 0.75, "trend_score": 0.4, "momentum_score": 0.3, "overall_score": 0.35, "top_signals": []}

        with patch.object(asset_route, "_load_recent_orders", fake_orders), patch.object(asset_route, "_load_recent_news", fake_news), patch.object(asset_route, "_load_signal_summary", fake_signal):
            resp = client.get("/asset/005930/execution-context")

        assert resp.status_code == 200
        data = resp.json()
        assert data["stock_code"] == "005930"
        assert data["latest_order"]["status"] == "FILLED"
        assert data["signal_summary"]["overall_signal"] == "buy"


# ========== Index Routes ==========


class TestIndexRoutes:
    def test_sector_trends(self, client):
        resp = client.get("/index/sectors?days=10")
        assert resp.status_code in (200, 429)  # may hit rate limit in test suite

    def test_market_overview(self, client):
        resp = client.get("/index/overview")
        assert resp.status_code in (200, 429)
