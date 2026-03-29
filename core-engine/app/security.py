"""Security middleware — API Key authentication and rate limiting."""

import logging
import time
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

logger = logging.getLogger(__name__)

# Paths that don't require authentication
PUBLIC_PATHS = {"/health", "/metrics", "/docs", "/openapi.json", "/redoc"}

# Stricter rate limits for sensitive endpoints (per window)
STRICT_RATE_LIMITS: dict[str, int] = {
    "/webhook/": 30,
    "/order/execute": 20,
    "/trading/run-cycle": 10,
    "/scanner/morning": 10,
}


class AuthMiddleware(BaseHTTPMiddleware):
    """API Key authentication.

    If API_AUTH_KEY is set in .env, all non-public endpoints require
    the header: X-API-Key: <key>
    """

    async def dispatch(self, request: Request, call_next):
        auth_key = settings.api_auth_key
        if not auth_key:
            return await call_next(request)

        path = request.url.path

        if path in PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/redoc"):
            return await call_next(request)

        provided = request.headers.get("X-API-Key", "")
        if provided != auth_key:
            logger.warning(
                "Unauthorized request: path=%s ip=%s",
                path, request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "message": "Invalid or missing API key"},
            )

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory rate limiter with per-endpoint stricter limits.

    General limit: settings.rate_limit_max per settings.rate_limit_window.
    Sensitive endpoints (webhook, order) have stricter limits defined in STRICT_RATE_LIMITS.
    """

    def __init__(self, app):
        super().__init__(app)
        self.max_requests = settings.rate_limit_max
        self.window = settings.rate_limit_window
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._last_cleanup = time.time()

    def _get_limit(self, path: str) -> int:
        """Get the rate limit for a given path."""
        for prefix, limit in STRICT_RATE_LIMITS.items():
            if path.startswith(prefix):
                return limit
        return self.max_requests

    def _cleanup_stale_ips(self, now: float):
        """Remove IPs with no recent requests to prevent memory growth."""
        if now - self._last_cleanup < 300:  # cleanup every 5 minutes
            return
        self._last_cleanup = now
        stale = [ip for ip, times in self._requests.items() if not times or now - times[-1] > self.window * 2]
        for ip in stale:
            del self._requests[ip]

    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        path = request.url.path

        self._cleanup_stale_ips(now)

        # Use combined key for strict endpoints (ip:path_prefix)
        limit = self._get_limit(path)
        rate_key = client_ip if limit == self.max_requests else f"{client_ip}:{path.split('/')[1]}"

        # Clean old entries
        self._requests[rate_key] = [t for t in self._requests[rate_key] if now - t < self.window]

        if len(self._requests[rate_key]) >= limit:
            logger.warning("Rate limit exceeded: ip=%s path=%s count=%d limit=%d", client_ip, path, len(self._requests[rate_key]), limit)
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limited", "message": f"Too many requests. Max {limit} per {self.window}s."},
                headers={"Retry-After": str(self.window)},
            )

        self._requests[rate_key].append(now)
        return await call_next(request)
