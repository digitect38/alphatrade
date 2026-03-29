"""FastAPI middleware for logging, metrics, and error handling."""

import logging
import time
import uuid

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.exceptions import AlphaTradeError, BrokerError, ExternalAPIError, RiskViolation
from app.metrics import REQUEST_COUNT, REQUEST_LATENCY

logger = logging.getLogger("alphatrade.request")

# Normalize paths like /market/news/005930 → /market/news/{stock_code}
_PARAM_PREFIXES = ("/market/news/", "/order/history")


def _normalize_path(path: str) -> str:
    for prefix in _PARAM_PREFIXES:
        if path.startswith(prefix) and len(path) > len(prefix):
            return prefix + "{param}"
    return path


class RequestMiddleware(BaseHTTPMiddleware):
    """Adds correlation ID, logs requests, and collects Prometheus metrics."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
        request.state.request_id = request_id

        start = time.perf_counter()
        method = request.method
        path = request.url.path
        metric_path = _normalize_path(path)

        try:
            response = await call_next(request)
            duration = time.perf_counter() - start

            # Prometheus metrics
            REQUEST_COUNT.labels(method=method, endpoint=metric_path, status=response.status_code).inc()
            REQUEST_LATENCY.labels(method=method, endpoint=metric_path).observe(duration)

            logger.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "status": response.status_code,
                    "duration_ms": round(duration * 1000, 1),
                },
            )

            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response

        except Exception as e:
            duration = time.perf_counter() - start
            REQUEST_COUNT.labels(method=method, endpoint=metric_path, status=500).inc()
            REQUEST_LATENCY.labels(method=method, endpoint=metric_path).observe(duration)

            logger.error(
                "request_error",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "duration_ms": round(duration * 1000, 1),
                },
            )
            raise


def register_exception_handlers(app):
    """Register custom exception handlers on the FastAPI app."""

    @app.exception_handler(RiskViolation)
    async def risk_violation_handler(request: Request, exc: RiskViolation):
        return JSONResponse(
            status_code=422,
            content={
                "error": "risk_violation",
                "message": exc.message,
                "retryable": False,
            },
        )

    @app.exception_handler(BrokerError)
    async def broker_error_handler(request: Request, exc: BrokerError):
        status = 503 if exc.retryable else 502
        return JSONResponse(
            status_code=status,
            content={
                "error": "broker_error",
                "message": exc.message,
                "retryable": exc.retryable,
            },
        )

    @app.exception_handler(ExternalAPIError)
    async def external_api_error_handler(request: Request, exc: ExternalAPIError):
        return JSONResponse(
            status_code=502,
            content={"error": "external_api_error", "message": exc.message, "retryable": exc.retryable},
        )

    @app.exception_handler(AlphaTradeError)
    async def alphatrade_error_handler(request: Request, exc: AlphaTradeError):
        return JSONResponse(
            status_code=500,
            content={
                "error": type(exc).__name__,
                "message": exc.message,
                "retryable": exc.retryable,
            },
        )
