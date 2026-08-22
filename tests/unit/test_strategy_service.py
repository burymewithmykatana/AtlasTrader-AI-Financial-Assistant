from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from atlas_trader.application.strategy_service import StrategyService
from atlas_trader.domain.enums.signal_action import SignalAction
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.models.candle import Candle
from atlas_trader.domain.models.signal import Signal
from atlas_trader.infrastructure.database.repositories.common import UpsertStats


class HoldStrategy:
    name = "hold"
    version = "1"
    required_history = 1

    def evaluate(self, candles: list[Candle]) -> Signal:
        candle = candles[-1]
        return Signal(
            strategy=self.name,
            strategy_version=self.version,
            exchange=candle.exchange,
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            candle_timestamp=candle.timestamp,
            action=SignalAction.HOLD,
            score=Decimal("0"),
            reference_price=candle.close,
        )


class MemorySignalRepository:
    def __init__(self) -> None:
        self.keys: set[tuple[object, ...]] = set()

    async def upsert(self, signal: Signal) -> UpsertStats:
        key = (
            signal.strategy,
            signal.strategy_version,
            signal.exchange,
            signal.symbol,
            signal.timeframe,
            signal.candle_timestamp,
        )
        inserted = key not in self.keys
        self.keys.add(key)
        return UpsertStats(inserted=int(inserted), updated=0)


@pytest.mark.asyncio
async def test_signal_generation_is_idempotent() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candle = Candle(
        exchange="mock",
        symbol="BTC-USDT",
        timeframe=Timeframe.ONE_HOUR,
        timestamp=start,
        close_time=start + timedelta(hours=1),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("1"),
    )
    repository = MemorySignalRepository()
    service = StrategyService(HoldStrategy(), repository)

    first = await service.run([candle])
    second = await service.run([candle])

    assert first.inserted is True
    assert second.inserted is False
    assert first.signal == second.signal
