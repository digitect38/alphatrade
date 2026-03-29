import asyncpg
import redis.asyncio as aioredis

from app.config import settings

# Global connection pool references
db_pool: asyncpg.Pool | None = None
redis_client: aioredis.Redis | None = None


async def init_db() -> asyncpg.Pool:
    global db_pool
    db_pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=2,
        max_size=10,
    )
    return db_pool


async def close_db():
    global db_pool
    if db_pool:
        await db_pool.close()
        db_pool = None


async def init_redis() -> aioredis.Redis:
    global redis_client
    redis_client = aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
        decode_responses=True,
    )
    return redis_client


async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None


def get_db() -> asyncpg.Pool:
    assert db_pool is not None, "Database pool not initialized"
    return db_pool


def get_redis() -> aioredis.Redis:
    assert redis_client is not None, "Redis client not initialized"
    return redis_client
