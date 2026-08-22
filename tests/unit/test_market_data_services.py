from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from atlas_trader.application.market_data import CandleSyncService, MarketDiscoveryService
from atlas_trader.domain.enums.market_status import MarketStatus
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.models.candle import Candle, CandlePage
from atlas_trader.domain.models.market import Market
from atlas_trader.infrastructure.database.repositories.common import UpsertStats


def market(symbol: str, base: str = "BTC") -> Market:
    return Market(
        exchange="nobitex",
        symbol=symbol,
        base_asset=base,
        quote_asset="USDT",
        price_precision=2,
        amount_precision=6,
        min_order_amount=Decimal("10"),
        price_step=Decimal("0.01"),
        amount_step=Decimal("0.000001"),
    )


def candle(open_time: datetime, close: str = "100") -> Candle:
    return Candle(
        exchange="nobitex",
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        timestamp=open_time,
        close_time=open_time + timedelta(minutes=1),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal(close),
        volume=Decimal("1"),
    )


class FakeMarketAdapter:
    name = "nobitex"

    def __init__(self, discovered: list[Market]) -> None:
        self.discovered = discovered

    async def discover_markets(self, *, correlation_id: str) -> list[Market]:
        return self.discovered


class MemoryMarketRepository:
    def __init__(self) -> None:
        self.records: dict[str, Market] = {}

    async def reconcile(self, exchange: str, markets: list[Market]) -> UpsertStats:
        existing = set(self.records)
        current = {item.symbol for item in markets}
        for symbol in existing - current:
            self.records[symbol] = self.records[symbol].model_copy(
                update={"active": False, "status": MarketStatus.INACTIVE}
            )
        for item in markets:
            self.records[item.symbol] = item
        return UpsertStats(
            inserted=len(current - existing),
            updated=len(current & existing),
        )


@pytest.mark.asyncio
async def test_market_discovery_is_dynamic_and_missing_markets_are_deactivated() -> None:
    repository = MemoryMarketRepository()
    first = MarketDiscoveryService(
        FakeMarketAdapter([market("BTCUSDT"), market("ABCUSDT", "ABC")]), repository
    )
    second = MarketDiscoveryService(FakeMarketAdapter([market("BTCUSDT")]), repository)

    first_result = await first.run(correlation_id="cycle-1")
    second_result = await second.run(correlation_id="cycle-2")

    assert first_result.inserted == 2
    assert second_result.updated == 1
    assert repository.records["ABCUSDT"].active is False
    assert repository.records["ABCUSDT"].status is MarketStatus.INACTIVE


class FakeCandleAdapter:
    name = "nobitex"

    def __init__(self, pages: list[CandlePage]) -> None:
        self.pages = pages
        self.requested_pages: list[int] = []

    async def get_candle_page(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        *,
        page: int,
        correlation_id: str,
    ) -> CandlePage:
        self.requested_pages.append(page)
        return self.pages[page - 1]


class MemoryCandleRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str, Timeframe, datetime], Candle] = {}

    async def upsert(self, candles: list[Candle]) -> UpsertStats:
        inserted = 0
        updated = 0
        for item in candles:
            key = (item.exchange, item.symbol, item.timeframe, item.timestamp)
            if key in self.records:
                updated += 1
            else:
                inserted += 1
            self.records[key] = item
        return UpsertStats(inserted=inserted, updated=updated)

    async def list_range(
        self,
        exchange: str,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        return sorted(
            (
                item
                for item in self.records.values()
                if item.exchange == exchange
                and item.symbol == symbol
                and item.timeframe == timeframe
                and start <= item.timestamp <= end
            ),
            key=lambda item: item.timestamp,
        )


@pytest.mark.asyncio
async def test_500_candle_pagination_and_idempotent_sync() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    first_page = tuple(candle(start + timedelta(minutes=index)) for index in range(500))
    second_page = tuple(candle(start + timedelta(minutes=500 + index)) for index in range(2))
    adapter = FakeCandleAdapter(
        [
            CandlePage(candles=first_page, page=1, has_more=True),
            CandlePage(candles=second_page, page=2, has_more=False),
        ]
    )
    repository = MemoryCandleRepository()
    service = CandleSyncService(adapter, repository)

    first = await service.sync(
        exchange="nobitex",
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start=start,
        end=start + timedelta(minutes=501),
        correlation_id="cycle-1",
    )
    second = await service.sync(
        exchange="nobitex",
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start=start,
        end=start + timedelta(minutes=501),
        correlation_id="cycle-2",
    )

    assert adapter.requested_pages == [1, 2, 1, 2]
    assert first.received == 502
    assert first.inserted == 502
    assert second.inserted == 0
    assert second.updated == 502
    assert len(repository.records) == 502


def test_gap_detection_reports_exact_missing_count() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [candle(start), candle(start + timedelta(minutes=3))]

    gaps = CandleSyncService.detect_gaps(candles, Timeframe.ONE_MINUTE)

    assert len(gaps) == 1
    assert gaps[0].expected_open_time == start + timedelta(minutes=1)
    assert gaps[0].missing_candles == 2
