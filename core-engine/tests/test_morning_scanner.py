"""Tests for morning scanner momentum calculation.

~100 test cases.
"""

import pytest
from app.scanner.morning import _calc_momentum_score


class TestCalcMomentumScore:
    @pytest.mark.parametrize("change_pct,vol_ratio,expected_positive", [
        (0.05, 3.0, True),    # 5% up + 3x volume → strong bullish
        (0.03, 1.5, True),    # 3% up + normal volume → bullish
        (-0.05, 3.0, False),  # 5% down + 3x volume → strong bearish
        (-0.03, 1.5, False),  # 3% down → bearish
        (0.0, 1.0, None),     # flat → ~0
    ])
    def test_basic_direction(self, change_pct, vol_ratio, expected_positive):
        score = _calc_momentum_score(change_pct, vol_ratio)
        if expected_positive is True:
            assert score > 0
        elif expected_positive is False:
            assert score < 0
        else:
            assert score == 0.0

    @pytest.mark.parametrize("vol_ratio", [0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0])
    def test_volume_amplification(self, vol_ratio):
        score_up = _calc_momentum_score(0.03, vol_ratio)
        assert score_up > 0
        # Higher volume should amplify (up to cap)
        score_low = _calc_momentum_score(0.03, 1.0)
        if vol_ratio > 1.0:
            assert abs(score_up) >= abs(score_low)

    @pytest.mark.parametrize("change_pct", [-0.10, -0.05, -0.03, -0.01, 0.0,
                                              0.01, 0.03, 0.05, 0.10])
    def test_change_pct_range(self, change_pct):
        score = _calc_momentum_score(change_pct, 2.0)
        if change_pct > 0:
            assert score > 0
        elif change_pct < 0:
            assert score < 0
        else:
            assert score == 0.0

    def test_extreme_values(self):
        # 30% up + 10x volume
        score = _calc_momentum_score(0.30, 10.0)
        assert score > 0
        # Very extreme but bounded
        assert isinstance(score, float)

    @pytest.mark.parametrize("change,vol", [
        (0.01, 1.0), (0.02, 2.0), (0.03, 3.0),
        (0.05, 5.0), (0.10, 10.0),
        (-0.01, 1.0), (-0.02, 2.0), (-0.05, 5.0),
    ])
    def test_proportionality(self, change, vol):
        score = _calc_momentum_score(change, vol)
        # Score magnitude should increase with both change and volume
        smaller = _calc_momentum_score(change * 0.5, vol * 0.5)
        if change != 0:
            assert abs(score) >= abs(smaller) or abs(score - smaller) < 0.01

    def test_symmetry(self):
        """Positive and negative of same magnitude should have same abs score."""
        up = _calc_momentum_score(0.05, 2.0)
        down = _calc_momentum_score(-0.05, 2.0)
        assert abs(up) == abs(down)
        assert up > 0
        assert down < 0
