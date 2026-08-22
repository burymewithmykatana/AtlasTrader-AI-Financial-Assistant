"""AtlasTrader FastAPI application factory."""

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from atlas_trader.api.routes.admin import router as admin_router
from atlas_trader.api.routes.backtests import router as backtests_router
from atlas_trader.api.routes.health import router as health_router
from atlas_trader.api.routes.market_data import router as market_data_router
from atlas_trader.api.routes.markets import router as markets_router
from atlas_trader.config.settings import get_settings
from atlas_trader.infrastructure.database.session import dispose_engine
from atlas_trader.infrastructure.logging import configure_logging

CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


def _correlation_id_from(request: Request) -> str:
    supplied = request.headers.get("X-Correlation-ID", "")
    return supplied if CORRELATION_ID_PATTERN.fullmatch(supplied) else str(uuid4())


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = structlog.get_logger()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "application_started",
            event_type="application.started",
            trading_mode=settings.trading_mode.value,
            live_trading_enabled=settings.live_trading_enabled,
        )
        try:
            yield
        finally:
            await dispose_engine()
            logger.info("application_stopped", event_type="application.stopped")

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def correlation_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = _correlation_id_from(request)
        request.state.correlation_id = correlation_id
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        except Exception as exc:
            logger.error(
                "unhandled_request_error",
                event_type="api.unhandled_error",
                exception_type=type(exc).__name__,
                method=request.method,
                path=request.url.path,
            )
            return JSONResponse(
                status_code=500,
                content={"detail": "internal_server_error", "correlation_id": correlation_id},
                headers={"X-Correlation-ID": correlation_id},
            )
        finally:
            structlog.contextvars.clear_contextvars()

    application.include_router(health_router)
    application.include_router(admin_router)
    application.include_router(markets_router)
    application.include_router(market_data_router)
    application.include_router(backtests_router)
    return application


app = create_app()
