"""Nobitex public adapter; authenticated operations are deliberately unavailable."""

from datetime import datetime
from decimal import Decimal
from typing import Never
from uuid import uuid4

import structlog
from pydantic import ValidationError

from atlas_trader.domain.enums.asset_class import AssetClass
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.exceptions import (
    ExchangeError,
    ExchangeOrderRejectedError,
    ExchangeRequestError,
)
from atlas_trader.domain.models.candle import Candle, CandlePage
from atlas_trader.domain.models.market import Market, MarketDiscoverySnapshot, OrderBook, Ticker
from atlas_trader.domain.models.order import ExchangeOrder, OrderIntent
from atlas_trader.domain.models.portfolio import Balance
from atlas_trader.domain.models.trade import PublicTrade, Trade
from atlas_trader.infrastructure.exchanges.nobitex.client import NobitexPublicClient
from atlas_trader.infrastructure.exchanges.nobitex.dto import (
    OptionsResponseDTO,
    OrderBookDTO,
    OrderBooksResponseDTO,
    TradesResponseDTO,
    UdfHistoryDTO,
)
from atlas_trader.infrastructure.exchanges.nobitex.mapper import (
    map_market,
    map_orderbook,
    map_public_trade,
    map_udf_history,
    timeframe_to_udf,
)


class NobitexPublicAdapter:
    name = "nobitex"
    maximum_candles_per_page = 500

    def __init__(
        self,
        client: NobitexPublicClient,
        *,
        asset_classifications: dict[str, AssetClass] | None = None,
    ) -> None:
        self._client = client
        self._classifications = {
            key.upper(): value for key, value in (asset_classifications or {}).items()
        }
        self._logger = structlog.get_logger()

    async def discover_markets(self, *, correlation_id: str) -> MarketDiscoverySnapshot:
        options = OptionsResponseDTO.from_payload(
            await self._client.get_options(correlation_id=correlation_id)
        )
        orderbooks = OrderBooksResponseDTO.from_payload(
            await self._client.get_all_orderbooks(correlation_id=correlation_id)
        )
        markets: list[Market] = []
        rejected_symbols: list[str] = []
        for symbol in sorted(orderbooks.books):
            try:
                markets.append(map_market(symbol, options, classifications=self._classifications))
            except (ExchangeError, ValidationError, ValueError) as exc:
                rejected_symbols.append(symbol)
                self._logger.warning(
                    "nobitex_market_mapping_rejected",
                    event_type="market.mapping.rejected",
                    exchange=self.name,
                    symbol=symbol,
                    correlation_id=correlation_id,
                    exception_type=type(exc).__name__,
                )
        return MarketDiscoverySnapshot(
            exchange=self.name,
            markets=tuple(markets),
            complete=not rejected_symbols,
        )

    async def get_markets(self) -> list[Market]:
        snapshot = await self.discover_markets(correlation_id=str(uuid4()))
        return list(snapshot.markets)

    async def get_ticker(self, symbol: str, *, correlation_id: str | None = None) -> Ticker:
        payload = await self._client.get_orderbook(
            symbol, correlation_id=correlation_id or str(uuid4())
        )
        dto = OrderBookDTO.from_payload(payload)
        book = map_orderbook(symbol, dto)
        if not book.bids or not book.asks:
            raise ExchangeRequestError(f"Nobitex order book for {symbol} has no best bid/ask")
        last = dto.last_trade_price or (book.bids[0].price + book.asks[0].price) / Decimal("2")
        return Ticker(
            exchange=self.name,
            symbol=symbol.upper(),
            bid=book.bids[0].price,
            ask=book.asks[0].price,
            last=last,
            timestamp=book.timestamp,
        )

    async def get_orderbook(self, symbol: str, *, limit: int = 20) -> OrderBook:
        if limit < 1:
            raise ExchangeRequestError("order-book limit must be positive")
        payload = await self._client.get_orderbook(symbol, correlation_id=str(uuid4()))
        dto = OrderBookDTO.from_payload(payload)
        book = map_orderbook(symbol, dto)
        return book.model_copy(update={"bids": book.bids[:limit], "asks": book.asks[:limit]})

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
        payload = await self._client.get_udf_history(
            symbol=symbol,
            resolution=timeframe_to_udf(timeframe),
            start_epoch=int(start.timestamp()),
            end_epoch=int(end.timestamp()),
            page=page,
            correlation_id=correlation_id,
        )
        dto = UdfHistoryDTO.from_payload(payload)
        candles, rejected = map_udf_history(symbol, timeframe, dto)
        return CandlePage(
            candles=candles,
            page=page,
            has_more=len(dto.timestamps) == self.maximum_candles_per_page,
            rejected=rejected,
        )

    async def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        correlation_id = str(uuid4())
        candles: list[Candle] = []
        page_number = 1
        while True:
            page = await self.get_candle_page(
                symbol,
                timeframe,
                start,
                end,
                page=page_number,
                correlation_id=correlation_id,
            )
            candles.extend(page.candles)
            if not page.has_more:
                break
            page_number += 1
        return sorted(set(candles), key=lambda candle: candle.timestamp)

    async def get_public_trades(self, symbol: str) -> list[PublicTrade]:
        payload = await self._client.get_trades(symbol, correlation_id=str(uuid4()))
        dto = TradesResponseDTO.from_payload(payload)
        return [map_public_trade(symbol, trade) for trade in dto.trades]

    async def get_balances(self) -> list[Balance]:
        self._reject_authenticated_operation()

    async def get_open_orders(self, symbol: str | None = None) -> list[ExchangeOrder]:
        self._reject_authenticated_operation()

    async def place_order(self, intent: OrderIntent) -> ExchangeOrder:
        self._reject_authenticated_operation()

    async def cancel_order(self, exchange_order_id: str) -> ExchangeOrder:
        self._reject_authenticated_operation()

    async def get_order(self, exchange_order_id: str) -> ExchangeOrder | None:
        self._reject_authenticated_operation()

    async def get_my_trades(
        self, symbol: str | None = None, since: datetime | None = None
    ) -> list[Trade]:
        self._reject_authenticated_operation()

    @staticmethod
    def _reject_authenticated_operation() -> Never:
        raise ExchangeOrderRejectedError(
            "NobitexPublicAdapter has no authenticated or trading capability"
        )
