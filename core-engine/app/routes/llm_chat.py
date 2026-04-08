"""LLM Chat API — Thin route layer.

Business logic is in:
  app/services/llm_models.py    — Pydantic models, system prompt
  app/services/llm_context.py   — Context building, RAG retrieval
  app/services/llm_tools.py     — Tool execution engine
  app/services/llm_callers.py   — OpenAI/Anthropic/Ollama API callers
"""

import json
import logging
import re
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends

from app.config import settings
from app.deps import get_db, get_redis
from app.services.llm_models import SYSTEM_PROMPT, TOOL_PATTERN, ChatRequest, ChatResponse
from app.services.llm_context import build_context
from app.services.llm_tools import execute_tools
from app.services.llm_callers import call_openai, call_claude, call_ollama, _build_vision_content

logger = logging.getLogger(__name__)

router = APIRouter()


# --- History (Redis + DB) ---

async def _get_history(redis: aioredis.Redis, session_id: str, limit: int = 20) -> list[dict]:
    key = f"llm:chat:{session_id}"
    raw = await redis.lrange(key, 0, limit - 1)
    return [json.loads(m) for m in reversed(raw)]


async def _append_history(redis: aioredis.Redis, session_id: str, role: str, content: str):
    key = f"llm:chat:{session_id}"
    msg = json.dumps({"role": role, "content": content, "ts": datetime.now(timezone.utc).isoformat()})
    await redis.rpush(key, msg)
    await redis.ltrim(key, -50, -1)
    await redis.expire(key, 86400 * 7)


async def _ensure_chat_table(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id SERIAL, time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                session_id TEXT NOT NULL, role TEXT NOT NULL,
                content TEXT NOT NULL, model TEXT, has_image BOOLEAN DEFAULT FALSE
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_history(session_id, time DESC)")


async def _save_to_db(pool: asyncpg.Pool, session_id: str, role: str, content: str, model: str | None = None, has_image: bool = False):
    try:
        await _ensure_chat_table(pool)
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO chat_history (session_id, role, content, model, has_image) VALUES ($1, $2, $3, $4, $5)",
                session_id, role, content[:5000], model, has_image,
            )
    except Exception as e:
        logger.debug("Chat DB save failed: %s", e)


# --- Runtime settings helpers ---

async def _get_runtime_setting(pool: asyncpg.Pool, key: str) -> str | None:
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT value FROM runtime_settings WHERE key = $1", key)
            return row["value"] if row else None
    except Exception:
        return None


async def _get_api_key(pool: asyncpg.Pool, provider: str) -> str:
    db_key = await _get_runtime_setting(pool, f"{provider}_api_key")
    if db_key:
        return db_key
    return getattr(settings, f"{provider}_api_key", "")


async def _get_model(pool: asyncpg.Pool, provider: str) -> str:
    db_model = await _get_runtime_setting(pool, f"{provider}_model")
    if db_model:
        return db_model
    defaults = {"anthropic": "claude-opus-4-6", "openai": "gpt-5.4"}
    return defaults.get(provider, "")


# --- Main chat endpoint ---

@router.post("/chat", response_model=ChatResponse)
async def api_chat(
    req: ChatRequest,
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Send a message to the AI trading assistant."""
    # Determine provider
    provider = await _get_runtime_setting(pool, "llm_provider") or ""
    anthropic_key = await _get_api_key(pool, "anthropic")
    openai_key = await _get_api_key(pool, "openai")

    if provider == "ollama":
        api_key = ""
        model = await _get_runtime_setting(pool, "ollama_model") or "exaone3.5:2.4b"
    elif provider == "anthropic" and anthropic_key:
        api_key = anthropic_key
        model = await _get_model(pool, provider)
    elif provider == "openai" and openai_key:
        api_key = openai_key
        model = await _get_model(pool, provider)
    else:
        if not provider:
            provider = "anthropic" if anthropic_key else ("openai" if openai_key else "ollama")
        if provider == "ollama" or (not anthropic_key and not openai_key):
            provider = "ollama"
            api_key = ""
            model = await _get_runtime_setting(pool, "ollama_model") or "exaone3.5:2.4b"
        else:
            api_key = anthropic_key if provider == "anthropic" else openai_key
            model = await _get_model(pool, provider)

    # Build context
    context = await build_context(req.message, pool, redis)
    system = SYSTEM_PROMPT.format(context=context)

    # History
    history = await _get_history(redis, req.session_id)
    await _append_history(redis, req.session_id, "user", req.message)
    await _save_to_db(pool, req.session_id, "user", req.message, has_image=bool(req.image))

    # Build messages
    api_messages = [{"role": h["role"], "content": h["content"]} for h in history[-10:]]
    if req.image:
        user_content = _build_vision_content(req.message, req.image, provider)
    else:
        user_content = req.message
    api_messages.append({"role": "user", "content": user_content})

    # Call LLM
    try:
        if provider == "ollama":
            reply = await call_ollama(api_messages, system, model)
        elif provider == "anthropic":
            reply = await call_claude(api_messages, system, api_key, model)
        else:
            reply = await call_openai(api_messages, system, api_key, model)

        # Tool execution (2-pass)
        tool_matches = re.findall(TOOL_PATTERN, reply)
        if tool_matches:
            tool_results = await execute_tools(tool_matches, pool, redis)
            clean_reply = re.sub(TOOL_PATTERN, '', reply).strip()
            tool_context = "\n".join(f"[도구 결과: {name}]\n{result}" for name, result in tool_results)
            followup_messages = api_messages + [
                {"role": "assistant", "content": clean_reply},
                {"role": "user", "content": f"아래는 도구 실행 결과입니다. 이 데이터를 분석하여 사용자에게 답변하세요.\n\n{tool_context}"},
            ]
            if provider == "ollama":
                reply = await call_ollama(followup_messages, system, model)
            elif provider == "anthropic":
                reply = await call_claude(followup_messages, system, api_key, model)
            else:
                reply = await call_openai(followup_messages, system, api_key, model)

    except Exception as e:
        logger.warning("Cloud LLM failed (%s), trying Ollama fallback...", e)
        try:
            model = "exaone3.5:2.4b"
            reply = await call_ollama(api_messages, system, model)
            logger.info("Ollama fallback succeeded")
        except Exception as ollama_err:
            logger.error("Ollama fallback also failed: %s", ollama_err)
            err_str = str(e)
            if "429" in err_str or "insufficient_quota" in err_str:
                reply = "클라우드 API 한도 초과. 로컬 Ollama도 실패했습니다. OpenAI 크레딧을 충전하거나 Ollama를 확인해주세요."
            else:
                reply = "AI 응답에 실패했습니다. 잠시 후 다시 시도해주세요."

    await _append_history(redis, req.session_id, "assistant", reply)
    await _save_to_db(pool, req.session_id, "assistant", reply, model=model)

    return ChatResponse(reply=reply, session_id=req.session_id, model=model, context_summary=context)


@router.get("/history")
async def api_history(session_id: str = "default", redis: aioredis.Redis = Depends(get_redis)):
    history = await _get_history(redis, session_id, limit=50)
    return {"session_id": session_id, "messages": history}


@router.delete("/history")
async def api_clear_history(session_id: str = "default", redis: aioredis.Redis = Depends(get_redis)):
    await redis.delete(f"llm:chat:{session_id}")
    return {"ok": True}


@router.get("/history/all")
async def api_all_history(limit: int = 100, pool: asyncpg.Pool = Depends(get_db)):
    try:
        await _ensure_chat_table(pool)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT time, session_id, role, content, model, has_image "
                "FROM chat_history ORDER BY time DESC LIMIT $1", limit,
            )
        return {
            "count": len(rows),
            "messages": [
                {"time": r["time"].isoformat(), "session_id": r["session_id"], "role": r["role"],
                 "content": r["content"][:500], "model": r["model"], "has_image": r["has_image"]}
                for r in reversed(rows)
            ],
        }
    except Exception:
        return {"count": 0, "messages": []}
