"""Deterministic in-memory exchange for tests and local development."""

from datetime import UTC, datetime
from decimal import Decimal

from atlas_trader.domain.enums.execution_mode import ExecutionMode
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.exceptions import (
    ExchangeDataNotFoundError,
    ExchangeOrderRejectedError,
    ExchangeRequestError,
    IdempotencyConflictError,
    InvalidOrderStateError,
)
from atlas_trader.domain.models.candle import Candle, CandlePage
from atlas_trader.domain.models.market import Market, OrderBook, OrderBookLevel, Ticker
from atlas_trader.domain.models.order import ExchangeOrder, OrderIntent, OrderStatus
from atlas_trader.domain.models.portfolio import Balance
from atlas_trader.domain.models.trade import Trade


class MockExchangeAdapter:
    """A network-free adapter with idempotent order submission semantics.

    It deliberately rejects LIVE intents: this Phase 0 component exists for contract
    testing, not production execution.
    """

    name = "mock"
    maximum_candles_per_page = 1000

    def __init__(self) -> None:
        self._markets: dict[str, Market] = {}
        self._tickers: dict[str, Ticker] = {}
        self._candles: dict[tuple[str, Timeframe], list[Candle]] = {}
        self._balances: dict[str, Balance] = {}
        self._orders: dict[str, ExchangeOrder] = {}
        self._client_order_index: dict[str, str] = {}
        self._intents: dict[str, OrderIntent] = {}
        self._trades: list[Trade] = []
        self._order_sequence = 0

    def seed_market(self, market: Market) -> None:
        self._require_exchange(market.exchange)
        self._markets[market.symbol] = market

    def seed_ticker(self, ticker: Ticker) -> None:
        self._require_exchange(ticker.exchange)
        self._tickers[ticker.symbol] = ticker

    def seed_candles(self, candles: list[Candle]) -> None:
        for candle in candles:
            self._require_exchange(candle.exchange)
            key = (candle.symbol, candle.timeframe)
            self._candles.setdefault(key, []).append(candle)
            self._candles[key].sort(key=lambda item: item.timestamp)

    def seed_balance(self, balance: Balance) -> None:
        self._balances[balance.asset] = balance

    async def get_markets(self) -> list[Market]:
        return sorted(self._markets.values(), key=lambda market: market.symbol)

    async def get_ticker(self, symbol: str) -> Ticker:
        try:
            return self._tickers[symbol]
        except KeyError as exc:
            raise ExchangeDataNotFoundError(f"ticker not seeded for {symbol}") from exc

    async def get_orderbook(self, symbol: str, *, limit: int = 20) -> OrderBook:
        if limit < 1:
            raise ExchangeRequestError("order-book limit must be positive")
        ticker = await self.get_ticker(symbol)
        return OrderBook(
            exchange=self.name,
            symbol=symbol,
            bids=(OrderBookLevel(price=ticker.bid, amount=Decimal("1")),)[:limit],
            asks=(OrderBookLevel(price=ticker.ask, amount=Decimal("1")),)[:limit],
            timestamp=ticker.timestamp,
        )

    async def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        if start.tzinfo is None or end.tzinfo is None:
            raise ExchangeRequestError("candle boundaries must be timezone-aware")
        if end < start:
            raise ExchangeRequestError("candle end cannot be before start")
        return [
            candle
            for candle in self._candles.get((symbol, timeframe), [])
            if start <= candle.timestamp <= end
        ]

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
        del correlation_id
        candles = await self.get_candles(symbol, timeframe, start, end)
        offset = (page - 1) * self.maximum_candles_per_page
        values = tuple(candles[offset : offset + self.maximum_candles_per_page])
        return CandlePage(
            candles=values,
            page=page,
            has_more=offset + len(values) < len(candles),
        )

    async def get_balances(self) -> list[Balance]:
        return sorted(self._balances.values(), key=lambda balance: balance.asset)

    async def get_open_orders(self, symbol: str | None = None) -> list[ExchangeOrder]:
        open_statuses = {OrderStatus.CREATED, OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}
        return [
            order
            for order in self._orders.values()
            if order.status in open_statuses and (symbol is None or order.symbol == symbol)
        ]

    async def place_order(self, intent: OrderIntent) -> ExchangeOrder:
        if intent.mode is ExecutionMode.LIVE:
            raise ExchangeOrderRejectedError("MockExchangeAdapter never accepts LIVE orders")
        self._require_exchange(intent.exchange)

        existing_id = self._client_order_index.get(intent.client_order_id)
        if existing_id is not None:
            original = self._intents[intent.client_order_id]
            if self._execution_signature(original) != self._execution_signature(intent):
                raise IdempotencyConflictError(
                    "client_order_id was reused with different execution parameters"
                )
            return self._orders[existing_id]

        self._order_sequence += 1
        exchange_order_id = f"mock-{self._order_sequence:08d}"
        now = datetime.now(UTC)
        order = ExchangeOrder(
            exchange=self.name,
            exchange_order_id=exchange_order_id,
            client_order_id=intent.client_order_id,
            symbol=intent.symbol,
            side=intent.side,
            order_type=intent.order_type,
            amount=intent.amount,
            price=intent.price,
            status=OrderStatus.SUBMITTED,
            created_at=now,
            updated_at=now,
        )
        self._orders[exchange_order_id] = order
        self._client_order_index[intent.client_order_id] = exchange_order_id
        self._intents[intent.client_order_id] = intent
        return order

    async def cancel_order(self, exchange_order_id: str) -> ExchangeOrder:
        order = await self.get_order(exchange_order_id)
        if order is None:
            raise ExchangeDataNotFoundError(f"unknown exchange order {exchange_order_id}")
        if order.status is OrderStatus.CANCELLED:
            return order
        if order.status in {OrderStatus.FILLED, OrderStatus.REJECTED}:
            raise InvalidOrderStateError(f"a {order.status.value} order cannot be cancelled")
        cancelled = order.model_copy(
            update={"status": OrderStatus.CANCELLED, "updated_at": datetime.now(UTC)}
        )
        self._orders[exchange_order_id] = cancelled
        return cancelled

    async def get_order(self, exchange_order_id: str) -> ExchangeOrder | None:
        return self._orders.get(exchange_order_id)

    async def get_my_trades(
        self, symbol: str | None = None, since: datetime | None = None
    ) -> list[Trade]:
        return [
            trade
            for trade in self._trades
            if (symbol is None or trade.symbol == symbol)
            and (since is None or trade.timestamp >= since)
        ]

    def _require_exchange(self, exchange: str) -> None:
        if exchange != self.name:
            raise ExchangeRequestError(
                f"{self.__class__.__name__} cannot handle exchange {exchange!r}"
            )

    @staticmethod
    def _execution_signature(intent: OrderIntent) -> tuple[object, ...]:
        return intent.execution_signature()
