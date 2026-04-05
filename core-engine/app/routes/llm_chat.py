"""LLM Chat API — Direct chat with AI trading assistant.

Provides the same trading-context-aware assistant as the Telegram bot,
but via REST API for the dashboard UI.
"""

import logging
from datetime import datetime, timezone

import asyncpg
import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import settings
from app.deps import get_db, get_redis

logger = logging.getLogger(__name__)

router = APIRouter()

SYSTEM_PROMPT = """당신은 AlphaTrade AI 트레이딩 어시스턴트입니다.
한국 주식시장(KOSPI/KOSDAQ) 자동매매 시스템의 운영을 돕습니다.

역할:
- 종목 분석 질문에 실시간 데이터 기반으로 답변
- 매매 판단 보조 (최종 결정은 사용자 몫임을 명시)
- 포트폴리오 현황/리스크 설명
- 시스템 운영 질문 안내

규칙:
- 한국어로 답변 (영어 질문에는 영어로)
- 숫자는 구체적으로
- 불확실한 정보는 "확인 필요"라고 답변
- 투자 권유가 아닌 정보 제공임을 인지
- 마크다운 포맷 사용 가능

현재 시스템 상태:
{context}"""


# --- Models ---

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str
    timestamp: str


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    model: str
    context_summary: str


# --- Context builder ---

async def build_context(question: str, pool: asyncpg.Pool, redis: aioredis.Redis) -> str:
    parts = []
    try:
        async with pool.acquire() as conn:
            snap = await conn.fetchrow(
                "SELECT total_value, cash, daily_pnl, positions_count "
                "FROM portfolio_snapshots ORDER BY time DESC LIMIT 1"
            )
        if snap:
            parts.append(
                f"포트폴리오: 총 {float(snap['total_value']):,.0f}원, "
                f"현금 {float(snap['cash']):,.0f}원, "
                f"일간 {float(snap['daily_pnl'] or 0):+,.0f}원, "
                f"{snap['positions_count']}종목"
            )
    except Exception:
        pass

    try:
        ks = await redis.get("trading:kill_switch")
        parts.append(f"킬스위치: {'활성' if ks in ('active', b'active') else '비활성'}")
    except Exception:
        pass

    try:
        mode = await redis.get("trading:mode")
        if mode:
            parts.append(f"트레이딩 모드: {mode.decode() if isinstance(mode, bytes) else mode}")
    except Exception:
        pass

    # Extract stock codes from question
    import re
    code_match = re.search(r'\b(\d{6})\b', question)
    if code_match:
        code = code_match.group(1)
        try:
            async with pool.acquire() as conn:
                sig = await conn.fetchrow(
                    "SELECT signal, strength FROM strategy_signals "
                    "WHERE stock_code = $1 ORDER BY time DESC LIMIT 1", code
                )
                price = await conn.fetchrow(
                    "SELECT close FROM ohlcv WHERE stock_code = $1 AND interval = '1d' "
                    "ORDER BY time DESC LIMIT 1", code
                )
                name = await conn.fetchrow(
                    "SELECT stock_name FROM stocks WHERE stock_code = $1", code
                )
            if name:
                parts.append(f"{code} ({name['stock_name']})")
            if sig:
                parts.append(f"  시그널: {sig['signal']} (강도 {float(sig['strength']):.2f})")
            if price:
                parts.append(f"  현재가: {float(price['close']):,.0f}원")
        except Exception:
            pass

    from app.utils.market_calendar import KST
    parts.append(f"현재시각: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    return "\n".join(parts) if parts else "컨텍스트 없음"


# --- Chat history (Redis-backed, per session) ---

async def get_history(redis: aioredis.Redis, session_id: str, limit: int = 20) -> list[dict]:
    import json
    key = f"llm:chat:{session_id}"
    raw = await redis.lrange(key, 0, limit - 1)
    return [json.loads(m) for m in reversed(raw)]


async def append_history(redis: aioredis.Redis, session_id: str, role: str, content: str):
    import json
    key = f"llm:chat:{session_id}"
    msg = json.dumps({"role": role, "content": content, "ts": datetime.now(timezone.utc).isoformat()})
    await redis.rpush(key, msg)
    await redis.ltrim(key, -50, -1)  # keep last 50 messages
    await redis.expire(key, 86400 * 7)  # 7 day TTL


# --- Runtime settings helpers ---

async def get_runtime_setting(pool: asyncpg.Pool, key: str) -> str | None:
    """Get a runtime setting from DB, returns None if table/key doesn't exist."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM runtime_settings WHERE key = $1", key
            )
            return row["value"] if row else None
    except Exception:
        return None


async def get_api_key(pool: asyncpg.Pool, provider: str) -> str:
    """Get LLM API key: prefer runtime_settings DB, fallback to env."""
    db_key = await get_runtime_setting(pool, f"{provider}_api_key")
    if db_key:
        return db_key
    return getattr(settings, f"{provider}_api_key", "")


async def get_model(pool: asyncpg.Pool, provider: str) -> str:
    """Get model name from runtime settings or default."""
    db_model = await get_runtime_setting(pool, f"{provider}_model")
    if db_model:
        return db_model
    defaults = {"anthropic": "claude-haiku-4-5-20251001", "openai": "gpt-4o-mini"}
    return defaults.get(provider, "")


# --- LLM Callers ---

async def call_claude(messages: list[dict], system: str, api_key: str, model: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 2000,
                "system": system,
                "messages": messages,
            },
            timeout=settings.http_timeout_llm,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]


async def call_openai(messages: list[dict], system: str, api_key: str, model: str) -> str:
    async with httpx.AsyncClient() as client:
        full_messages = [{"role": "system", "content": system}] + messages
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 2000,
                "messages": full_messages,
            },
            timeout=settings.http_timeout_llm,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


# --- Endpoints ---

@router.post("/chat", response_model=ChatResponse)
async def api_chat(
    req: ChatRequest,
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Send a message to the AI trading assistant."""
    # Determine provider
    provider = await get_runtime_setting(pool, "llm_provider") or ""
    anthropic_key = await get_api_key(pool, "anthropic")
    openai_key = await get_api_key(pool, "openai")

    if not provider:
        provider = "anthropic" if anthropic_key else ("openai" if openai_key else "")
    if not provider or (provider == "anthropic" and not anthropic_key) or (provider == "openai" and not openai_key):
        return ChatResponse(
            reply="LLM API 키가 설정되지 않았습니다. 설정 페이지에서 API 키를 입력해주세요.",
            session_id=req.session_id,
            model="none",
            context_summary="API 키 미설정",
        )

    api_key = anthropic_key if provider == "anthropic" else openai_key
    model = await get_model(pool, provider)

    # Build context
    context = await build_context(req.message, pool, redis)
    system = SYSTEM_PROMPT.format(context=context)

    # Get history + append user message
    history = await get_history(redis, req.session_id)
    await append_history(redis, req.session_id, "user", req.message)

    # Build messages for API (include recent history)
    api_messages = []
    for h in history[-10:]:  # last 10 messages for context
        api_messages.append({"role": h["role"], "content": h["content"]})
    api_messages.append({"role": "user", "content": req.message})

    try:
        if provider == "anthropic":
            reply = await call_claude(api_messages, system, api_key, model)
        else:
            reply = await call_openai(api_messages, system, api_key, model)
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        reply = "AI 응답에 실패했습니다. 잠시 후 다시 시도해주세요."

    await append_history(redis, req.session_id, "assistant", reply)

    return ChatResponse(
        reply=reply,
        session_id=req.session_id,
        model=model,
        context_summary=context,
    )


@router.get("/history")
async def api_history(
    session_id: str = "default",
    redis: aioredis.Redis = Depends(get_redis),
):
    """Get chat history for a session."""
    history = await get_history(redis, session_id, limit=50)
    return {"session_id": session_id, "messages": history}


@router.delete("/history")
async def api_clear_history(
    session_id: str = "default",
    redis: aioredis.Redis = Depends(get_redis),
):
    """Clear chat history for a session."""
    key = f"llm:chat:{session_id}"
    await redis.delete(key)
    return {"ok": True}
