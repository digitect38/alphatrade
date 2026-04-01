"""Tests for Telegram LLM trading assistant."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.telegram_bot import TelegramAssistant, COMMAND_HELP


class MockConn:
    def __init__(self, fetchrow_data=None, fetch_data=None):
        self._fetchrow = fetchrow_data
        self._fetch = fetch_data or []

    async def fetchrow(self, query, *args):
        return self._fetchrow

    async def fetch(self, query, *args):
        return self._fetch


class MockPool:
    def __init__(self, conn=None):
        self._conn = conn or MockConn()

    def acquire(self):
        return MockAcquire(self._conn)


class MockAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


class MockRedis:
    def __init__(self, store=None):
        self._store = store or {}

    async def get(self, key):
        return self._store.get(key)


@pytest.fixture
def assistant():
    pool = MockPool(MockConn(
        fetchrow_data={
            "total_value": Decimal("10000000"), "cash": Decimal("5000000"),
            "invested": Decimal("5000000"), "daily_pnl": Decimal("50000"),
            "daily_return": Decimal("0.005"), "cumulative_return": Decimal("0.03"),
            "positions_count": 3,
        },
        fetch_data=[],
    ))
    redis = MockRedis()
    return TelegramAssistant(pool=pool, redis=redis)


@pytest.mark.asyncio
async def test_unauthorized_chat(assistant):
    """Messages from unauthorized chats are ignored."""
    msg = {"chat": {"id": 999999}, "text": "hello"}
    with patch("app.services.telegram_bot.settings") as s:
        s.telegram_chat_id = "12345"
        s.telegram_bot_token = "token"
        s.anthropic_api_key = ""
        result = await assistant.handle_message(msg)
    assert result is None


@pytest.mark.asyncio
async def test_help_command(assistant):
    """Help command returns command list."""
    msg = {"chat": {"id": 12345}, "text": "/help"}
    with patch("app.services.telegram_bot.settings") as s:
        s.telegram_chat_id = "12345"
        s.telegram_bot_token = "token"
        result = await assistant.handle_message(msg)
    assert "명령어" in result
    assert "/status" in result


@pytest.mark.asyncio
async def test_start_command(assistant):
    """/start returns help."""
    msg = {"chat": {"id": 12345}, "text": "/start"}
    with patch("app.services.telegram_bot.settings") as s:
        s.telegram_chat_id = "12345"
        s.telegram_bot_token = "token"
        result = await assistant.handle_message(msg)
    assert result == COMMAND_HELP


@pytest.mark.asyncio
async def test_status_command(assistant):
    """/status returns portfolio info."""
    msg = {"chat": {"id": 12345}, "text": "/status"}
    with patch("app.services.telegram_bot.settings") as s:
        s.telegram_chat_id = "12345"
        s.telegram_bot_token = "token"
        result = await assistant.handle_message(msg)
    assert "포트폴리오" in result
    assert "10,000,000" in result


@pytest.mark.asyncio
async def test_kill_command(assistant):
    """/kill returns kill switch status."""
    msg = {"chat": {"id": 12345}, "text": "/kill"}
    with patch("app.services.telegram_bot.settings") as s:
        s.telegram_chat_id = "12345"
        s.telegram_bot_token = "token"
        s.risk_broker_max_failures = 3
        result = await assistant.handle_message(msg)
    assert "킬 스위치" in result


@pytest.mark.asyncio
async def test_unknown_command(assistant):
    """Unknown command returns hint."""
    msg = {"chat": {"id": 12345}, "text": "/foo"}
    with patch("app.services.telegram_bot.settings") as s:
        s.telegram_chat_id = "12345"
        s.telegram_bot_token = "token"
        result = await assistant.handle_message(msg)
    assert "/help" in result


@pytest.mark.asyncio
async def test_empty_message(assistant):
    """Empty message returns None."""
    msg = {"chat": {"id": 12345}, "text": ""}
    result = await assistant.handle_message(msg)
    assert result is None


@pytest.mark.asyncio
async def test_llm_no_api_key(assistant):
    """Free-form question without API key returns error."""
    msg = {"chat": {"id": 12345}, "text": "삼성전자 지금 사도 될까?"}
    with patch("app.services.telegram_bot.settings") as s:
        s.telegram_chat_id = "12345"
        s.telegram_bot_token = "token"
        s.anthropic_api_key = ""
        s.openai_api_key = ""
        s.core_engine_port = 8000
        result = await assistant.handle_message(msg)
    assert "API 키" in result
