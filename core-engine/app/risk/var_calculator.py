"""Portfolio VaR/CVaR calculator.

Computes Value at Risk and Conditional VaR (Expected Shortfall)
using historical simulation method.

- Historical VaR: Uses actual past return distribution
- CVaR (ES): Average of losses beyond VaR threshold
- Marginal VaR: Per-position contribution to portfolio VaR
"""

import logging
from datetime import datetime, timezone

import asyncpg
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 252  # 1 year of trading days
DEFAULT_CONFIDENCE_LEVELS = [0.95, 0.99]


async def compute_portfolio_var(
    *,
    pool: asyncpg.Pool,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    confidence_levels: list[float] | None = None,
) -> dict:
    """Compute portfolio VaR and CVaR using historical simulation.

    Steps:
    1. Get current positions
    2. Fetch historical daily returns for each position
    3. Compute portfolio-weighted daily returns
    4. Calculate VaR/CVaR from the empirical distribution

    Returns dict with VaR, CVaR, per-position marginal VaR, and risk metrics.
    """
    if confidence_levels is None:
        confidence_levels = DEFAULT_CONFIDENCE_LEVELS

    now = datetime.now(timezone.utc)

    # 1. Get current positions
    async with pool.acquire() as conn:
        positions = await conn.fetch(
            """SELECT stock_code, quantity, avg_price, current_price
            FROM portfolio_positions WHERE quantity > 0"""
        )
        snapshot = await conn.fetchrow(
            "SELECT total_value, cash FROM portfolio_snapshots ORDER BY time DESC LIMIT 1"
        )

    if not positions:
        return {"message": "No positions", "computed_at": now.isoformat()}

    total_value = float(snapshot["total_value"]) if snapshot else 0
    cash = float(snapshot["cash"]) if snapshot else 0

    # 2. Fetch historical returns for each position
    stock_codes = [p["stock_code"] for p in positions]
    returns_data = {}

    async with pool.acquire() as conn:
        for code in stock_codes:
            rows = await conn.fetch(
                """SELECT time::date as date, close
                FROM ohlcv
                WHERE stock_code = $1 AND interval = '1d'
                ORDER BY time DESC LIMIT $2""",
                code, lookback_days + 1,
            )
            if len(rows) >= 10:
                prices = sorted(
                    [(r["date"], float(r["close"])) for r in rows if r["close"]],
                    key=lambda x: x[0],
                )
                price_series = pd.Series(
                    [p[1] for p in prices],
                    index=[p[0] for p in prices],
                )
                returns_data[code] = price_series.pct_change().dropna()

    if not returns_data:
        return {"message": "Insufficient historical data", "computed_at": now.isoformat()}

    # 3. Build portfolio weights
    weights = {}
    position_values = {}
    for pos in positions:
        code = pos["stock_code"]
        current = float(pos["current_price"]) if pos["current_price"] else float(pos["avg_price"])
        val = pos["quantity"] * current
        position_values[code] = val
        weights[code] = val / total_value if total_value > 0 else 0

    # Align returns to common dates
    returns_df = pd.DataFrame(returns_data)
    returns_df = returns_df.dropna()

    if returns_df.empty or len(returns_df) < 10:
        return {"message": "Insufficient overlapping data", "computed_at": now.isoformat()}

    # 4. Compute portfolio daily returns (weighted sum)
    weight_vector = np.array([weights.get(col, 0) for col in returns_df.columns])
    portfolio_returns = returns_df.values @ weight_vector

    # 5. Calculate VaR and CVaR
    var_results = {}
    for level in confidence_levels:
        alpha = 1 - level
        var_pct = float(np.percentile(portfolio_returns, alpha * 100))
        var_amount = round(var_pct * total_value, 0)

        # CVaR = mean of returns below VaR
        tail_returns = portfolio_returns[portfolio_returns <= var_pct]
        cvar_pct = float(np.mean(tail_returns)) if len(tail_returns) > 0 else var_pct
        cvar_amount = round(cvar_pct * total_value, 0)

        key = f"{int(level * 100)}%"
        var_results[key] = {
            "var_pct": round(var_pct * 100, 3),
            "var_amount": var_amount,
            "cvar_pct": round(cvar_pct * 100, 3),
            "cvar_amount": cvar_amount,
        }

    # 6. Marginal VaR per position (Component VaR)
    marginal_var = []
    base_var_95 = float(np.percentile(portfolio_returns, 5))

    for code in returns_df.columns:
        if code not in weights or weights[code] == 0:
            continue

        # Marginal VaR: VaR contribution = weight * beta * portfolio VaR
        pos_returns = returns_df[code].values
        cov = np.cov(pos_returns, portfolio_returns)
        if cov.shape == (2, 2) and cov[1, 1] > 0:
            beta = cov[0, 1] / cov[1, 1]
        else:
            beta = 1.0

        component_var = weights[code] * beta * base_var_95 * total_value
        marginal_var.append({
            "stock_code": code,
            "weight_pct": round(weights[code] * 100, 1),
            "beta": round(beta, 3),
            "component_var": round(component_var, 0),
            "pct_of_portfolio_var": round(
                component_var / (base_var_95 * total_value) * 100, 1
            ) if base_var_95 * total_value != 0 else 0,
        })

    marginal_var.sort(key=lambda x: x["component_var"])

    # 7. Additional risk metrics
    vol = float(np.std(portfolio_returns)) * np.sqrt(252)  # annualized
    mean_return = float(np.mean(portfolio_returns)) * 252
    sharpe = mean_return / vol if vol > 0 else 0
    max_daily_loss = float(np.min(portfolio_returns))
    skewness = float(pd.Series(portfolio_returns).skew())
    kurtosis = float(pd.Series(portfolio_returns).kurtosis())

    return {
        "total_value": total_value,
        "cash": cash,
        "invested": total_value - cash,
        "lookback_days": len(returns_df),
        "positions_count": len(positions),
        "var": var_results,
        "marginal_var": marginal_var,
        "risk_metrics": {
            "annualized_volatility_pct": round(vol * 100, 2),
            "annualized_return_pct": round(mean_return * 100, 2),
            "sharpe_ratio": round(sharpe, 3),
            "max_daily_loss_pct": round(max_daily_loss * 100, 3),
            "skewness": round(skewness, 3),
            "excess_kurtosis": round(kurtosis, 3),
        },
        "computed_at": now.isoformat(),
    }
