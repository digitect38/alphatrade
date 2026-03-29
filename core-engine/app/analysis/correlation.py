import logging
from datetime import datetime, timezone

import asyncpg
import numpy as np
import pandas as pd
from scipy import stats
from app.models.sentiment import CausalityResult, CorrelationPair, CorrelationResult

logger = logging.getLogger(__name__)


async def _fetch_close_series(stock_codes: list[str], period: int, *, pool: asyncpg.Pool) -> pd.DataFrame:
    """Fetch close prices for multiple stocks and align by date."""
    frames = {}

    for code in stock_codes:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT time::date as date, close
                FROM ohlcv
                WHERE stock_code = $1 AND interval = '1d'
                ORDER BY time DESC
                LIMIT $2
                """,
                code,
                period,
            )
        if rows:
            df = pd.DataFrame([dict(r) for r in rows])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.set_index("date").sort_index()
            frames[code] = df["close"]

    if not frames:
        return pd.DataFrame()

    combined = pd.DataFrame(frames).dropna()
    return combined


async def compute_correlation_matrix(
    stock_codes: list[str], period: int = 60, method: str = "pearson",
    *, pool: asyncpg.Pool,
) -> CorrelationResult:
    """Compute correlation matrix between stocks."""
    now = datetime.now(timezone.utc)

    if len(stock_codes) < 2:
        return CorrelationResult(matrix={}, computed_at=now)

    df = await _fetch_close_series(stock_codes, period, pool=pool)

    if df.empty or len(df) < 5:
        return CorrelationResult(
            matrix={c: {c2: 0.0 for c2 in stock_codes} for c in stock_codes},
            computed_at=now,
        )

    # Compute returns for correlation (more stationary than prices)
    returns = df.pct_change().dropna()

    if returns.empty:
        return CorrelationResult(matrix={}, computed_at=now)

    corr_matrix = returns.corr(method=method)

    # Convert to dict
    matrix = {}
    for code in corr_matrix.columns:
        matrix[code] = {}
        for code2 in corr_matrix.columns:
            val = corr_matrix.loc[code, code2]
            matrix[code][code2] = round(float(val), 4) if not np.isnan(val) else 0.0

    # Find high/low correlation pairs
    high_pairs = []
    low_pairs = []
    seen = set()

    for i, c1 in enumerate(stock_codes):
        for c2 in stock_codes[i + 1:]:
            if c1 in matrix and c2 in matrix.get(c1, {}):
                corr = matrix[c1][c2]
                pair_key = tuple(sorted([c1, c2]))
                if pair_key not in seen:
                    seen.add(pair_key)
                    if corr > 0.7:
                        high_pairs.append(CorrelationPair(stock_a=c1, stock_b=c2, correlation=corr))
                    elif corr < -0.3:
                        low_pairs.append(CorrelationPair(stock_a=c1, stock_b=c2, correlation=corr))

    high_pairs.sort(key=lambda x: x.correlation, reverse=True)
    low_pairs.sort(key=lambda x: x.correlation)

    return CorrelationResult(
        matrix=matrix,
        high_pairs=high_pairs,
        low_pairs=low_pairs,
        computed_at=now,
    )


async def granger_causality_test(
    stock_a: str, stock_b: str, max_lag: int = 5,
    *, pool: asyncpg.Pool,
) -> CausalityResult:
    """Perform Granger causality test between two stocks."""
    now = datetime.now(timezone.utc)

    df = await _fetch_close_series([stock_a, stock_b], period=120, pool=pool)

    if df.empty or len(df) < max_lag + 10 or stock_a not in df.columns or stock_b not in df.columns:
        return CausalityResult(
            stock_a=stock_a,
            stock_b=stock_b,
            computed_at=now,
        )

    # Compute log returns
    returns = np.log(df / df.shift(1)).dropna()
    y_a = returns[stock_a].values
    y_b = returns[stock_b].values

    # Test A -> B (does A Granger-cause B?)
    a_to_b_pval, a_to_b_lag = _granger_test(y_a, y_b, max_lag)

    # Test B -> A
    b_to_a_pval, b_to_a_lag = _granger_test(y_b, y_a, max_lag)

    significance = 0.05
    optimal_lag = a_to_b_lag if a_to_b_pval < b_to_a_pval else b_to_a_lag

    return CausalityResult(
        stock_a=stock_a,
        stock_b=stock_b,
        a_causes_b=a_to_b_pval < significance,
        b_causes_a=b_to_a_pval < significance,
        a_to_b_pvalue=round(a_to_b_pval, 6),
        b_to_a_pvalue=round(b_to_a_pval, 6),
        optimal_lag=optimal_lag,
        computed_at=now,
    )


def _granger_test(x: np.ndarray, y: np.ndarray, max_lag: int) -> tuple[float, int]:
    """
    Simple Granger causality F-test: does x Granger-cause y?
    Returns (best_pvalue, best_lag).
    """
    n = len(y)
    best_pval = 1.0
    best_lag = 1

    for lag in range(1, max_lag + 1):
        if n <= lag + 2:
            continue

        # Restricted model: y_t = a0 + a1*y_{t-1} + ... + a_lag*y_{t-lag}
        # Unrestricted model: y_t = a0 + a1*y_{t-1} + ... + b1*x_{t-1} + ... + b_lag*x_{t-lag}

        y_dep = y[lag:]

        # Build lagged matrices
        y_lags = np.column_stack([y[lag - i - 1: n - i - 1] for i in range(lag)])
        x_lags = np.column_stack([x[lag - i - 1: n - i - 1] for i in range(lag)])

        # Restricted: only y lags
        X_r = np.column_stack([np.ones(len(y_dep)), y_lags])
        # Unrestricted: y lags + x lags
        X_u = np.column_stack([np.ones(len(y_dep)), y_lags, x_lags])

        try:
            # OLS for restricted
            beta_r = np.linalg.lstsq(X_r, y_dep, rcond=None)[0]
            resid_r = y_dep - X_r @ beta_r
            ssr_r = np.sum(resid_r ** 2)

            # OLS for unrestricted
            beta_u = np.linalg.lstsq(X_u, y_dep, rcond=None)[0]
            resid_u = y_dep - X_u @ beta_u
            ssr_u = np.sum(resid_u ** 2)

            # F-statistic
            df1 = lag  # number of restrictions
            df2 = len(y_dep) - X_u.shape[1]

            if df2 <= 0 or ssr_u <= 0:
                continue

            f_stat = ((ssr_r - ssr_u) / df1) / (ssr_u / df2)
            p_value = 1 - stats.f.cdf(f_stat, df1, df2)

            if p_value < best_pval:
                best_pval = p_value
                best_lag = lag
        except Exception:
            continue

    return best_pval, best_lag
