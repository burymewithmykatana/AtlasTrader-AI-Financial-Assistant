"""Exchange-neutral market discovery and candle synchronization use cases."""

from collections.abc import Sequence
from datetime import datetime
from math import ceil
from typing import Protocol

from pydantic import AwareDatetime, Field

from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.interfaces.market_data import (
    PublicCandleAdapter,
    PublicMarketDiscoveryAdapter,
)
from atlas_trader.domain.models.base import DomainModel
from atlas_trader.domain.models.candle import Candle
from atlas_trader.domain.models.market import Market
from atlas_trader.infrastructure.database.repositories.common import UpsertStats


class MarketRepository(Protocol):
    async def reconcile(self, exchange: str, markets: list[Market]) -> UpsertStats: ...


class CandleRepository(Protocol):
    async def upsert(self, candles: list[Candle]) -> UpsertStats: ...

    async def list_range(
        self,
        exchange: str,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]: ...


class MarketDiscoveryResult(DomainModel):
    exchange: str
    discovered: int = Field(ge=0)
    inserted: int = Field(ge=0)
    updated: int = Field(ge=0)


class CandleGap(DomainModel):
    expected_open_time: AwareDatetime
    next_available_open_time: AwareDatetime
    missing_candles: int = Field(ge=1)


class CandleSyncResult(DomainModel):
    exchange: str
    symbol: str
    timeframe: Timeframe
    requested_start: AwareDatetime
    requested_end: AwareDatetime
    received: int = Field(ge=0)
    inserted: int = Field(ge=0)
    updated: int = Field(ge=0)
    rejected: int = Field(ge=0)
    gaps: tuple[CandleGap, ...] = ()


class MarketDiscoveryService:
    def __init__(self, adapter: PublicMarketDiscoveryAdapter, repository: MarketRepository) -> None:
        self._adapter = adapter
        self._repository = repository

    async def run(self, *, correlation_id: str) -> MarketDiscoveryResult:
        markets = await self._adapter.discover_markets(correlation_id=correlation_id)
        stats = await self._repository.reconcile(self._adapter.name, markets)
        return MarketDiscoveryResult(
            exchange=self._adapter.name,
            discovered=len(markets),
            inserted=stats.inserted,
            updated=stats.updated,
        )


class CandleSyncService:
    def __init__(self, adapter: PublicCandleAdapter, repository: CandleRepository) -> None:
        self._adapter = adapter
        self._repository = repository

    async def sync(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        correlation_id: str,
    ) -> CandleSyncResult:
        if exchange != self._adapter.name:
            raise ValueError(f"adapter {self._adapter.name} cannot synchronize {exchange}")
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("sync boundaries must be timezone-aware")
        if end < start:
            raise ValueError("sync end cannot be before start")

        estimated = max(1, ceil((end - start) / timeframe.duration))
        max_pages = ceil(estimated / 500) + 2
        received: list[Candle] = []
        rejected = 0
        for page_number in range(1, max_pages + 1):
            page = await self._adapter.get_candle_page(
                symbol,
                timeframe,
                start,
                end,
                page=page_number,
                correlation_id=correlation_id,
            )
            received.extend(page.candles)
            rejected += page.rejected
            if not page.has_more:
                break
        else:
            raise RuntimeError("candle pagination exceeded its deterministic safety bound")

        normalized, duplicate_rejections = self._normalize(received, start, end)
        rejected += duplicate_rejections
        stats = await self._repository.upsert(normalized)
        return CandleSyncResult(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            requested_start=start,
            requested_end=end,
            received=len(received),
            inserted=stats.inserted,
            updated=stats.updated,
            rejected=rejected,
            gaps=self.detect_gaps(normalized, timeframe),
        )

    @staticmethod
    def _normalize(
        candles: Sequence[Candle], start: datetime, end: datetime
    ) -> tuple[list[Candle], int]:
        unique: dict[datetime, Candle] = {}
        rejected = 0
        for candle in sorted(candles, key=lambda item: item.timestamp):
            if candle.timestamp < start or candle.timestamp > end:
                rejected += 1
                continue
            if candle.timestamp in unique:
                rejected += 1
                continue
            unique[candle.timestamp] = candle
        return list(unique.values()), rejected

    @staticmethod
    def detect_gaps(candles: Sequence[Candle], timeframe: Timeframe) -> tuple[CandleGap, ...]:
        ordered = sorted(candles, key=lambda candle: candle.timestamp)
        gaps: list[CandleGap] = []
        for previous, current in zip(ordered, ordered[1:], strict=False):
            expected = previous.timestamp + timeframe.duration
            if current.timestamp > expected:
                missing = int((current.timestamp - expected) / timeframe.duration)
                gaps.append(
                    CandleGap(
                        expected_open_time=expected,
                        next_available_open_time=current.timestamp,
                        missing_candles=missing,
                    )
                )
        return tuple(gaps)
