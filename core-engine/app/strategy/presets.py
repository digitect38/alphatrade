"""Strategy presets — pre-defined trading strategy configurations.

Each preset defines:
- name, description
- component weights (momentum, mean_reversion, volume, sentiment)
- buy/sell thresholds
- risk parameters
"""

STRATEGY_PRESETS = {
    "ensemble": {
        "name": "앙상블 (기본)",
        "name_en": "Ensemble (Default)",
        "description": "모멘텀, 평균회귀, 거래량, 센티먼트를 균형있게 조합",
        "weights": {"momentum": 0.30, "mean_reversion": 0.25, "volume": 0.20, "sentiment": 0.25},
        "buy_threshold": 0.15,
        "sell_threshold": -0.15,
        "risk_level": "medium",
    },
    "momentum": {
        "name": "모멘텀 추세추종",
        "name_en": "Momentum Trend-Following",
        "description": "강한 추세를 따라가는 전략. 상승 추세 확인 후 진입, 추세 전환 시 탈출.",
        "weights": {"momentum": 0.60, "mean_reversion": 0.05, "volume": 0.25, "sentiment": 0.10},
        "buy_threshold": 0.20,
        "sell_threshold": -0.10,
        "risk_level": "high",
    },
    "mean_reversion": {
        "name": "평균회귀 역추세",
        "name_en": "Mean Reversion Contrarian",
        "description": "과매도 종목 매수, 과매수 종목 매도. RSI/볼린저밴드 기반.",
        "weights": {"momentum": 0.05, "mean_reversion": 0.60, "volume": 0.20, "sentiment": 0.15},
        "buy_threshold": 0.10,
        "sell_threshold": -0.20,
        "risk_level": "medium",
    },
    "volume_breakout": {
        "name": "거래량 돌파",
        "name_en": "Volume Breakout",
        "description": "거래량 급증 + 가격 돌파 시 진입. 단기 트레이딩에 적합.",
        "weights": {"momentum": 0.25, "mean_reversion": 0.05, "volume": 0.55, "sentiment": 0.15},
        "buy_threshold": 0.25,
        "sell_threshold": -0.15,
        "risk_level": "high",
    },
    "sentiment_driven": {
        "name": "센티먼트 기반",
        "name_en": "Sentiment-Driven",
        "description": "뉴스/공시 감성분석 중심. AI 분석 결과를 최우선으로 반영.",
        "weights": {"momentum": 0.15, "mean_reversion": 0.10, "volume": 0.15, "sentiment": 0.60},
        "buy_threshold": 0.15,
        "sell_threshold": -0.15,
        "risk_level": "medium",
    },
    "conservative": {
        "name": "보수적 안전",
        "name_en": "Conservative Safety",
        "description": "낮은 매매 빈도, 높은 확신 시에만 진입. 자본 보존 우선.",
        "weights": {"momentum": 0.25, "mean_reversion": 0.30, "volume": 0.20, "sentiment": 0.25},
        "buy_threshold": 0.30,
        "sell_threshold": -0.25,
        "risk_level": "low",
    },
    "aggressive": {
        "name": "공격적 단타",
        "name_en": "Aggressive Short-Term",
        "description": "짧은 홀딩, 빈번한 매매. 높은 수익 + 높은 리스크.",
        "weights": {"momentum": 0.40, "mean_reversion": 0.10, "volume": 0.35, "sentiment": 0.15},
        "buy_threshold": 0.10,
        "sell_threshold": -0.08,
        "risk_level": "very_high",
    },
    "custom": {
        "name": "사용자 정의",
        "name_en": "Custom",
        "description": "직접 가중치와 임계값을 설정합니다.",
        "weights": {"momentum": 0.25, "mean_reversion": 0.25, "volume": 0.25, "sentiment": 0.25},
        "buy_threshold": 0.15,
        "sell_threshold": -0.15,
        "risk_level": "custom",
    },
}


def get_preset(name: str) -> dict | None:
    return STRATEGY_PRESETS.get(name)


def list_presets() -> list[dict]:
    return [{"key": k, **v} for k, v in STRATEGY_PRESETS.items()]
