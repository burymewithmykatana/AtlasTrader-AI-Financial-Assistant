from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_trader.api.dependencies import (
    create_nobitex_public_adapter,
    create_nobitex_public_client,
)
from atlas_trader.application.market_data import (
    CandleSyncResult,
    CandleSyncService,
    MarketDiscoveryResult,
    MarketDiscoveryService,
)
from atlas_trader.config.settings import get_settings
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.models.candle import Candle
from atlas_trader.infrastructure.database.repositories.candles import SqlAlchemyCandleRepository
from atlas_trader.infrastructure.database.repositories.markets import SqlAlchemyMarketRepository
from atlas_trader.infrastructure.database.session import get_session

router = APIRouter(prefix="/market-data", tags=["market-data"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class MarketDataSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["markets", "candles"] = "candles"
    exchange: Literal["nobitex"] = "nobitex"
    symbol: str | None = None
    timeframe: Timeframe | None = None
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None

    @model_validator(mode="after")
    def require_candle_fields(self) -> Self:
        if self.kind == "candles" and None in (
            self.symbol,
            self.timeframe,
            self.start,
            self.end,
        ):
            raise ValueError("candle sync requires symbol, timeframe, start, and end")
        return self


@router.post("/sync", response_model=MarketDiscoveryResult | CandleSyncResult)
async def sync_market_data(
    payload: MarketDataSyncRequest,
    request: Request,
    session: SessionDep,
) -> MarketDiscoveryResult | CandleSyncResult:
    settings = get_settings()
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid4()))
    async with create_nobitex_public_client(settings) as client:
        adapter = create_nobitex_public_adapter(client, settings)
        if payload.kind == "markets":
            return await MarketDiscoveryService(adapter, SqlAlchemyMarketRepository(session)).run(
                correlation_id=correlation_id
            )
        assert payload.symbol is not None
        assert payload.timeframe is not None
        assert payload.start is not None
        assert payload.end is not None
        return await CandleSyncService(adapter, SqlAlchemyCandleRepository(session)).sync(
            exchange=payload.exchange,
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            start=payload.start,
            end=payload.end,
            correlation_id=correlation_id,
        )


@router.get("/candles", response_model=list[Candle])
async def list_candles(
    exchange: str,
    symbol: str,
    timeframe: Timeframe,
    start: Annotated[datetime, Query()],
    end: Annotated[datetime, Query()],
    session: SessionDep,
) -> list[Candle]:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("candle query boundaries must be timezone-aware")
    return await SqlAlchemyCandleRepository(session).list_range(
        exchange, symbol, timeframe, start, end
    )
