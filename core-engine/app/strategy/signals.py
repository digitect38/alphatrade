"""Individual strategy signal generators.

Each function takes analysis results and returns a score from -1.0 to 1.0.
Positive = bullish, Negative = bearish, 0 = neutral.
"""

from app.models.analysis import TechnicalResult, VolumeResult
from app.models.sentiment import StockSentimentResult


def momentum_signal(technical: TechnicalResult) -> float:
    """Trend-following momentum strategy.
    Buy when price is above moving averages and momentum is positive.
    """
    score = 0.0
    count = 0

    ind = technical.indicators

    # Price vs SMA trend alignment
    if ind.sma_20 and technical.current_price:
        count += 1
        score += 0.5 if technical.current_price > ind.sma_20 else -0.5

    if ind.sma_60 and technical.current_price:
        count += 1
        score += 0.5 if technical.current_price > ind.sma_60 else -0.5

    # MACD momentum
    if ind.macd_hist is not None:
        count += 1
        if ind.macd_hist > 0:
            score += 0.6
        else:
            score -= 0.6

    # RSI momentum (not reversal)
    if ind.rsi_14 is not None:
        count += 1
        if 50 < ind.rsi_14 < 70:
            score += 0.4  # healthy uptrend
        elif 30 < ind.rsi_14 <= 50:
            score -= 0.3  # weakening
        elif ind.rsi_14 >= 70:
            score += 0.2  # strong but risky
        else:
            score -= 0.5  # weak

    # ROC (Rate of Change)
    if ind.roc_12 is not None:
        count += 1
        if ind.roc_12 > 5:
            score += 0.5
        elif ind.roc_12 > 0:
            score += 0.2
        elif ind.roc_12 > -5:
            score -= 0.2
        else:
            score -= 0.5

    return round(score / max(count, 1), 4)


def mean_reversion_signal(technical: TechnicalResult) -> float:
    """Mean reversion strategy.
    Buy when oversold, sell when overbought.
    """
    score = 0.0
    count = 0

    ind = technical.indicators

    # RSI reversal
    if ind.rsi_14 is not None:
        count += 1
        if ind.rsi_14 < 30:
            score += 0.8  # oversold → buy
        elif ind.rsi_14 > 70:
            score -= 0.8  # overbought → sell
        elif ind.rsi_14 < 40:
            score += 0.3
        elif ind.rsi_14 > 60:
            score -= 0.3

    # Bollinger Band position
    if ind.bb_upper and ind.bb_lower and technical.current_price:
        count += 1
        bb_range = ind.bb_upper - ind.bb_lower
        if bb_range > 0:
            position = (technical.current_price - ind.bb_lower) / bb_range
            if position < 0.2:
                score += 0.7  # near lower band
            elif position > 0.8:
                score -= 0.7  # near upper band
            else:
                score += (0.5 - position) * 0.4  # linear scale

    # Stochastic
    if ind.stoch_k is not None and ind.stoch_d is not None:
        count += 1
        if ind.stoch_k < 20:
            score += 0.6
        elif ind.stoch_k > 80:
            score -= 0.6

    # Williams %R
    if ind.willr_14 is not None:
        count += 1
        if ind.willr_14 < -80:
            score += 0.5  # oversold
        elif ind.willr_14 > -20:
            score -= 0.5  # overbought

    return round(score / max(count, 1), 4)


def volume_signal(volume: VolumeResult) -> float:
    """Volume-based strategy signal."""
    score = 0.0

    # Volume surge with OBV confirmation
    if volume.is_surge and volume.obv_trend == "increasing":
        score += 0.7  # strong buying pressure
    elif volume.is_surge and volume.obv_trend == "decreasing":
        score -= 0.5  # distribution

    # Price-volume divergence
    if volume.price_volume_divergence == "bullish":
        score += 0.4
    elif volume.price_volume_divergence == "bearish":
        score -= 0.4

    # Volume trend
    if volume.volume_trend == "increasing":
        score += 0.2
    elif volume.volume_trend == "decreasing":
        score -= 0.1

    return round(max(-1.0, min(1.0, score)), 4)


def sentiment_signal(sentiment: StockSentimentResult | None) -> float:
    """Sentiment-based strategy signal."""
    if not sentiment or sentiment.article_count == 0:
        return 0.0

    # Direct mapping of overall sentiment score
    # Dampened by confidence (article count)
    confidence = min(sentiment.article_count / 5, 1.0)
    score = sentiment.overall_score * confidence

    return round(max(-1.0, min(1.0, score)), 4)
