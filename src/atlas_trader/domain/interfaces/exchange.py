"""Exchange port consumed by application services."""

from datetime import datetime
from typing import Protocol, runtime_checkable

from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.models.candle import Candle
from atlas_trader.domain.models.market import Market, OrderBook, Ticker
from atlas_trader.domain.models.order import ExchangeOrder, OrderIntent
from atlas_trader.domain.models.portfolio import Balance
from atlas_trader.domain.models.trade import Trade


@runtime_checkable
class ExchangeAdapter(Protocol):
    """Common async contract implemented by every exchange integration.

    Expected operational failures cross this boundary as ``ExchangeError`` subclasses,
    never vendor SDK exceptions.
    """

    name: str

    async def get_markets(self) -> list[Market]: ...

    async def get_ticker(self, symbol: str) -> Ticker: ...

    async def get_orderbook(self, symbol: str, *, limit: int = 20) -> OrderBook: ...

    async def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]: ...

    async def get_balances(self) -> list[Balance]: ...

    async def get_open_orders(self, symbol: str | None = None) -> list[ExchangeOrder]: ...

    async def place_order(self, intent: OrderIntent) -> ExchangeOrder: ...

    async def cancel_order(self, exchange_order_id: str) -> ExchangeOrder: ...

    async def get_order(self, exchange_order_id: str) -> ExchangeOrder | None: ...

    async def get_my_trades(
        self, symbol: str | None = None, since: datetime | None = None
    ) -> list[Trade]: ...
