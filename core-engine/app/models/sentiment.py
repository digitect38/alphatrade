from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# --- Sentiment ---


class SentimentScore(BaseModel):
    score: float  # -1.0 ~ 1.0
    confidence: float = 0.0
    reasoning: str = ""
    model: str = "unknown"


class TextSentimentRequest(BaseModel):
    text: str
    model: str = "claude"  # claude | openai


class StockSentimentRequest(BaseModel):
    stock_code: str
    days: int = 7


class StockSentimentResult(BaseModel):
    stock_code: str
    overall_score: float = 0.0
    news_score: float | None = None
    disclosure_score: float | None = None
    article_count: int = 0
    recent_sentiments: list[SentimentScore] = []
    computed_at: datetime


# --- Correlation ---


class CorrelationRequest(BaseModel):
    stock_codes: list[str]  # 2개 이상
    period: int = 60
    method: Literal["pearson", "spearman"] = "pearson"


class CorrelationPair(BaseModel):
    stock_a: str
    stock_b: str
    correlation: float


class CorrelationResult(BaseModel):
    matrix: dict[str, dict[str, float]]  # {code: {code: corr}}
    high_pairs: list[CorrelationPair] = []  # corr > 0.7
    low_pairs: list[CorrelationPair] = []  # corr < -0.3
    computed_at: datetime


# --- Causality ---


class CausalityRequest(BaseModel):
    stock_a: str
    stock_b: str
    max_lag: int = 5


class CausalityResult(BaseModel):
    stock_a: str
    stock_b: str
    a_causes_b: bool = False
    b_causes_a: bool = False
    a_to_b_pvalue: float = 1.0
    b_to_a_pvalue: float = 1.0
    optimal_lag: int = 1
    computed_at: datetime
