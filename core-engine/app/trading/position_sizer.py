"""Position sizing: determine order quantity based on signal strength and portfolio state."""

import logging

from app.config import settings

logger = logging.getLogger(__name__)


def calculate_quantity(
    signal_strength: float,
    portfolio_value: float,
    cash: float,
    current_price: float,
    existing_quantity: int = 0,
    existing_avg_price: float = 0,
) -> int:
    """Calculate order quantity for a BUY signal.

    Args:
        signal_strength: 0.0 ~ 1.0 from strategy signal
        portfolio_value: total portfolio value
        cash: available cash
        current_price: current stock price
        existing_quantity: shares already held
        existing_avg_price: average price of existing position

    Returns:
        Number of shares to buy (0 if not worth buying)
    """
    if current_price <= 0 or cash <= 0 or portfolio_value <= 0:
        return 0

    # Target investment = portfolio_value * settings.sizing_max_position_pct * signal_strength
    target_value = portfolio_value * settings.sizing_max_position_pct * max(signal_strength, settings.sizing_min_signal_strength)

    # Subtract existing position value
    existing_value = existing_quantity * current_price
    remaining_target = target_value - existing_value

    if remaining_target <= 0:
        return 0  # Already at or above target

    # Cap by cash available
    max_from_cash = cash * settings.sizing_max_cash_per_order_pct
    invest = min(remaining_target, max_from_cash)

    # Minimum order check
    if invest < settings.sizing_min_order_value:
        return 0

    quantity = int(invest / current_price)
    return max(0, quantity)


def calculate_sell_quantity(
    held_quantity: int,
    signal_strength: float,
) -> int:
    """Calculate sell quantity for a SELL signal.

    For strong signals, sell all. For weaker signals, sell partial.
    """
    if held_quantity <= 0:
        return 0

    if signal_strength >= settings.sizing_full_exit_strength:
        return held_quantity  # Full exit
    elif signal_strength >= settings.sizing_half_exit_strength:
        return max(1, int(held_quantity * settings.sizing_half_exit_ratio))  # Half exit
    else:
        return max(1, int(held_quantity * settings.sizing_trim_ratio))  # Trim
