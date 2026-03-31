"""Stress test engine — scenario-based portfolio risk analysis.

Applies historical crisis scenarios to the current portfolio
to estimate potential losses under extreme conditions.

Built-in scenarios:
- 2020 COVID crash (Feb-Mar 2020)
- 2022 rate hike shock
- Circuit breaker day (-8% index drop)
- Flash crash (-5% in 30 min)
- Sector rotation (tech -10%, defensive +5%)
"""

import logging
from datetime import datetime, timezone

import asyncpg
import numpy as np

logger = logging.getLogger(__name__)

# Pre-defined stress scenarios
# Each scenario: {name, description, market_shock_pct, sector_shocks: {sector: pct}}
STRESS_SCENARIOS = {
    "covid_crash": {
        "name": "COVID-19 Crash (2020.03)",
        "description": "2020년 3월 코로나 폭락 — KOSPI -30%, 전 업종 급락",
        "market_shock_pct": -30.0,
        "duration_days": 20,
        "sector_shocks": {
            "항공": -50, "여행": -50, "호텔": -45,
            "의료": +10, "제약": +15, "바이오": +20,
            "IT": -25, "반도체": -20, "자동차": -35,
            "금융": -30, "보험": -25, "건설": -30,
            "음식료": -15, "유통": -20,
        },
    },
    "rate_hike": {
        "name": "Rate Hike Shock (2022)",
        "description": "2022년 금리 인상 충격 — 성장주 급락, 가치주 상대 강세",
        "market_shock_pct": -20.0,
        "duration_days": 60,
        "sector_shocks": {
            "IT": -30, "바이오": -35, "게임": -30,
            "반도체": -15, "금융": -5, "보험": -5,
            "에너지": +5, "유틸리티": -5,
            "자동차": -20, "건설": -15,
        },
    },
    "circuit_breaker": {
        "name": "Circuit Breaker Day",
        "description": "서킷브레이커 발동 — 1일 KOSPI -8%, 변동성 극대화",
        "market_shock_pct": -8.0,
        "duration_days": 1,
        "sector_shocks": {},  # All sectors hit equally
    },
    "flash_crash": {
        "name": "Flash Crash",
        "description": "플래시 크래시 — 30분 내 5% 급락 후 부분 회복",
        "market_shock_pct": -5.0,
        "duration_days": 1,
        "sector_shocks": {},
    },
    "sector_rotation": {
        "name": "Sector Rotation",
        "description": "섹터 로테이션 — 기술주→방어주 대전환",
        "market_shock_pct": -3.0,
        "duration_days": 30,
        "sector_shocks": {
            "IT": -15, "반도체": -12, "게임": -15, "바이오": -10,
            "음식료": +5, "유틸리티": +3, "통신": +2,
            "금융": +3, "보험": +2,
        },
    },
    "custom_worst_case": {
        "name": "Custom Worst Case",
        "description": "전 종목 동시 -15% 하락 (최악의 가정)",
        "market_shock_pct": -15.0,
        "duration_days": 5,
        "sector_shocks": {},
    },
}


async def run_stress_test(
    *,
    pool: asyncpg.Pool,
    scenarios: list[str] | None = None,
) -> dict:
    """Run stress tests on current portfolio.

    Args:
        pool: Database pool
        scenarios: List of scenario keys to test (None = all)

    Returns:
        Dict with per-scenario results and portfolio impact.
    """
    now = datetime.now(timezone.utc)

    # Get current positions with sector info
    async with pool.acquire() as conn:
        positions = await conn.fetch(
            """SELECT pp.stock_code, pp.quantity, pp.avg_price, pp.current_price,
                      s.sector, s.stock_name
            FROM portfolio_positions pp
            LEFT JOIN stocks s ON pp.stock_code = s.stock_code
            WHERE pp.quantity > 0"""
        )
        snapshot = await conn.fetchrow(
            "SELECT total_value, cash FROM portfolio_snapshots ORDER BY time DESC LIMIT 1"
        )

    if not positions:
        return {"message": "No positions to stress test", "computed_at": now.isoformat()}

    total_value = float(snapshot["total_value"]) if snapshot else 0
    cash = float(snapshot["cash"]) if snapshot else 0

    # Build position detail
    pos_list = []
    for p in positions:
        current = float(p["current_price"]) if p["current_price"] else float(p["avg_price"])
        pos_list.append({
            "stock_code": p["stock_code"],
            "stock_name": p["stock_name"] or p["stock_code"],
            "sector": p["sector"] or "기타",
            "quantity": p["quantity"],
            "current_price": current,
            "current_value": p["quantity"] * current,
        })

    # Run each scenario
    scenario_keys = scenarios or list(STRESS_SCENARIOS.keys())
    results = []

    for key in scenario_keys:
        scenario = STRESS_SCENARIOS.get(key)
        if not scenario:
            continue

        result = _apply_scenario(pos_list, total_value, cash, key, scenario)
        results.append(result)

    # Sort by impact (worst first)
    results.sort(key=lambda x: x["portfolio_impact_pct"])

    # Summary
    worst = results[0] if results else None
    best = results[-1] if results else None

    return {
        "portfolio": {
            "total_value": round(total_value, 0),
            "cash": round(cash, 0),
            "invested": round(total_value - cash, 0),
            "positions_count": len(pos_list),
        },
        "worst_scenario": {
            "name": worst["scenario_name"] if worst else None,
            "impact_pct": worst["portfolio_impact_pct"] if worst else 0,
            "impact_amount": worst["portfolio_impact_amount"] if worst else 0,
        },
        "scenarios": results,
        "computed_at": now.isoformat(),
    }


def _apply_scenario(
    positions: list[dict],
    total_value: float,
    cash: float,
    scenario_key: str,
    scenario: dict,
) -> dict:
    """Apply a stress scenario to the portfolio and compute impact."""
    market_shock = scenario["market_shock_pct"] / 100
    sector_shocks = {k: v / 100 for k, v in scenario.get("sector_shocks", {}).items()}

    total_loss = 0
    position_impacts = []

    for pos in positions:
        sector = pos["sector"]
        value = pos["current_value"]

        # Use sector-specific shock if available, else market-wide
        shock = sector_shocks.get(sector, market_shock)
        loss = value * shock
        stressed_value = value + loss

        total_loss += loss
        position_impacts.append({
            "stock_code": pos["stock_code"],
            "stock_name": pos["stock_name"],
            "sector": sector,
            "current_value": round(value, 0),
            "shock_pct": round(shock * 100, 1),
            "impact_amount": round(loss, 0),
            "stressed_value": round(stressed_value, 0),
        })

    stressed_total = total_value + total_loss
    impact_pct = (total_loss / total_value * 100) if total_value > 0 else 0

    # Sort by loss (biggest loss first)
    position_impacts.sort(key=lambda x: x["impact_amount"])

    return {
        "scenario_key": scenario_key,
        "scenario_name": scenario["name"],
        "description": scenario["description"],
        "duration_days": scenario["duration_days"],
        "market_shock_pct": scenario["market_shock_pct"],
        "portfolio_impact_pct": round(impact_pct, 2),
        "portfolio_impact_amount": round(total_loss, 0),
        "stressed_total_value": round(stressed_total, 0),
        "cash_unchanged": round(cash, 0),
        "position_impacts": position_impacts[:10],  # Top 10 impacts
    }
