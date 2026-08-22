from datetime import datetime
from typing import Protocol
from uuid import UUID

from atlas_trader.domain.models.market import Market, Ticker
from atlas_trader.domain.models.order import OrderIntent
from atlas_trader.domain.models.paper import PaperExecutionResult, ReconciliationReport
from atlas_trader.domain.models.signal import Signal


class SignalReader(Protocol):
    async def get_stored(self, signal_id: UUID) -> Signal | None: ...


class MarketReader(Protocol):
    async def get(self, exchange: str, symbol: str) -> Market | None: ...


class PublicQuoteProvider(Protocol):
    async def get_ticker(self, symbol: str, *, correlation_id: str) -> Ticker: ...


class TradingUnitOfWork(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class PaperExecutor(Protocol):
    async def execute(
        self,
        intent: OrderIntent,
        market: Market,
        ticker: Ticker,
        *,
        account_id: str,
        now: datetime,
    ) -> PaperExecutionResult: ...


class PaperReconciler(Protocol):
    async def run(
        self, account_id: str, *, correlation_id: str, now: datetime
    ) -> ReconciliationReport: ...
