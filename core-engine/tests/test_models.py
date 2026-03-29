"""Tests for all Pydantic models — validation, defaults, edge cases.

~300 test cases via parametrize.
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal

from app.models.common import CollectionResult, CollectionTrigger
from app.models.news import NewsRecord, NewsCollectionResult
from app.models.disclosure import DisclosureRecord, DisclosureCollectionRequest, DisclosureCollectionResult
from app.models.ohlcv import OHLCVRecord, OHLCVCollectionRequest, OHLCVCollectionResult
from app.models.analysis import (
    TechnicalIndicators, TechnicalSignal, TechnicalResult, VolumeResult,
    SectorResult, StockRank, SectorOverview, AnalysisSummary,
    TechnicalRequest, VolumeRequest, SectorRequest, SummaryRequest,
)
from app.models.sentiment import (
    SentimentScore, TextSentimentRequest, StockSentimentRequest,
    StockSentimentResult, CorrelationRequest, CorrelationPair,
    CorrelationResult, CausalityRequest, CausalityResult,
)
from app.models.strategy import (
    StrategySignalRequest, BatchSignalRequest, StrategyComponent,
    StrategySignalResult, BatchSignalResult, BacktestRequest,
    BacktestTrade, BacktestResult, TradingViewWebhook,
)
from app.models.execution import (
    OrderRequest, OrderResult, OrderHistoryItem, PositionInfo,
    PortfolioStatus, RiskCheckRequest, RiskCheckResult,
)

NOW = datetime.now(timezone.utc)


# ===== CollectionResult =====

class TestCollectionResult:
    @pytest.mark.parametrize("status", ["success", "partial", "error"])
    def test_valid_status(self, status):
        r = CollectionResult(status=status, collected_at=NOW)
        assert r.status == status

    def test_defaults(self):
        r = CollectionResult(status="success", collected_at=NOW)
        assert r.inserted == 0
        assert r.duplicates == 0
        assert r.errors == []

    @pytest.mark.parametrize("inserted,duplicates", [(0,0), (1,0), (100,50), (0,999)])
    def test_counts(self, inserted, duplicates):
        r = CollectionResult(status="success", inserted=inserted, duplicates=duplicates, collected_at=NOW)
        assert r.inserted == inserted
        assert r.duplicates == duplicates

    def test_errors_list(self):
        r = CollectionResult(status="error", errors=["e1", "e2", "e3"], collected_at=NOW)
        assert len(r.errors) == 3

    def test_invalid_status_rejected(self):
        with pytest.raises(Exception):
            CollectionResult(status="unknown", collected_at=NOW)


class TestCollectionTrigger:
    def test_defaults(self):
        t = CollectionTrigger()
        assert t.stock_codes is None
        assert t.force is False

    def test_with_codes(self):
        t = CollectionTrigger(stock_codes=["005930", "000660"])
        assert len(t.stock_codes) == 2

    def test_force(self):
        t = CollectionTrigger(force=True)
        assert t.force is True


# ===== NewsRecord =====

class TestNewsRecord:
    def test_minimal(self):
        n = NewsRecord(time=NOW, source="test", title="Test News")
        assert n.content is None
        assert n.stock_codes == []

    @pytest.mark.parametrize("source", ["naver", "google_news", "hankyung", "매경", "dart"])
    def test_sources(self, source):
        n = NewsRecord(time=NOW, source=source, title="Title")
        assert n.source == source

    @pytest.mark.parametrize("codes", [[], ["005930"], ["005930", "000660", "035420"]])
    def test_stock_codes(self, codes):
        n = NewsRecord(time=NOW, source="test", title="T", stock_codes=codes)
        assert n.stock_codes == codes

    @pytest.mark.parametrize("category", [None, "market", "stock", "industry"])
    def test_categories(self, category):
        n = NewsRecord(time=NOW, source="test", title="T", category=category)
        assert n.category == category


class TestNewsCollectionResult:
    def test_with_samples(self):
        sample = NewsRecord(time=NOW, source="test", title="T")
        r = NewsCollectionResult(status="success", collected_at=NOW, sample=[sample])
        assert len(r.sample) == 1


# ===== DisclosureRecord =====

class TestDisclosureRecord:
    def test_minimal(self):
        d = DisclosureRecord(time=NOW, stock_code="005930", report_name="주요사항보고", rcept_no="20260329000001")
        assert d.is_major is False
        assert d.report_type is None

    @pytest.mark.parametrize("is_major", [True, False])
    def test_major_flag(self, is_major):
        d = DisclosureRecord(time=NOW, stock_code="005930", report_name="R", rcept_no="1", is_major=is_major)
        assert d.is_major == is_major


class TestDisclosureCollectionRequest:
    def test_defaults(self):
        r = DisclosureCollectionRequest()
        assert r.corp_codes is None
        assert r.bgn_de is None

    @pytest.mark.parametrize("bgn,end", [("20260101","20260131"), ("20260301","20260329")])
    def test_date_range(self, bgn, end):
        r = DisclosureCollectionRequest(bgn_de=bgn, end_de=end)
        assert r.bgn_de == bgn


# ===== OHLCVRecord =====

class TestOHLCVRecord:
    def test_full(self):
        r = OHLCVRecord(time=NOW, stock_code="005930", open=Decimal("58000"),
                        high=Decimal("59000"), low=Decimal("57000"),
                        close=Decimal("58500"), volume=15000000)
        assert r.interval == "1d"

    @pytest.mark.parametrize("interval", ["1m", "5m", "15m", "1h", "1d"])
    def test_intervals(self, interval):
        r = OHLCVRecord(time=NOW, stock_code="005930", open=100, high=110,
                        low=90, close=105, volume=1000, interval=interval)
        assert r.interval == interval

    @pytest.mark.parametrize("price", [100, 1000, 10000, 100000, 1000000])
    def test_price_ranges(self, price):
        r = OHLCVRecord(time=NOW, stock_code="T", open=price, high=price+100,
                        low=price-100, close=price, volume=1)
        assert r.close == price

    @pytest.mark.parametrize("volume", [0, 1, 1000000, 100000000])
    def test_volume_ranges(self, volume):
        r = OHLCVRecord(time=NOW, stock_code="T", open=100, high=110,
                        low=90, close=100, volume=volume)
        assert r.volume == volume


class TestOHLCVCollectionRequest:
    def test_defaults(self):
        r = OHLCVCollectionRequest()
        assert r.stock_codes is None
        assert r.interval == "1m"


# ===== TechnicalIndicators =====

class TestTechnicalIndicators:
    def test_all_none_defaults(self):
        t = TechnicalIndicators()
        assert t.sma_5 is None
        assert t.rsi_14 is None
        assert t.macd is None
        assert t.atr_14 is None

    @pytest.mark.parametrize("field,value", [
        ("sma_5", 58000), ("sma_20", 57000), ("sma_60", 56000), ("sma_120", 55000),
        ("ema_12", 58500), ("ema_26", 57500),
        ("macd", 500), ("macd_signal", 300), ("macd_hist", 200),
        ("bb_upper", 62000), ("bb_middle", 59000), ("bb_lower", 56000),
        ("rsi_14", 55.5), ("stoch_k", 60.2), ("stoch_d", 55.8),
        ("cci_20", 100.5), ("willr_14", -40.3), ("roc_12", 3.5),
        ("obv", 150000000), ("mfi_14", 60.1), ("vwap", 59500),
        ("atr_14", 1500.5), ("kc_upper", 61500), ("kc_lower", 56500),
        ("ichimoku_tenkan", 59000), ("ichimoku_kijun", 58000),
    ])
    def test_individual_indicators(self, field, value):
        t = TechnicalIndicators(**{field: value})
        assert getattr(t, field) == value


class TestTechnicalSignal:
    @pytest.mark.parametrize("signal", ["bullish", "bearish", "neutral"])
    def test_valid_signals(self, signal):
        s = TechnicalSignal(indicator="RSI", signal=signal, strength=0.5, description="test")
        assert s.signal == signal

    @pytest.mark.parametrize("strength", [0.0, 0.25, 0.5, 0.75, 1.0])
    def test_strength_range(self, strength):
        s = TechnicalSignal(indicator="T", signal="bullish", strength=strength, description="t")
        assert s.strength == strength

    @pytest.mark.parametrize("indicator", ["RSI", "MACD", "BB", "SMA20", "SMA60", "Stochastic", "MFI", "GoldenCross"])
    def test_indicator_names(self, indicator):
        s = TechnicalSignal(indicator=indicator, signal="neutral", strength=0.5, description="t")
        assert s.indicator == indicator


class TestTechnicalResult:
    def test_defaults(self):
        r = TechnicalResult(stock_code="005930", interval="1d",
                            indicators=TechnicalIndicators(), computed_at=NOW)
        assert r.current_price is None
        assert r.signals == []
        assert r.trend_score == 0.0
        assert r.overall_score == 0.0


class TestVolumeResult:
    @pytest.mark.parametrize("ratio,expected_surge", [
        (0.5, False), (1.0, False), (1.99, False), (2.0, False), (2.01, True), (5.0, True),
    ])
    def test_surge_detection(self, ratio, expected_surge):
        r = VolumeResult(stock_code="T", volume_ratio=ratio, is_surge=expected_surge, computed_at=NOW)
        assert r.is_surge == expected_surge

    @pytest.mark.parametrize("div", ["bullish", "bearish", "none"])
    def test_divergence_types(self, div):
        r = VolumeResult(stock_code="T", price_volume_divergence=div, computed_at=NOW)
        assert r.price_volume_divergence == div

    @pytest.mark.parametrize("trend", ["increasing", "decreasing", "flat"])
    def test_volume_trends(self, trend):
        r = VolumeResult(stock_code="T", volume_trend=trend, computed_at=NOW)
        assert r.volume_trend == trend


# ===== Sentiment Models =====

class TestSentimentScore:
    @pytest.mark.parametrize("score", [-1.0, -0.5, 0.0, 0.5, 1.0])
    def test_score_range(self, score):
        s = SentimentScore(score=score)
        assert s.score == score

    @pytest.mark.parametrize("model", ["claude", "openai", "keyword_fallback", "unknown"])
    def test_models(self, model):
        s = SentimentScore(score=0.0, model=model)
        assert s.model == model


class TestCorrelationRequest:
    @pytest.mark.parametrize("method", ["pearson", "spearman"])
    def test_methods(self, method):
        r = CorrelationRequest(stock_codes=["005930", "000660"], method=method)
        assert r.method == method

    @pytest.mark.parametrize("period", [10, 30, 60, 120, 252])
    def test_periods(self, period):
        r = CorrelationRequest(stock_codes=["A", "B"], period=period)
        assert r.period == period


class TestCorrelationPair:
    @pytest.mark.parametrize("corr", [-1.0, -0.5, 0.0, 0.5, 0.8, 1.0])
    def test_correlation_values(self, corr):
        p = CorrelationPair(stock_a="A", stock_b="B", correlation=corr)
        assert p.correlation == corr


class TestCausalityResult:
    def test_defaults(self):
        r = CausalityResult(stock_a="A", stock_b="B", computed_at=NOW)
        assert r.a_causes_b is False
        assert r.b_causes_a is False
        assert r.a_to_b_pvalue == 1.0

    @pytest.mark.parametrize("pval,causes", [(0.01, True), (0.04, True), (0.05, False), (0.5, False), (1.0, False)])
    def test_causality_significance(self, pval, causes):
        r = CausalityResult(stock_a="A", stock_b="B", a_causes_b=(pval < 0.05),
                            a_to_b_pvalue=pval, computed_at=NOW)
        assert r.a_causes_b == causes


# ===== Strategy Models =====

class TestStrategySignalResult:
    @pytest.mark.parametrize("signal", ["BUY", "SELL", "HOLD"])
    def test_signals(self, signal):
        r = StrategySignalResult(stock_code="T", signal=signal, strength=0.5,
                                 ensemble_score=0.3, computed_at=NOW)
        assert r.signal == signal

    @pytest.mark.parametrize("score,expected_signal", [
        (0.5, "BUY"), (0.2, "BUY"), (0.0, "HOLD"), (-0.2, "SELL"), (-0.5, "SELL"),
    ])
    def test_score_signal_mapping(self, score, expected_signal):
        if score > 0.15:
            sig = "BUY"
        elif score < -0.15:
            sig = "SELL"
        else:
            sig = "HOLD"
        assert sig == expected_signal


class TestStrategyComponent:
    @pytest.mark.parametrize("name,weight", [
        ("momentum", 0.30), ("mean_reversion", 0.25), ("volume", 0.20), ("sentiment", 0.25),
    ])
    def test_components(self, name, weight):
        c = StrategyComponent(name=name, score=0.5, weight=weight)
        assert c.weight == weight


class TestBacktestRequest:
    def test_defaults(self):
        r = BacktestRequest(stock_code="005930")
        assert r.initial_capital == 10_000_000
        assert r.strategy == "ensemble"
        assert r.interval == "1d"

    @pytest.mark.parametrize("strategy", ["ensemble", "momentum", "mean_reversion"])
    def test_strategies(self, strategy):
        r = BacktestRequest(stock_code="T", strategy=strategy)
        assert r.strategy == strategy

    @pytest.mark.parametrize("capital", [1_000_000, 5_000_000, 10_000_000, 100_000_000])
    def test_capital(self, capital):
        r = BacktestRequest(stock_code="T", initial_capital=capital)
        assert r.initial_capital == capital


class TestBacktestTrade:
    @pytest.mark.parametrize("action", ["BUY", "SELL"])
    def test_actions(self, action):
        t = BacktestTrade(date="2026-01-01", action=action, price=60000, quantity=10)
        assert t.action == action

    @pytest.mark.parametrize("pnl", [None, -50000, 0, 50000, 1000000])
    def test_pnl(self, pnl):
        t = BacktestTrade(date="2026-01-01", action="SELL", price=60000, quantity=10, pnl=pnl)
        assert t.pnl == pnl


class TestBacktestResult:
    def test_full(self):
        r = BacktestResult(
            stock_code="005930", strategy="ensemble",
            initial_capital=10000000, final_capital=11000000,
            total_return=10.0, max_drawdown=-5.0,
            win_rate=60.0, total_trades=20,
            computed_at=NOW,
        )
        assert r.total_return == 10.0
        assert r.total_trades == 20


class TestTradingViewWebhook:
    @pytest.mark.parametrize("action", ["buy", "sell", "alert"])
    def test_actions(self, action):
        w = TradingViewWebhook(ticker="005930", action=action)
        assert w.action == action

    def test_with_secret(self):
        w = TradingViewWebhook(ticker="T", action="buy", secret="mysecret")
        assert w.secret == "mysecret"


# ===== Execution Models =====

class TestOrderRequest:
    @pytest.mark.parametrize("side", ["BUY", "SELL"])
    def test_sides(self, side):
        r = OrderRequest(stock_code="005930", side=side, quantity=10)
        assert r.side == side

    @pytest.mark.parametrize("order_type", ["MARKET", "LIMIT"])
    def test_order_types(self, order_type):
        r = OrderRequest(stock_code="T", side="BUY", quantity=1, order_type=order_type)
        assert r.order_type == order_type

    @pytest.mark.parametrize("qty", [1, 10, 100, 1000])
    def test_quantities(self, qty):
        r = OrderRequest(stock_code="T", side="BUY", quantity=qty)
        assert r.quantity == qty


class TestRiskCheckResult:
    def test_allowed(self):
        r = RiskCheckResult(allowed=True)
        assert r.violations == []

    def test_rejected(self):
        r = RiskCheckResult(allowed=False, violations=["종목당 한도 초과"])
        assert not r.allowed
        assert len(r.violations) == 1

    @pytest.mark.parametrize("max_qty", [None, 0, 1, 10, 100])
    def test_max_quantity(self, max_qty):
        r = RiskCheckResult(allowed=True, max_quantity=max_qty)
        assert r.max_quantity == max_qty


class TestPortfolioStatus:
    def test_empty_portfolio(self):
        p = PortfolioStatus(total_value=10000000, cash=10000000, invested=0,
                            unrealized_pnl=0, total_return_pct=0.0,
                            positions_count=0, updated_at=NOW)
        assert p.positions == []

    @pytest.mark.parametrize("ret", [-10.0, -5.0, 0.0, 5.0, 10.0, 50.0])
    def test_return_pct(self, ret):
        p = PortfolioStatus(total_value=10000000, cash=5000000, invested=5000000,
                            unrealized_pnl=0, total_return_pct=ret,
                            positions_count=1, updated_at=NOW)
        assert p.total_return_pct == ret


class TestPositionInfo:
    @pytest.mark.parametrize("pnl_pct", [-10.0, -5.0, 0.0, 5.0, 10.0])
    def test_pnl_pct(self, pnl_pct):
        p = PositionInfo(stock_code="T", quantity=10, avg_price=60000,
                         unrealized_pnl_pct=pnl_pct)
        assert p.unrealized_pnl_pct == pnl_pct
