"""Dependency injection container.

All service instances are created once at startup (via lifespan in main.py)
and stored here. Routes use FastAPI Depends() to access them. Internal modules
import directly. Tests can override via app.dependency_overrides.
"""

from functools import lru_cache

import asyncpg
import redis.asyncio as aioredis
from fastapi import Request

from app.config import Settings


# --- Settings ---

@lru_cache
def get_settings() -> Settings:
    return Settings()


# --- Database & Redis ---
# These are initialized in main.py lifespan and stored in app.state

def get_db(request: Request) -> asyncpg.Pool:
    return request.app.state.db_pool


def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis_client


# --- Service accessors (from app.state) ---

def get_kis_client(request: Request):
    return request.app.state.kis_client


def get_dart_client(request: Request):
    return request.app.state.dart_client


def get_naver_client(request: Request):
    return request.app.state.naver_client


def get_notifier(request: Request):
    return request.app.state.notifier


def get_broker(request: Request):
    return request.app.state.broker_client


def get_risk_manager(request: Request):
    return request.app.state.risk_manager


def get_trading_guard(request: Request):
    from app.execution.trading_guard import TradingGuard
    return TradingGuard(pool=request.app.state.db_pool, redis=request.app.state.redis_client)
