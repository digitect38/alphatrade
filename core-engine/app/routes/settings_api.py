"""Runtime Settings API — Manage configurable settings from the dashboard.

Stores settings in a `runtime_settings` table (auto-created if missing).
Secret values (API keys) are masked in GET responses.
"""

import logging

import asyncpg
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.deps import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

SECRET_KEYS = {"anthropic_api_key", "openai_api_key", "telegram_bot_token"}

# Default settings structure — defines all configurable keys
SETTINGS_SCHEMA: dict[str, dict] = {
    "llm_provider": {"label": "LLM Provider", "type": "select", "options": ["anthropic", "openai"], "default": "anthropic", "group": "llm"},
    "anthropic_api_key": {"label": "Anthropic API Key", "type": "secret", "default": "", "group": "llm"},
    "anthropic_model": {"label": "Anthropic Model", "type": "select", "options": [
        "claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001",
        "claude-sonnet-4-5-20241022", "claude-opus-4-0-20250514",
    ], "default": "claude-opus-4-6", "group": "llm"},
    "openai_api_key": {"label": "OpenAI API Key", "type": "secret", "default": "", "group": "llm"},
    "openai_model": {"label": "OpenAI Model", "type": "select", "options": [
        "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini",
    ], "default": "gpt-5.4", "group": "llm"},
    "telegram_bot_token": {"label": "Telegram Bot Token", "type": "secret", "default": "", "group": "telegram"},
    "telegram_chat_id": {"label": "Telegram Chat ID", "type": "text", "default": "", "group": "telegram"},
}


def mask_secret(value: str) -> str:
    if not value or len(value) < 8:
        return "••••" if value else ""
    return value[:4] + "•" * (len(value) - 8) + value[-4:]


async def ensure_table(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS runtime_settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)


# --- Endpoints ---

@router.get("")
async def api_get_settings(pool: asyncpg.Pool = Depends(get_db)):
    """Get all runtime settings (secrets masked)."""
    await ensure_table(pool)
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, value FROM runtime_settings")
    db_values = {r["key"]: r["value"] for r in rows}

    result = {}
    for key, schema in SETTINGS_SCHEMA.items():
        value = db_values.get(key, schema["default"])
        result[key] = {
            **schema,
            "value": mask_secret(value) if key in SECRET_KEYS else value,
            "is_set": bool(db_values.get(key)),
        }
    return {"settings": result}


class SettingsUpdate(BaseModel):
    settings: dict[str, str]


@router.put("")
async def api_put_settings(
    body: SettingsUpdate,
    pool: asyncpg.Pool = Depends(get_db),
):
    """Update runtime settings. Only updates keys present in the request."""
    await ensure_table(pool)
    updated = []
    async with pool.acquire() as conn:
        for key, value in body.settings.items():
            if key not in SETTINGS_SCHEMA:
                continue
            # Skip masked values (user didn't change the secret)
            if key in SECRET_KEYS and "••••" in value:
                continue
            await conn.execute(
                """INSERT INTO runtime_settings (key, value, updated_at)
                   VALUES ($1, $2, NOW())
                   ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()""",
                key, value,
            )
            updated.append(key)
    logger.info("Settings updated: %s", updated)
    return {"ok": True, "updated": updated}


@router.get("/schema")
async def api_settings_schema():
    """Get the settings schema (for building the UI form)."""
    return {"schema": SETTINGS_SCHEMA}


@router.get("/llm-models")
async def api_llm_models():
    """Get available LLM models for each provider.

    This endpoint can be extended to fetch models dynamically from provider APIs.
    For now returns a curated list of latest models.
    """
    return {
        "anthropic": [
            {"id": "claude-opus-4-6", "name": "Claude Opus 4.6", "tier": "flagship", "context": "1M"},
            {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6", "tier": "balanced", "context": "200K"},
            {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "tier": "fast", "context": "200K"},
            {"id": "claude-sonnet-4-5-20241022", "name": "Claude Sonnet 4.5", "tier": "legacy", "context": "200K"},
            {"id": "claude-opus-4-0-20250514", "name": "Claude Opus 4.0", "tier": "legacy", "context": "200K"},
        ],
        "openai": [
            {"id": "gpt-5.4", "name": "GPT-5.4", "tier": "flagship", "context": "1.05M", "api": "responses"},
            {"id": "gpt-5.4-mini", "name": "GPT-5.4 Mini", "tier": "balanced", "context": "1.05M", "api": "responses"},
            {"id": "gpt-5.4-nano", "name": "GPT-5.4 Nano", "tier": "fast", "context": "1.05M", "api": "responses"},
            {"id": "gpt-4.1", "name": "GPT-4.1", "tier": "balanced", "context": "1M", "api": "chat"},
            {"id": "gpt-4.1-mini", "name": "GPT-4.1 Mini", "tier": "fast", "context": "1M", "api": "chat"},
            {"id": "gpt-4o", "name": "GPT-4o", "tier": "legacy", "context": "128K", "api": "chat"},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "tier": "legacy", "context": "128K", "api": "chat"},
        ],
    }
