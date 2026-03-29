"""Tests for position sizing logic.

~150 test cases via parametrize.
"""

import pytest
from app.trading.position_sizer import calculate_quantity, calculate_sell_quantity


# ===== Buy Quantity =====

class TestCalculateQuantity:
    @pytest.mark.parametrize("price", [0, -100])
    def test_zero_or_negative_price(self, price):
        assert calculate_quantity(0.5, 10_000_000, 10_000_000, price) == 0

    def test_zero_cash(self):
        assert calculate_quantity(0.5, 10_000_000, 0, 60000) == 0

    def test_zero_portfolio(self):
        assert calculate_quantity(0.5, 0, 10_000_000, 60000) == 0

    @pytest.mark.parametrize("strength", [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0])
    def test_strength_scaling(self, strength):
        qty = calculate_quantity(strength, 10_000_000, 10_000_000, 60000)
        assert qty >= 0
        # Higher strength should generally give more shares (with min 0.3 floor)
        if strength >= 0.3:
            assert qty > 0

    @pytest.mark.parametrize("portfolio,cash,price,expected_min,expected_max", [
        (10_000_000, 10_000_000, 60000, 0, 50),  # realistic range
        (10_000_000, 1_000_000, 60000, 0, 5),    # low cash
        (10_000_000, 10_000_000, 500, 0, 9000),   # cheap stock
        (100_000_000, 100_000_000, 60000, 0, 500), # big portfolio
    ])
    def test_quantity_ranges(self, portfolio, cash, price, expected_min, expected_max):
        qty = calculate_quantity(0.5, portfolio, cash, price)
        assert expected_min <= qty <= expected_max

    @pytest.mark.parametrize("existing_qty,existing_avg", [
        (0, 0),
        (5, 60000),
        (10, 55000),
        (20, 58000),
    ])
    def test_existing_position(self, existing_qty, existing_avg):
        qty = calculate_quantity(0.5, 10_000_000, 5_000_000, 60000,
                                 existing_qty, existing_avg)
        # Should buy less when already holding
        assert qty >= 0
        if existing_qty > 0:
            no_hold = calculate_quantity(0.5, 10_000_000, 5_000_000, 60000, 0, 0)
            assert qty <= no_hold

    def test_below_min_order_value(self):
        # MIN_ORDER_VALUE = 100_000
        # Very small allocation should return 0
        qty = calculate_quantity(0.01, 1_000_000, 1_000_000, 60000)
        # With 0.3 floor on strength: 1M * 0.15 * 0.3 = 45000 < 100000
        assert qty == 0

    @pytest.mark.parametrize("price", [1000, 5000, 10000, 50000, 100000, 500000, 1000000])
    def test_various_price_levels(self, price):
        qty = calculate_quantity(0.7, 10_000_000, 10_000_000, price)
        if price <= 500000:
            assert qty >= 0
        # Very expensive stock: might get 0
        assert qty * price <= 10_000_000  # Never exceeds portfolio

    def test_cash_constraint(self):
        # Cash is only 500K, even with big portfolio
        qty = calculate_quantity(1.0, 50_000_000, 500_000, 60000)
        assert qty * 60000 <= 500_000 * 0.3  # max 30% of cash per order


# ===== Sell Quantity =====

class TestCalculateSellQuantity:
    def test_zero_held(self):
        assert calculate_sell_quantity(0, 0.5) == 0

    @pytest.mark.parametrize("held", [1, 5, 10, 50, 100])
    def test_strong_signal_full_exit(self, held):
        qty = calculate_sell_quantity(held, 0.7)
        assert qty == held  # Full exit

    @pytest.mark.parametrize("held", [1, 5, 10, 50, 100])
    def test_medium_signal_half_exit(self, held):
        qty = calculate_sell_quantity(held, 0.5)
        assert qty == max(1, int(held * 0.5))

    @pytest.mark.parametrize("held", [1, 5, 10, 50, 100])
    def test_weak_signal_trim(self, held):
        qty = calculate_sell_quantity(held, 0.2)
        assert qty == max(1, int(held * 0.3))

    @pytest.mark.parametrize("strength", [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    def test_sell_always_at_least_one(self, strength):
        qty = calculate_sell_quantity(10, strength)
        assert qty >= 1

    @pytest.mark.parametrize("strength", [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    def test_sell_never_exceeds_held(self, strength):
        held = 5
        qty = calculate_sell_quantity(held, strength)
        assert qty <= held

    @pytest.mark.parametrize("held,strength", [
        (1, 0.1), (1, 0.5), (1, 1.0),
        (2, 0.1), (2, 0.5), (2, 1.0),
    ])
    def test_small_positions(self, held, strength):
        qty = calculate_sell_quantity(held, strength)
        assert 1 <= qty <= held
