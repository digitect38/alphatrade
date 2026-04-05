"""Tests for analysis helper functions (pure functions, no DB).

~200 test cases.
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from app.analysis.technical import _safe_float, _generate_signals, _compute_scores, _compute_indicators
from app.models.analysis import TechnicalIndicators, TechnicalSignal


# ===== _safe_float =====

class TestSafeFloat:
    @pytest.mark.parametrize("val,expected", [
        (None, None),
        (float("nan"), None),
        (float("inf"), None),
        (float("-inf"), None),
        (0, 0.0),
        (1, 1.0),
        (-1, -1.0),
        (3.14159, 3.1416),
        (100.0, 100.0),
        (0.00001, 0.0),
        (99999.9999, 99999.9999),
    ])
    def test_values(self, val, expected):
        result = _safe_float(val)
        assert result == expected

    @pytest.mark.parametrize("val", [
        np.float64(3.14), np.float32(2.71), np.int64(42), np.int32(7),
    ])
    def test_numpy_types(self, val):
        result = _safe_float(val)
        assert isinstance(result, float)

    def test_nan_series_value(self):
        s = pd.Series([1.0, np.nan, 3.0])
        assert _safe_float(s.iloc[1]) is None
        assert _safe_float(s.iloc[0]) == 1.0

    @pytest.mark.parametrize("val", ["abc", [], {}, object()])
    def test_invalid_types(self, val):
        assert _safe_float(val) is None


# ===== _generate_signals =====

class TestGenerateSignals:
    def test_empty_indicators(self):
        indicators = TechnicalIndicators()
        signals = _generate_signals(indicators, None)
        assert signals == []

    @pytest.mark.parametrize("rsi,expected_signal", [
        (10, "bullish"), (20, "bullish"), (29, "bullish"),
        (35, "neutral"), (50, "neutral"), (65, "neutral"),
        (71, "bearish"), (80, "bearish"), (90, "bearish"),
    ])
    def test_rsi_signal(self, rsi, expected_signal):
        indicators = TechnicalIndicators(rsi_14=rsi)
        signals = _generate_signals(indicators, 60000)
        rsi_signals = [s for s in signals if s.indicator == "RSI"]
        assert len(rsi_signals) == 1
        assert rsi_signals[0].signal == expected_signal

    @pytest.mark.parametrize("macd_hist,expected_signal", [
        (500, "bullish"), (0.01, "bullish"),
        (-500, "bearish"), (-0.01, "bearish"),
    ])
    def test_macd_signal(self, macd_hist, expected_signal):
        indicators = TechnicalIndicators(macd_hist=macd_hist)
        signals = _generate_signals(indicators, 60000)
        macd_signals = [s for s in signals if s.indicator == "MACD"]
        assert len(macd_signals) == 1
        assert macd_signals[0].signal == expected_signal

    @pytest.mark.parametrize("price,bb_upper,bb_lower,expected_signal", [
        (63000, 62000, 56000, "bearish"),  # above upper
        (55000, 62000, 56000, "bullish"),  # below lower
        (59000, 62000, 56000, None),       # in between → no BB signal
    ])
    def test_bollinger_signal(self, price, bb_upper, bb_lower, expected_signal):
        indicators = TechnicalIndicators(bb_upper=bb_upper, bb_lower=bb_lower)
        signals = _generate_signals(indicators, price)
        bb_signals = [s for s in signals if s.indicator == "BB"]
        if expected_signal:
            assert len(bb_signals) == 1
            assert bb_signals[0].signal == expected_signal
        else:
            assert len(bb_signals) == 0


class TestComputeIndicators:
    def test_bollinger_band_order(self):
        close = pd.Series([100 + i for i in range(40)], dtype=float)
        df = pd.DataFrame({
            "time": pd.date_range("2026-01-01", periods=40, freq="D"),
            "open": close,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": pd.Series([1000] * 40, dtype=int),
        })

        indicators = _compute_indicators(df)

        assert indicators.bb_upper is not None
        assert indicators.bb_middle is not None
        assert indicators.bb_lower is not None
        assert indicators.bb_upper > indicators.bb_middle > indicators.bb_lower

    @pytest.mark.parametrize("price,sma20,expected", [
        (60000, 55000, "bullish"),
        (50000, 55000, "bearish"),
    ])
    def test_sma20_signal(self, price, sma20, expected):
        indicators = TechnicalIndicators(sma_20=sma20)
        signals = _generate_signals(indicators, price)
        sma_signals = [s for s in signals if s.indicator == "SMA20"]
        assert len(sma_signals) == 1
        assert sma_signals[0].signal == expected

    @pytest.mark.parametrize("sma20,sma60,expected_indicator", [
        (58000, 55000, "GoldenCross"),
        (55000, 58000, "DeathCross"),
    ])
    def test_cross_signals(self, sma20, sma60, expected_indicator):
        indicators = TechnicalIndicators(sma_20=sma20, sma_60=sma60)
        signals = _generate_signals(indicators, 60000)
        cross = [s for s in signals if s.indicator in ("GoldenCross", "DeathCross")]
        assert len(cross) == 1
        assert cross[0].indicator == expected_indicator

    @pytest.mark.parametrize("stoch_k,stoch_d,expected", [
        (10, 12, "bullish"),
        (85, 82, "bearish"),
        (50, 50, None),  # no stochastic signal in neutral zone
    ])
    def test_stochastic_signal(self, stoch_k, stoch_d, expected):
        indicators = TechnicalIndicators(stoch_k=stoch_k, stoch_d=stoch_d)
        signals = _generate_signals(indicators, 60000)
        stoch = [s for s in signals if s.indicator == "Stochastic"]
        if expected:
            assert len(stoch) == 1
            assert stoch[0].signal == expected
        else:
            assert len(stoch) == 0

    @pytest.mark.parametrize("mfi,expected", [
        (10, "bullish"), (18, "bullish"),
        (50, None),
        (82, "bearish"), (90, "bearish"),
    ])
    def test_mfi_signal(self, mfi, expected):
        indicators = TechnicalIndicators(mfi_14=mfi)
        signals = _generate_signals(indicators, 60000)
        mfi_signals = [s for s in signals if s.indicator == "MFI"]
        if expected:
            assert len(mfi_signals) == 1
            assert mfi_signals[0].signal == expected
        else:
            assert len(mfi_signals) == 0


# ===== _compute_scores =====

class TestComputeScores:
    def test_empty_signals(self):
        trend, momentum, overall = _compute_scores([])
        assert trend == 0.0
        assert momentum == 0.0
        assert overall == 0.0

    def test_all_bullish(self):
        signals = [
            TechnicalSignal(indicator="SMA20", signal="bullish", strength=0.5, description="t"),
            TechnicalSignal(indicator="SMA60", signal="bullish", strength=0.6, description="t"),
            TechnicalSignal(indicator="RSI", signal="bullish", strength=0.8, description="t"),
            TechnicalSignal(indicator="MACD", signal="bullish", strength=0.7, description="t"),
        ]
        trend, momentum, overall = _compute_scores(signals)
        assert trend > 0
        assert momentum > 0
        assert overall > 0

    def test_all_bearish(self):
        signals = [
            TechnicalSignal(indicator="SMA20", signal="bearish", strength=0.5, description="t"),
            TechnicalSignal(indicator="RSI", signal="bearish", strength=0.8, description="t"),
            TechnicalSignal(indicator="MACD", signal="bearish", strength=0.7, description="t"),
        ]
        trend, momentum, overall = _compute_scores(signals)
        assert trend < 0
        assert momentum < 0
        assert overall < 0

    def test_mixed_signals(self):
        signals = [
            TechnicalSignal(indicator="SMA20", signal="bullish", strength=0.5, description="t"),
            TechnicalSignal(indicator="RSI", signal="bearish", strength=0.8, description="t"),
        ]
        trend, momentum, overall = _compute_scores(signals)
        # Trend is bullish, momentum is bearish
        assert trend > 0
        assert momentum < 0

    def test_neutral_signals(self):
        signals = [
            TechnicalSignal(indicator="RSI", signal="neutral", strength=0.3, description="t"),
            TechnicalSignal(indicator="MACD", signal="neutral", strength=0.5, description="t"),
        ]
        _, momentum, _ = _compute_scores(signals)
        assert momentum == 0.0

    @pytest.mark.parametrize("n_bullish,n_bearish", [
        (1, 0), (0, 1), (2, 1), (1, 2), (3, 3), (5, 0), (0, 5),
    ])
    def test_signal_ratio(self, n_bullish, n_bearish):
        signals = []
        for i in range(n_bullish):
            signals.append(TechnicalSignal(indicator="RSI", signal="bullish", strength=0.5, description="t"))
        for i in range(n_bearish):
            signals.append(TechnicalSignal(indicator="MACD", signal="bearish", strength=0.5, description="t"))
        _, momentum, _ = _compute_scores(signals)
        if n_bullish > n_bearish:
            assert momentum > 0
        elif n_bearish > n_bullish:
            assert momentum < 0


# ===== Correlation Helper =====

class TestGrangerHelper:
    """Test the Granger causality F-test helper (pure function)."""

    def test_import(self):
        from app.analysis.correlation import _granger_test
        assert callable(_granger_test)

    @pytest.mark.parametrize("n", [5, 10, 20, 50])
    def test_random_no_causality(self, n):
        from app.analysis.correlation import _granger_test
        np.random.seed(42)
        x = np.random.randn(n)
        y = np.random.randn(n)
        pval, lag = _granger_test(x, y, 3)
        # Random series should generally not show causality
        assert 0 <= pval <= 1
        assert 1 <= lag <= 3

    def test_causal_series(self):
        from app.analysis.correlation import _granger_test
        np.random.seed(42)
        n = 100
        x = np.random.randn(n)
        y = np.zeros(n)
        for i in range(1, n):
            y[i] = 0.8 * x[i - 1] + 0.2 * np.random.randn()
        pval, lag = _granger_test(x, y, 5)
        # x should Granger-cause y
        assert pval < 0.05
        assert lag == 1

    def test_short_series(self):
        from app.analysis.correlation import _granger_test
        x = np.array([1.0, 2.0, 3.0])
        y = np.array([1.5, 2.5, 3.5])
        pval, lag = _granger_test(x, y, 2)
        assert 0 <= pval <= 1


# ===== Keyword Sentiment =====

class TestKeywordSentiment:
    def test_import(self):
        from app.analysis.sentiment import _keyword_sentiment
        assert callable(_keyword_sentiment)

    @pytest.mark.parametrize("text,expected_positive", [
        ("삼성전자 영업이익 급등 호재", True),
        ("주가 급락 적자 전환 악재", False),
        ("오늘 날씨가 좋다", None),  # neutral
        ("", None),
    ])
    def test_keyword_direction(self, text, expected_positive):
        from app.analysis.sentiment import _keyword_sentiment
        result = _keyword_sentiment(text)
        if expected_positive is True:
            assert result.score > 0
        elif expected_positive is False:
            assert result.score < 0
        else:
            assert result.score == 0.0

    @pytest.mark.parametrize("text", [
        "상승 급등 호재 성장 개선",
        "하락 급락 적자 손실 부도",
        "상승 하락 호재 악재",
        "일반적인 텍스트",
    ])
    def test_score_bounds(self, text):
        from app.analysis.sentiment import _keyword_sentiment
        result = _keyword_sentiment(text)
        assert -1.0 <= result.score <= 1.0
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.parametrize("word", [
        "상승", "급등", "호재", "흑자", "성장", "개선", "돌파", "최고",
        "수주", "계약", "신고가", "배당", "증가", "매출", "영업이익",
    ])
    def test_positive_keywords(self, word):
        from app.analysis.sentiment import _keyword_sentiment
        result = _keyword_sentiment(f"삼성전자 {word} 관련 뉴스")
        assert result.score > 0

    @pytest.mark.parametrize("word", [
        "하락", "급락", "악재", "적자", "감소", "하향", "폐지", "부도",
        "손실", "매도", "공매도", "최저", "감자", "워크아웃", "회생",
    ])
    def test_negative_keywords(self, word):
        from app.analysis.sentiment import _keyword_sentiment
        result = _keyword_sentiment(f"삼성전자 {word} 관련 뉴스")
        assert result.score < 0
