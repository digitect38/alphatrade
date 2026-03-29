"""Async retry utility for transient network errors."""

import asyncio
import logging
from functools import wraps

import httpx

logger = logging.getLogger(__name__)

# Errors that are safe to retry
RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    ConnectionError,
    TimeoutError,
)


async def retry_async(
    coro_func,
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    **kwargs,
):
    """Call an async function with exponential backoff on transient errors.

    Args:
        coro_func: Async function to call
        max_retries: Maximum number of attempts (default 3)
        base_delay: Initial delay in seconds (doubles each retry)
    """
    last_exc = None
    for attempt in range(max_retries):
        try:
            return await coro_func(*args, **kwargs)
        except RETRYABLE_EXCEPTIONS as e:
            last_exc = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                func_name = getattr(coro_func, "__qualname__", getattr(coro_func, "__name__", str(coro_func)))
                logger.warning(
                    "Retry %d/%d for %s after %s: %.1fs delay",
                    attempt + 1, max_retries, func_name,
                    type(e).__name__, delay,
                )
                await asyncio.sleep(delay)
            else:
                func_name = getattr(coro_func, "__qualname__", getattr(coro_func, "__name__", str(coro_func)))
                logger.error(
                    "All %d retries exhausted for %s: %s",
                    max_retries, func_name, e,
                )
    raise last_exc


def with_retry(max_retries: int = 3, base_delay: float = 1.0):
    """Decorator version of retry_async for async methods."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_async(func, *args, max_retries=max_retries, base_delay=base_delay, **kwargs)
        return wrapper
    return decorator
