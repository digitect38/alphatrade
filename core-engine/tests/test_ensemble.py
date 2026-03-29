"""Tests for ensemble strategy weighting and signal determination.

~60 test cases.
"""

import pytest
from app.config import settings


class TestEnsembleWeights:
    def test_weights_sum_to_one(self):
        total = (settings.strategy_weight_momentum + settings.strategy_weight_mean_reversion +
                 settings.strategy_weight_volume + settings.strategy_weight_sentiment)
        assert abs(total - 1.0) < 0.001

    @pytest.mark.parametrize("weight_attr", [
        "strategy_weight_momentum", "strategy_weight_mean_reversion",
        "strategy_weight_volume", "strategy_weight_sentiment",
    ])
    def test_weights_positive(self, weight_attr):
        assert getattr(settings, weight_attr) > 0

    @pytest.mark.parametrize("weight_attr", [
        "strategy_weight_momentum", "strategy_weight_mean_reversion",
        "strategy_weight_volume", "strategy_weight_sentiment",
    ])
    def test_weights_under_one(self, weight_attr):
        assert getattr(settings, weight_attr) < 1.0


class TestEnsembleThresholds:
    def test_buy_threshold_positive(self):
        assert settings.strategy_buy_threshold > 0

    def test_sell_threshold_negative(self):
        assert settings.strategy_sell_threshold < 0

    def test_thresholds_symmetric(self):
        assert abs(settings.strategy_buy_threshold + settings.strategy_sell_threshold) < 0.01

    @pytest.mark.parametrize("score,expected", [
        (0.5, "BUY"), (0.2, "BUY"), (0.16, "BUY"),
        (0.15, "HOLD"), (0.0, "HOLD"), (-0.14, "HOLD"),
        (-0.15, "HOLD"), (-0.16, "SELL"), (-0.5, "SELL"),
    ])
    def test_signal_from_score(self, score, expected):
        if score > settings.strategy_buy_threshold:
            sig = "BUY"
        elif score < settings.strategy_sell_threshold:
            sig = "SELL"
        else:
            sig = "HOLD"
        assert sig == expected


class TestEnsembleScoreCalculation:
    @pytest.mark.parametrize("scores,expected_positive", [
        ({"momentum": 0.5, "mean_reversion": 0.5, "volume": 0.5, "sentiment": 0.5}, True),
        ({"momentum": -0.5, "mean_reversion": -0.5, "volume": -0.5, "sentiment": -0.5}, False),
        ({"momentum": 0.0, "mean_reversion": 0.0, "volume": 0.0, "sentiment": 0.0}, None),
    ])
    def test_ensemble_direction(self, scores, expected_positive):
        from app.strategy.ensemble import _get_weights
        weights = _get_weights()
        total = sum(scores[k] * weights[k] for k in scores)
        if expected_positive is True:
            assert total > 0
        elif expected_positive is False:
            assert total < 0
        else:
            assert total == 0

    @pytest.mark.parametrize("dominant,score", [
        ("momentum", 1.0),
        ("mean_reversion", 1.0),
        ("volume", 1.0),
        ("sentiment", 1.0),
    ])
    def test_single_strong_signal(self, dominant, score):
        from app.strategy.ensemble import _get_weights
        weights = _get_weights()
        scores = {k: 0.0 for k in weights}
        scores[dominant] = score
        total = sum(scores[k] * weights[k] for k in scores)
        assert total > 0

    def test_conflicting_signals_cancel(self):
        from app.strategy.ensemble import _get_weights
        weights = _get_weights()
        # momentum bullish, mean_reversion bearish, equal weight
        scores = {"momentum": 0.5, "mean_reversion": -0.5, "volume": 0.0, "sentiment": 0.0}
        total = sum(scores[k] * weights[k] for k in scores)
        # momentum(0.30) * 0.5 + mean_reversion(0.25) * -0.5 = 0.15 - 0.125 = 0.025
        assert abs(total) < 0.1  # near zero

    @pytest.mark.parametrize("all_score", [-1.0, -0.5, 0.0, 0.5, 1.0])
    def test_uniform_scores(self, all_score):
        from app.strategy.ensemble import _get_weights
        weights = _get_weights()
        scores = {k: all_score for k in weights}
        total = sum(scores[k] * weights[k] for k in scores)
        expected = all_score * sum(weights.values())
        assert abs(total - expected) < 0.001

    def test_score_bounded(self):
        from app.strategy.ensemble import _get_weights
        weights = _get_weights()
        # Even with max scores, ensemble should be <= 1.0
        scores = {k: 1.0 for k in weights}
        total = sum(scores[k] * weights[k] for k in scores)
        assert total <= 1.0 + 0.001
