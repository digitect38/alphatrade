from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest

from app.config import settings
from app.database import close_db, close_redis, init_db, init_redis
from app.metrics import registry
from app.execution.broker import BrokerClient
from app.logging_config import setup_logging
from app.middleware import RequestMiddleware, register_exception_handlers
from app.security import AuthMiddleware, RateLimitMiddleware
from app.execution.risk_manager import RiskManager
from app.routes.analysis import router as analysis_router
from app.routes.asset import router as asset_router
from app.routes.collect import router as collect_router
from app.routes.data import router as data_router
from app.routes.index import router as index_router
from app.routes.market import router as market_router
from app.routes.order import router as order_router
from app.routes.portfolio import router as portfolio_router
from app.routes.scanner import router as scanner_router
from app.routes.strategy import router as strategy_router
from app.routes.trading import router as trading_router
from app.routes.webhook import router as webhook_router
from app.routes.alert import router as alert_router
from app.routes.ws import router as ws_router, redis_to_websocket_bridge
from app.routes.risk import router as risk_router
from app.services.dart_api import DARTClient
from app.services.kis_api import KISClient
from app.services.naver_news import NaverNewsClient
from app.services.notification import NotificationService
from app.services.market_poller import market_state_fallback_loop

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Logging
    setup_logging(json_format=True)

    # Startup: create all service instances and store in app.state
    db_pool = await init_db()
    redis_client = await init_redis()

    app.state.db_pool = db_pool
    app.state.redis_client = redis_client

    kis = KISClient()
    await kis.initialize(redis_client)
    app.state.kis_client = kis
    app.state.dart_client = DARTClient()
    app.state.naver_client = NaverNewsClient()
    app.state.notifier = NotificationService()
    app.state.broker_client = BrokerClient(kis_client=kis)
    app.state.risk_manager = RiskManager()

    # Recover inflight orders from previous run (v1.31 16.5.2)
    try:
        from app.execution.order_fsm import recover_inflight_orders
        inflight = await recover_inflight_orders(db_pool)
        if inflight:
            import logging
            logging.getLogger(__name__).warning("Found %d inflight orders on startup", len(inflight))
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Inflight order recovery failed: %s", e)

    # Start Redis→WebSocket bridge (background task)
    import asyncio
    ws_bridge_task = asyncio.create_task(redis_to_websocket_bridge(redis_client))

    # Start KIS WebSocket real-time streaming (if API keys configured)
    kis_ws_task = None
    market_poll_task = None
    if settings.kis_app_key and settings.kis_app_secret:
        try:
            from app.services.kis_websocket import KISWebSocketClient
            kis_ws_client = KISWebSocketClient(redis=redis_client)
            # Get universe stock codes for subscription
            async with db_pool.acquire() as conn:
                universe = await conn.fetch("SELECT stock_code FROM universe WHERE is_active = TRUE")
            codes = [r["stock_code"] for r in universe]
            if codes:
                kis_ws_task = asyncio.create_task(kis_ws_client.run(stock_codes=codes))
                market_poll_task = asyncio.create_task(
                    market_state_fallback_loop(
                        pool=db_pool,
                        redis=redis_client,
                        kis_client=kis,
                        interval_seconds=settings.market_state_poll_interval_sec,
                    )
                )
                app.state.kis_ws_client = kis_ws_client
                import logging
                logging.getLogger(__name__).info("KIS WebSocket started for %d stocks", len(codes))
                logging.getLogger(__name__).info(
                    "Market fallback poller started (%ds interval)",
                    settings.market_state_poll_interval_sec,
                )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("KIS WebSocket startup failed: %s", e)

    yield

    # Shutdown background tasks
    ws_bridge_task.cancel()
    if kis_ws_task:
        app.state.kis_ws_client.stop()
        kis_ws_task.cancel()
    if market_poll_task:
        market_poll_task.cancel()

    # Shutdown
    await app.state.notifier.close()
    await app.state.naver_client.close()
    await app.state.dart_client.close()
    await app.state.kis_client.close()
    await close_db()
    await close_redis()


app = FastAPI(
    title="AlphaTrade Core Engine",
    version="0.1.0",
    description="AI Quantitative Trading System — Core Analysis & Strategy Engine",
    lifespan=lifespan,
)

# --- Middleware & Error Handlers ---
# Note: middleware executes in reverse order (last added = first executed)
app.add_middleware(RequestMiddleware)  # 4th: logging + correlation ID + metrics
app.add_middleware(RateLimitMiddleware)  # 3rd: rate limit
app.add_middleware(AuthMiddleware)  # 2nd: authentication
app.add_middleware(  # 1st: CORS
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://alphatrade.visualfactory.ai"],
    allow_methods=["*"],
    allow_headers=["*"],
)
register_exception_handlers(app)

# --- Routers ---
app.include_router(collect_router, prefix="/collect", tags=["collection"])
app.include_router(data_router, prefix="/data", tags=["data"])
app.include_router(analysis_router, prefix="/analyze", tags=["analysis"])
app.include_router(asset_router, prefix="/asset", tags=["asset"])
app.include_router(strategy_router, prefix="/strategy", tags=["strategy"])
app.include_router(webhook_router, prefix="/webhook", tags=["webhook"])
app.include_router(order_router, prefix="/order", tags=["order"])
app.include_router(portfolio_router, prefix="/portfolio", tags=["portfolio"])
app.include_router(scanner_router, prefix="/scanner", tags=["scanner"])
app.include_router(alert_router, prefix="/alert", tags=["alert"])
app.include_router(ws_router, tags=["websocket"])
app.include_router(market_router, prefix="/market", tags=["market"])
app.include_router(index_router, prefix="/index", tags=["index"])
app.include_router(trading_router, prefix="/trading", tags=["trading"])
app.include_router(risk_router, prefix="/risk", tags=["risk"])


# --- Health & Metrics ---


@app.get("/health")
async def health():
    """Health check endpoint for Docker healthcheck and monitoring."""
    checks = {"status": "ok", "db": "unknown", "redis": "unknown"}

    try:
        async with app.state.db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"error: {e}"
        checks["status"] = "degraded"

    try:
        await app.state.redis_client.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        checks["status"] = "degraded"

    return checks


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(registry),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
