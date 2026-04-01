"""Market event collector — uses OpenAI to identify and classify major events.

Periodically asks LLM to identify recent political, economic, and social events
that could impact the Korean stock market. Stores in market_events table.

Also seeds historical events on first run.
"""

import json
import logging
from datetime import datetime, timezone

import asyncpg
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

COLLECTION_PROMPT = """당신은 한국 및 글로벌 금융시장에 영향을 미치는 주요 사건을 추적하는 전문가입니다.

현재 날짜: {today}

최근 {period}간 발생한 주요 정치/경제/사회적 사건을 JSON 배열로 반환하세요.
한국 주식시장(KOSPI/KOSDAQ)에 영향을 줄 수 있는 사건만 포함합니다.

각 사건 형식:
{{
  "date": "YYYY-MM-DD",
  "label": "짧은 제목 (8자 이내)",
  "category": "policy|geopolitics|economy|market|disaster",
  "description": "1-2문장 설명",
  "importance": 1-5 (5=매우 중요),
  "url": "관련 뉴스 URL (없으면 빈 문자열)"
}}

카테고리 기준:
- policy: 금리, 통화정책, 규제, 관세
- geopolitics: 전쟁, 외교, 선거, 제재
- economy: 기업 실적, 파산, 환율, 고용
- market: 증시 급등락, 서킷브레이커, IPO
- disaster: 자연재해, 전염병, 사고

중요도 기준:
- 5: 글로벌 증시 5% 이상 영향 (전쟁, 금융위기)
- 4: KOSPI 2% 이상 영향 (금리 변경, 대형 지정학)
- 3: 섹터 영향 (산업 규제, 기업 이슈)
- 2: 단기 영향 (선거 결과, 단발 이슈)
- 1: 참고 사항

이미 알려진 사건도 빠짐없이 포함하세요.
JSON 배열만 반환하세요. 설명 텍스트 없이."""

SEED_PROMPT = """당신은 한국 및 글로벌 금융시장 역사 전문가입니다.

{start_year}년부터 {end_year}년까지 한국 주식시장에 큰 영향을 미친 주요 정치/경제/사회적 사건을
JSON 배열로 반환하세요. 연도별로 최소 2-3개, 최대 5개 사건을 포함하세요.

특히 다음을 반드시 포함:
- 전쟁 (한국전쟁, 걸프전, 이라크전, 러시아-우크라이나, 이스라엘-하마스, 미국-이란 등)
- 금융위기 (IMF, 리먼, 유럽재정위기, FTX 등)
- 정치 변동 (탄핵, 계엄, 대선, 트럼프 관세 등)
- 팬데믹/재난 (SARS, 코로나, 지진 등)
- 중앙은행 정책 (금리 변경, QE 등)
- 최근 2025-2026년 이벤트 (미국-이란 긴장, 트럼프 상호관세, 한국 대선 등)

각 사건 형식:
{{
  "date": "YYYY-MM-DD",
  "label": "짧은 제목 (8자 이내)",
  "category": "policy|geopolitics|economy|market|disaster",
  "description": "1-2문장 설명",
  "importance": 1-5,
  "url": ""
}}

JSON 배열만 반환하세요."""


async def collect_recent_events(
    *,
    pool: asyncpg.Pool,
    period: str = "1개월",
) -> dict:
    """Collect recent market events using OpenAI API.

    Returns summary of inserted/skipped events.
    """
    if not settings.openai_api_key:
        return {"error": "OPENAI_API_KEY not configured"}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = COLLECTION_PROMPT.format(today=today, period=period)

    events = await _call_openai(prompt)
    if not events:
        return {"status": "no_events", "inserted": 0}

    return await _store_events(pool, events, source="openai")


async def seed_historical_events(
    *,
    pool: asyncpg.Pool,
    start_year: int = 1997,
    end_year: int = 2026,
) -> dict:
    """Seed historical events using OpenAI API.

    Should be called once to populate the database with major historical events.
    """
    if not settings.openai_api_key:
        return {"error": "OPENAI_API_KEY not configured"}

    prompt = SEED_PROMPT.format(start_year=start_year, end_year=end_year)
    events = await _call_openai(prompt)
    if not events:
        return {"status": "no_events", "inserted": 0}

    return await _store_events(pool, events, source="seed")


async def _call_openai(prompt: str) -> list[dict]:
    """Call OpenAI API and parse JSON response."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "max_tokens": 4000,
                    "temperature": 0.3,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            # Parse JSON from response (handle markdown code blocks)
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            events = json.loads(content)
            if not isinstance(events, list):
                events = [events]

            logger.info("OpenAI returned %d events", len(events))
            return events

    except Exception as e:
        logger.error("OpenAI event collection failed: %s", e)
        return []


async def _store_events(pool: asyncpg.Pool, events: list[dict], source: str) -> dict:
    """Store events in database, skipping duplicates."""
    inserted = 0
    skipped = 0
    errors = []

    async with pool.acquire() as conn:
        for evt in events:
            try:
                date_str = evt.get("date", "")
                label = evt.get("label", "")
                category = evt.get("category", "economy")
                description = evt.get("description", "")
                importance = min(5, max(1, int(evt.get("importance", 3))))
                url = evt.get("url", "")

                if not date_str or not label:
                    continue

                # Parse date string to date object
                from datetime import date as _date_type
                try:
                    date = _date_type.fromisoformat(date_str)
                except ValueError:
                    errors.append(f"Invalid date: {date_str} {label}")
                    continue

                # Validate category
                if category not in ("policy", "geopolitics", "economy", "market", "disaster"):
                    category = "economy"

                result = await conn.execute(
                    """INSERT INTO market_events (date, label, category, description, importance, url, source)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (date, label) DO UPDATE SET
                        description = EXCLUDED.description,
                        importance = GREATEST(market_events.importance, EXCLUDED.importance),
                        url = CASE WHEN EXCLUDED.url != '' THEN EXCLUDED.url ELSE market_events.url END
                    """,
                    date, label, category, description, importance, url, source,
                )
                if "INSERT" in result:
                    inserted += 1
                else:
                    skipped += 1

            except Exception as e:
                errors.append(f"{evt.get('date', '?')} {evt.get('label', '?')}: {e}")

    logger.info("Events stored: inserted=%d skipped=%d errors=%d", inserted, skipped, len(errors))
    return {
        "status": "ok",
        "inserted": inserted,
        "skipped": skipped,
        "total_received": len(events),
        "errors": errors[:5],
    }


async def get_events_for_range(
    *,
    pool: asyncpg.Pool,
    start_date: str,
    end_date: str,
    min_importance: int = 1,
) -> list[dict]:
    """Get events from DB for a date range."""
    from datetime import date as _date_type
    sd = _date_type.fromisoformat(start_date) if isinstance(start_date, str) else start_date
    ed = _date_type.fromisoformat(end_date) if isinstance(end_date, str) else end_date

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT date, label, category, description, url, importance
            FROM market_events
            WHERE date >= $1 AND date <= $2 AND importance >= $3
            ORDER BY date ASC""",
            sd, ed, min_importance,
        )

    return [
        {
            "date": str(r["date"]),
            "label": r["label"],
            "category": r["category"],
            "description": r["description"],
            "url": r["url"] or "",
            "importance": r["importance"],
        }
        for r in rows
    ]
