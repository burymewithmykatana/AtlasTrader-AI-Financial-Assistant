from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from atlas_trader.config.settings import get_settings
from atlas_trader.domain.enums.execution_mode import ExecutionMode

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    service: str
    version: str
    environment: str
    trading_mode: ExecutionMode
    live_trading_enabled: bool


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        trading_mode=settings.trading_mode,
        live_trading_enabled=settings.live_trading_enabled,
    )
