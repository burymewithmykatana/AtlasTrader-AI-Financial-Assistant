from datetime import datetime
from typing import Protocol

from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.models.candle import CandlePage
from atlas_trader.domain.models.market import MarketDiscoverySnapshot


class PublicMarketDiscoveryAdapter(Protocol):
    name: str

    async def discover_markets(self, *, correlation_id: str) -> MarketDiscoverySnapshot: ...


class PublicCandleAdapter(Protocol):
    name: str
    maximum_candles_per_page: int

    async def get_candle_page(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        *,
        page: int,
        correlation_id: str,
    ) -> CandlePage: ...


class PublicMarketDataAdapter(PublicMarketDiscoveryAdapter, PublicCandleAdapter, Protocol):
    pass
