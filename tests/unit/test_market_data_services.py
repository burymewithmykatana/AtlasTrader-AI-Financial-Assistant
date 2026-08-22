from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from atlas_trader.application.market_data import (
    CandleGapKind,
    CandleSyncService,
    MarketDiscoveryService,
)
from atlas_trader.domain.enums.market_status import MarketStatus
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.models.candle import Candle, CandlePage
from atlas_trader.domain.models.market import Market, MarketDiscoverySnapshot
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

    def __init__(self, discovered: list[Market], *, complete: bool = True) -> None:
        self.discovered = discovered
        self.complete = complete

    async def discover_markets(self, *, correlation_id: str) -> MarketDiscoverySnapshot:
        return MarketDiscoverySnapshot(
            exchange=self.name,
            markets=tuple(self.discovered),
            complete=self.complete,
        )


class MemoryMarketRepository:
    def __init__(self) -> None:
        self.records: dict[str, Market] = {}

    async def reconcile(self, snapshot: MarketDiscoverySnapshot) -> UpsertStats:
        markets = list(snapshot.markets)
        existing = set(self.records)
        current = {item.symbol for item in markets}
        if snapshot.complete:
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


@pytest.mark.asyncio
async def test_incomplete_market_snapshot_does_not_deactivate_unseen_markets() -> None:
    repository = MemoryMarketRepository()
    await MarketDiscoveryService(
        FakeMarketAdapter([market("BTCUSDT"), market("ABCUSDT", "ABC")]), repository
    ).run(correlation_id="cycle-1")

    partial_result = await MarketDiscoveryService(
        FakeMarketAdapter([market("BTCUSDT")], complete=False), repository
    ).run(correlation_id="cycle-2")
    await MarketDiscoveryService(FakeMarketAdapter([], complete=False), repository).run(
        correlation_id="cycle-3"
    )

    assert repository.records["ABCUSDT"].active is True
    assert partial_result.complete is False


def test_complete_empty_market_snapshot_requires_explicit_policy() -> None:
    with pytest.raises(ValidationError, match="explicit deactivation approval"):
        MarketDiscoverySnapshot(exchange="nobitex", markets=(), complete=True)

    approved = MarketDiscoverySnapshot(
        exchange="nobitex",
        markets=(),
        complete=True,
        allow_empty_deactivation=True,
    )

    assert approved.allow_empty_deactivation is True


@pytest.mark.asyncio
async def test_explicit_complete_empty_snapshot_deactivates_without_deleting() -> None:
    repository = MemoryMarketRepository()
    await repository.reconcile(
        MarketDiscoverySnapshot(
            exchange="nobitex",
            markets=(market("BTCUSDT"),),
            complete=True,
        )
    )

    await repository.reconcile(
        MarketDiscoverySnapshot(
            exchange="nobitex",
            markets=(),
            complete=True,
            allow_empty_deactivation=True,
        )
    )

    assert set(repository.records) == {"BTCUSDT"}
    assert repository.records["BTCUSDT"].active is False


class FakeCandleAdapter:
    name = "nobitex"

    def __init__(self, pages: list[CandlePage], *, page_size: int = 500) -> None:
        self.pages = pages
        self.maximum_candles_per_page = page_size
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

    gaps = CandleSyncService.detect_gaps(
        candles,
        Timeframe.ONE_MINUTE,
        start,
        start + timedelta(minutes=3),
    )

    assert len(gaps) == 1
    assert gaps[0].kind is CandleGapKind.INTERNAL
    assert gaps[0].expected_open_time == start + timedelta(minutes=1)
    assert gaps[0].missing_candles == 2


@pytest.mark.parametrize(
    ("minute_offsets", "expected"),
    [
        ([1, 2, 3, 4], [(CandleGapKind.LEADING, 1)]),
        ([0, 1, 2, 3], [(CandleGapKind.TRAILING, 1)]),
        (
            [1, 3],
            [
                (CandleGapKind.LEADING, 1),
                (CandleGapKind.INTERNAL, 1),
                (CandleGapKind.TRAILING, 1),
            ],
        ),
        ([0, 1, 2, 3, 4], []),
        ([], [(CandleGapKind.EMPTY, 5)]),
    ],
)
def test_range_aware_gap_detection(
    minute_offsets: list[int], expected: list[tuple[CandleGapKind, int]]
) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    values = [candle(start + timedelta(minutes=offset)) for offset in minute_offsets]

    gaps = CandleSyncService.detect_gaps(
        values,
        Timeframe.ONE_MINUTE,
        start,
        start + timedelta(minutes=4),
    )

    assert [(gap.kind, gap.missing_candles) for gap in gaps] == expected


@pytest.mark.asyncio
async def test_sync_uses_adapter_specific_non_500_page_size() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    adapter = FakeCandleAdapter(
        [
            CandlePage(
                candles=(candle(start), candle(start + timedelta(minutes=1))),
                page=1,
                has_more=True,
            ),
            CandlePage(
                candles=(
                    candle(start + timedelta(minutes=2)),
                    candle(start + timedelta(minutes=3)),
                ),
                page=2,
                has_more=False,
            ),
        ],
        page_size=2,
    )

    result = await CandleSyncService(adapter, MemoryCandleRepository()).sync(
        exchange="nobitex",
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        start=start,
        end=start + timedelta(minutes=3),
        correlation_id="cycle-page-size",
    )

    assert adapter.requested_pages == [1, 2]
    assert result.received == 4
    assert result.gaps == ()
