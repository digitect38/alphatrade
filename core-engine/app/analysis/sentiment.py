import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import asyncpg
import httpx

from app.config import settings
from app.models.sentiment import SentimentScore, StockSentimentResult

logger = logging.getLogger(__name__)

SENTIMENT_PROMPT = """당신은 한국 금융 시장 전문 센티먼트 분석가입니다.
아래 텍스트의 주식 시장 감성을 분석하세요.

텍스트:
{text}

다음 JSON 형식으로만 응답하세요:
{{"score": <-1.0~1.0 float>, "confidence": <0.0~1.0 float>, "reasoning": "<한 문장 근거>"}}

score 기준:
- 1.0: 매우 긍정 (실적 대폭 개선, 대형 계약 등)
- 0.5: 긍정
- 0.0: 중립
- -0.5: 부정
- -1.0: 매우 부정 (적자 전환, 상장폐지 등)"""


async def analyze_text_sentiment(text: str, model: str = "claude") -> SentimentScore:
    """Analyze sentiment of financial text using LLM API."""
    if not text.strip():
        return SentimentScore(score=0.0, confidence=0.0, reasoning="Empty text", model=model)

    try:
        if model == "claude" and settings.anthropic_api_key:
            return await _call_claude(text)
        elif model == "openai" and settings.openai_api_key:
            return await _call_openai(text)
        else:
            # Fallback: keyword-based simple analysis
            return _keyword_sentiment(text, model="keyword_fallback")
    except Exception as e:
        logger.error("Sentiment analysis failed: %s", e)
        return _keyword_sentiment(text, model="keyword_fallback")


async def _call_claude(text: str) -> SentimentScore:
    """Call Anthropic Claude API for sentiment analysis."""
    from app.utils.retry import retry_async
    async with httpx.AsyncClient(timeout=settings.http_timeout_llm) as client:
        resp = await retry_async(client.post,
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 200,
                "messages": [{"role": "user", "content": SENTIMENT_PROMPT.format(text=text[:2000])}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["content"][0]["text"]

        # Parse JSON from response
        result = json.loads(content)
        return SentimentScore(
            score=max(-1.0, min(1.0, float(result["score"]))),
            confidence=max(0.0, min(1.0, float(result.get("confidence", 0.7)))),
            reasoning=result.get("reasoning", ""),
            model="claude",
        )


async def _call_openai(text: str) -> SentimentScore:
    """Call OpenAI API for sentiment analysis."""
    from app.utils.retry import retry_async
    async with httpx.AsyncClient(timeout=settings.http_timeout_llm) as client:
        resp = await retry_async(client.post,
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": SENTIMENT_PROMPT.format(text=text[:2000])}],
                "max_tokens": 200,
                "temperature": 0.1,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]

        result = json.loads(content)
        return SentimentScore(
            score=max(-1.0, min(1.0, float(result["score"]))),
            confidence=max(0.0, min(1.0, float(result.get("confidence", 0.7)))),
            reasoning=result.get("reasoning", ""),
            model="openai",
        )


def _keyword_sentiment(text: str, model: str = "keyword_fallback") -> SentimentScore:
    """Simple keyword-based sentiment as fallback when no LLM API key is configured."""
    positive_words = [
        "상승", "급등", "호재", "흑자", "성장", "개선", "돌파", "최고", "수주",
        "계약", "신고가", "배당", "증가", "호실적", "매출", "영업이익", "순이익",
        "슈퍼사이클", "상향", "확대", "투자", "인수",
    ]
    negative_words = [
        "하락", "급락", "악재", "적자", "감소", "하향", "폐지", "부도", "손실",
        "매도", "공매도", "최저", "감자", "워크아웃", "회생", "리콜", "분쟁",
        "소송", "제재", "과징금", "불공정",
    ]

    pos_count = sum(1 for w in positive_words if w in text)
    neg_count = sum(1 for w in negative_words if w in text)
    total = pos_count + neg_count

    if total == 0:
        return SentimentScore(score=0.0, confidence=0.2, reasoning="키워드 매칭 없음", model=model)

    score = (pos_count - neg_count) / total
    confidence = min(total / 5, 1.0) * 0.5  # Max 0.5 for keyword method

    reasoning = f"긍정 {pos_count}개, 부정 {neg_count}개 키워드 탐지"
    return SentimentScore(score=round(score, 4), confidence=round(confidence, 4), reasoning=reasoning, model=model)


async def analyze_stock_sentiment(stock_code: str, days: int = 7, *, pool: asyncpg.Pool) -> StockSentimentResult:
    """Aggregate sentiment for a stock from news and disclosures."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    # Get existing sentiment scores from DB
    async with pool.acquire() as conn:
        scores = await conn.fetch(
            """
            SELECT score, confidence, model, source_type
            FROM sentiment_scores
            WHERE stock_code = $1 AND time >= $2
            ORDER BY time DESC
            """,
            stock_code,
            since,
        )

        # Get unprocessed news for this stock
        unprocessed = await conn.fetch(
            """
            SELECT title, content, url
            FROM news
            WHERE $1 = ANY(stock_codes) AND is_processed = FALSE AND time >= $2
            ORDER BY time DESC
            LIMIT 10
            """,
            stock_code,
            since,
        )

    # Analyze unprocessed news
    new_sentiments = []
    for row in unprocessed:
        text = f"{row['title']}. {row['content'] or ''}"
        result = await analyze_text_sentiment(text)
        new_sentiments.append(result)

        # Store in DB
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO sentiment_scores (time, stock_code, source_type, score, confidence, model, raw_text_id)
                    VALUES ($1, $2, 'news', $3, $4, $5, $6)
                    """,
                    now,
                    stock_code,
                    Decimal(str(result.score)),
                    Decimal(str(result.confidence)),
                    result.model,
                    row["url"],
                )
                await conn.execute(
                    "UPDATE news SET is_processed = TRUE WHERE url = $1",
                    row["url"],
                )
        except Exception as e:
            logger.error("Failed to store sentiment: %s", e)

    # Aggregate all scores
    all_scores = [
        SentimentScore(
            score=float(r["score"]),
            confidence=float(r["confidence"]) if r["confidence"] else 0.5,
            model=r["model"] or "unknown",
        )
        for r in scores
    ] + new_sentiments

    if not all_scores:
        return StockSentimentResult(
            stock_code=stock_code,
            overall_score=0.0,
            article_count=0,
            computed_at=now,
        )

    # Weighted average by confidence
    total_weight = sum(s.confidence for s in all_scores) or 1.0
    weighted_score = sum(s.score * s.confidence for s in all_scores) / total_weight

    # Separate news vs disclosure scores
    news_scores = [float(r["score"]) for r in scores if r["source_type"] == "news"]
    disc_scores = [float(r["score"]) for r in scores if r["source_type"] == "disclosure"]

    return StockSentimentResult(
        stock_code=stock_code,
        overall_score=round(weighted_score, 4),
        news_score=round(sum(news_scores) / len(news_scores), 4) if news_scores else None,
        disclosure_score=round(sum(disc_scores) / len(disc_scores), 4) if disc_scores else None,
        article_count=len(all_scores),
        recent_sentiments=all_scores[:10],
        computed_at=now,
    )
