from typing import Protocol

from atlas_trader.domain.interfaces.strategy import Strategy
from atlas_trader.domain.models.candle import Candle
from atlas_trader.domain.models.signal import Signal
from atlas_trader.infrastructure.database.repositories.common import UpsertStats


class SignalRepository(Protocol):
    async def upsert(self, signal: Signal) -> UpsertStats: ...


class StrategyRunResult:
    def __init__(self, signal: Signal, *, inserted: bool) -> None:
        self.signal = signal
        self.inserted = inserted


class StrategyService:
    def __init__(self, strategy: Strategy, repository: SignalRepository) -> None:
        self._strategy = strategy
        self._repository = repository

    async def run(self, candles: list[Candle]) -> StrategyRunResult:
        signal = self._strategy.evaluate(candles)
        stats = await self._repository.upsert(signal)
        return StrategyRunResult(signal, inserted=stats.inserted == 1)
