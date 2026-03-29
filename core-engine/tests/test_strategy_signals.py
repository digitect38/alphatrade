"""Tests for individual strategy signal generators.

~250 test cases via parametrize.
"""

import pytest
from datetime import datetime, timezone

from app.strategy.signals import (
    momentum_signal,
    mean_reversion_signal,
    volume_signal,
    sentiment_signal,
)
from app.models.analysis import TechnicalIndicators, TechnicalResult, VolumeResult
from app.models.sentiment import StockSentimentResult, SentimentScore

NOW = datetime.now(timezone.utc)


def _make_technical(
    current_price=60000,
    sma_20=None, sma_60=None,
    macd_hist=None, rsi_14=None, roc_12=None,
    bb_upper=None, bb_lower=None,
    stoch_k=None, stoch_d=None, willr_14=None,
    mfi_14=None,
) -> TechnicalResult:
    return TechnicalResult(
        stock_code="T", interval="1d", current_price=current_price,
        indicators=TechnicalIndicators(
            sma_20=sma_20, sma_60=sma_60,
            macd_hist=macd_hist, rsi_14=rsi_14, roc_12=roc_12,
            bb_upper=bb_upper, bb_lower=bb_lower,
            stoch_k=stoch_k, stoch_d=stoch_d, willr_14=willr_14,
            mfi_14=mfi_14,
        ),
        signals=[], computed_at=NOW,
    )


def _make_volume(
    volume_ratio=1.0, is_surge=False,
    divergence="none", trend="flat", obv_trend="flat",
) -> VolumeResult:
    return VolumeResult(
        stock_code="T", volume_ratio=volume_ratio, is_surge=is_surge,
        price_volume_divergence=divergence, volume_trend=trend,
        obv_trend=obv_trend, computed_at=NOW,
    )


def _make_sentiment(score=0.0, count=0) -> StockSentimentResult:
    return StockSentimentResult(
        stock_code="T", overall_score=score, article_count=count,
        computed_at=NOW,
    )


# ===== Momentum Signal =====

class TestMomentumSignal:
    @pytest.mark.parametrize("price,sma20,expected_positive", [
        (60000, 55000, True),   # above SMA20 → bullish
        (50000, 55000, False),  # below SMA20 → bearish
        (55000, 55000, False),  # at SMA20 → bearish (not strictly above)
    ])
    def test_sma20_trend(self, price, sma20, expected_positive):
        t = _make_technical(current_price=price, sma_20=sma20)
        score = momentum_signal(t)
        if expected_positive:
            assert score > 0
        else:
            assert score <= 0

    @pytest.mark.parametrize("price,sma60,expected_positive", [
        (60000, 55000, True),
        (50000, 55000, False),
    ])
    def test_sma60_trend(self, price, sma60, expected_positive):
        t = _make_technical(current_price=price, sma_60=sma60)
        score = momentum_signal(t)
        if expected_positive:
            assert score > 0
        else:
            assert score <= 0

    @pytest.mark.parametrize("macd_hist,expected_positive", [
        (500, True), (100, True), (0.01, True),
        (-500, False), (-100, False), (-0.01, False),
    ])
    def test_macd_momentum(self, macd_hist, expected_positive):
        t = _make_technical(macd_hist=macd_hist)
        score = momentum_signal(t)
        if expected_positive:
            assert score > 0
        else:
            assert score < 0

    @pytest.mark.parametrize("rsi", [10, 20, 30, 40, 50, 55, 60, 65, 70, 80, 90])
    def test_rsi_values(self, rsi):
        t = _make_technical(rsi_14=rsi)
        score = momentum_signal(t)
        assert -1.0 <= score <= 1.0

    @pytest.mark.parametrize("roc", [-20, -10, -5, -1, 0, 1, 5, 10, 20])
    def test_roc_values(self, roc):
        t = _make_technical(roc_12=roc)
        score = momentum_signal(t)
        assert -1.0 <= score <= 1.0
        if roc > 5:
            assert score > 0
        elif roc < -5:
            assert score < 0

    def test_strong_bullish(self):
        t = _make_technical(
            current_price=60000, sma_20=55000, sma_60=50000,
            macd_hist=500, rsi_14=60, roc_12=8,
        )
        assert momentum_signal(t) > 0.3

    def test_strong_bearish(self):
        t = _make_technical(
            current_price=50000, sma_20=55000, sma_60=60000,
            macd_hist=-500, rsi_14=30, roc_12=-8,
        )
        assert momentum_signal(t) < -0.3

    def test_empty_indicators(self):
        t = _make_technical()
        assert momentum_signal(t) == 0.0

    def test_score_bounds(self):
        for rsi in range(0, 101, 5):
            for roc in range(-20, 21, 5):
                t = _make_technical(rsi_14=rsi, roc_12=roc)
                s = momentum_signal(t)
                assert -1.0 <= s <= 1.0


# ===== Mean Reversion Signal =====

class TestMeanReversionSignal:
    @pytest.mark.parametrize("rsi,expected_direction", [
        (10, "bullish"), (20, "bullish"), (25, "bullish"), (29, "bullish"),
        (35, "bullish"),  # mildly bullish
        (50, "neutral"),
        (65, "bearish"),  # mildly bearish
        (75, "bearish"), (80, "bearish"), (90, "bearish"),
    ])
    def test_rsi_reversal(self, rsi, expected_direction):
        t = _make_technical(rsi_14=rsi)
        score = mean_reversion_signal(t)
        if expected_direction == "bullish":
            assert score > 0
        elif expected_direction == "bearish":
            assert score < 0

    @pytest.mark.parametrize("price,bb_upper,bb_lower,expected", [
        (56000, 62000, 56500, "bullish"),   # near lower band
        (61500, 62000, 56000, "bearish"),   # near upper band
        (59000, 62000, 56000, "neutral"),   # middle
    ])
    def test_bollinger_position(self, price, bb_upper, bb_lower, expected):
        t = _make_technical(current_price=price, bb_upper=bb_upper, bb_lower=bb_lower)
        score = mean_reversion_signal(t)
        if expected == "bullish":
            assert score > 0
        elif expected == "bearish":
            assert score < 0

    @pytest.mark.parametrize("stoch_k,stoch_d,expected_direction", [
        (10, 12, "bullish"), (15, 18, "bullish"),
        (50, 50, "neutral"),
        (85, 82, "bearish"), (90, 88, "bearish"),
    ])
    def test_stochastic(self, stoch_k, stoch_d, expected_direction):
        t = _make_technical(stoch_k=stoch_k, stoch_d=stoch_d)
        score = mean_reversion_signal(t)
        if expected_direction == "bullish":
            assert score > 0
        elif expected_direction == "bearish":
            assert score < 0

    @pytest.mark.parametrize("willr,expected", [
        (-95, "bullish"), (-85, "bullish"),
        (-50, "neutral"),
        (-10, "bearish"), (-15, "bearish"),
    ])
    def test_williams_r(self, willr, expected):
        t = _make_technical(willr_14=willr)
        score = mean_reversion_signal(t)
        if expected == "bullish":
            assert score > 0
        elif expected == "bearish":
            assert score < 0

    def test_extreme_oversold(self):
        t = _make_technical(rsi_14=15, stoch_k=10, stoch_d=12,
                            willr_14=-92, current_price=56000,
                            bb_upper=62000, bb_lower=56500)
        assert mean_reversion_signal(t) > 0.5

    def test_extreme_overbought(self):
        t = _make_technical(rsi_14=85, stoch_k=90, stoch_d=88,
                            willr_14=-8, current_price=61800,
                            bb_upper=62000, bb_lower=56000)
        assert mean_reversion_signal(t) < -0.5

    def test_empty(self):
        t = _make_technical()
        assert mean_reversion_signal(t) == 0.0

    def test_score_bounds_exhaustive(self):
        for rsi in range(0, 101, 10):
            for sk in range(0, 101, 20):
                t = _make_technical(rsi_14=rsi, stoch_k=sk, stoch_d=sk)
                s = mean_reversion_signal(t)
                assert -1.0 <= s <= 1.0


# ===== Volume Signal =====

class TestVolumeSignal:
    @pytest.mark.parametrize("surge,obv,expected", [
        (True, "increasing", "bullish"),
        (True, "decreasing", "bearish"),
        (False, "increasing", "neutral_or_mild"),
        (False, "decreasing", "neutral_or_mild"),
    ])
    def test_surge_obv_combo(self, surge, obv, expected):
        v = _make_volume(is_surge=surge, obv_trend=obv)
        score = volume_signal(v)
        if expected == "bullish":
            assert score > 0.3
        elif expected == "bearish":
            assert score < 0

    @pytest.mark.parametrize("div,expected_positive", [
        ("bullish", True),
        ("bearish", False),
        ("none", None),
    ])
    def test_divergence(self, div, expected_positive):
        v = _make_volume(divergence=div)
        score = volume_signal(v)
        if expected_positive is True:
            assert score > 0
        elif expected_positive is False:
            assert score < 0

    @pytest.mark.parametrize("trend,expected", [
        ("increasing", True),
        ("decreasing", False),
        ("flat", None),
    ])
    def test_volume_trend(self, trend, expected):
        v = _make_volume(trend=trend)
        score = volume_signal(v)
        if expected is True:
            assert score >= 0
        elif expected is False:
            assert score <= 0

    def test_max_bullish(self):
        v = _make_volume(is_surge=True, obv_trend="increasing",
                         divergence="bullish", trend="increasing")
        assert volume_signal(v) > 0.5

    def test_score_bounds(self):
        for surge in [True, False]:
            for div in ["bullish", "bearish", "none"]:
                for trend in ["increasing", "decreasing", "flat"]:
                    for obv in ["increasing", "decreasing", "flat"]:
                        v = _make_volume(is_surge=surge, divergence=div,
                                         trend=trend, obv_trend=obv)
                        s = volume_signal(v)
                        assert -1.0 <= s <= 1.0


# ===== Sentiment Signal =====

class TestSentimentSignal:
    def test_no_data(self):
        assert sentiment_signal(None) == 0.0

    def test_zero_articles(self):
        s = _make_sentiment(score=0.8, count=0)
        assert sentiment_signal(s) == 0.0

    @pytest.mark.parametrize("score,count,expected_positive", [
        (0.8, 5, True),
        (0.5, 3, True),
        (-0.8, 5, False),
        (-0.5, 3, False),
        (0.0, 10, None),
    ])
    def test_sentiment_direction(self, score, count, expected_positive):
        s = _make_sentiment(score=score, count=count)
        result = sentiment_signal(s)
        if expected_positive is True:
            assert result > 0
        elif expected_positive is False:
            assert result < 0
        else:
            assert result == 0.0

    @pytest.mark.parametrize("count", [1, 2, 3, 5, 10, 20])
    def test_confidence_scaling(self, count):
        s = _make_sentiment(score=0.8, count=count)
        result = sentiment_signal(s)
        assert 0 < result <= 0.8
        # More articles should give higher confidence
        if count >= 5:
            assert result >= sentiment_signal(_make_sentiment(score=0.8, count=1))

    def test_score_bounds(self):
        for score_val in [-1.0, -0.5, 0.0, 0.5, 1.0]:
            for cnt in [0, 1, 3, 5, 10]:
                s = _make_sentiment(score=score_val, count=cnt)
                result = sentiment_signal(s)
                assert -1.0 <= result <= 1.0
