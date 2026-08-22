"""Nobitex DTO to exchange-neutral domain mapping."""

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import ValidationError

from atlas_trader.domain.enums.asset_class import AssetClass
from atlas_trader.domain.enums.market_status import MarketStatus
from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.exceptions import ExchangeDataNotFoundError
from atlas_trader.domain.models.candle import Candle
from atlas_trader.domain.models.market import Market, OrderBook, OrderBookLevel
from atlas_trader.domain.models.trade import PublicTrade
from atlas_trader.infrastructure.exchanges.nobitex.dto import (
    OptionsResponseDTO,
    OrderBookDTO,
    PublicTradeDTO,
    UdfHistoryDTO,
)

TIMEFRAME_TO_UDF = {
    Timeframe.ONE_MINUTE: "1",
    Timeframe.FIVE_MINUTES: "5",
    Timeframe.FIFTEEN_MINUTES: "15",
    Timeframe.THIRTY_MINUTES: "30",
    Timeframe.ONE_HOUR: "60",
    Timeframe.FOUR_HOURS: "240",
    Timeframe.ONE_DAY: "D",
}


def timeframe_to_udf(timeframe: Timeframe) -> str:
    return TIMEFRAME_TO_UDF[timeframe]


def precision_digits(step: Decimal) -> int:
    normalized = step.normalize()
    exponent = normalized.as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def split_market_symbol(
    symbol: str, currencies: set[str], quote_assets: set[str]
) -> tuple[str, str]:
    upper = symbol.upper()
    candidates = sorted((asset.upper() for asset in quote_assets), key=len, reverse=True)
    for quote in candidates:
        if upper.endswith(quote):
            base = upper[: -len(quote)]
            if base and base in currencies:
                return base, quote
    raise ExchangeDataNotFoundError(f"cannot resolve assets for Nobitex market {symbol}")


def map_market(
    symbol: str,
    options: OptionsResponseDTO,
    *,
    classifications: dict[str, AssetClass],
) -> Market:
    data = options.nobitex
    currencies = {coin.coin.upper() for coin in options.coins}
    quote_assets = {key.upper() for key in data.min_orders}
    base, quote = split_market_symbol(symbol, currencies, quote_assets)
    amount_step = data.amount_precisions.get(symbol, data.amount_precisions.get(symbol.upper()))
    price_step = data.price_precisions.get(symbol, data.price_precisions.get(symbol.upper()))
    minimum = data.min_orders.get(quote.lower(), data.min_orders.get(quote))
    if amount_step is None or price_step is None or minimum is None:
        raise ExchangeDataNotFoundError(f"precision metadata missing for Nobitex market {symbol}")
    return Market(
        exchange="nobitex",
        symbol=symbol.upper(),
        base_asset=base,
        quote_asset=quote,
        price_precision=precision_digits(price_step),
        amount_precision=precision_digits(amount_step),
        min_order_amount=minimum,
        price_step=price_step,
        amount_step=amount_step,
        status=MarketStatus.ACTIVE,
        active=True,
        base_asset_class=classifications.get(base, AssetClass.UNKNOWN),
        quote_asset_class=classifications.get(quote, AssetClass.UNKNOWN),
        metadata={"source": "nobitex_public_options"},
    )


def map_orderbook(symbol: str, dto: OrderBookDTO) -> OrderBook:
    timestamp = datetime.fromtimestamp(dto.last_update / 1000, tz=UTC)
    return OrderBook(
        exchange="nobitex",
        symbol=symbol.upper(),
        bids=tuple(OrderBookLevel(price=price, amount=amount) for price, amount in dto.bids),
        asks=tuple(OrderBookLevel(price=price, amount=amount) for price, amount in dto.asks),
        timestamp=timestamp,
    )


def map_udf_history(
    symbol: str, timeframe: Timeframe, dto: UdfHistoryDTO
) -> tuple[tuple[Candle, ...], int]:
    if dto.status == "no_data":
        return (), 0
    if dto.status != "ok":
        raise ExchangeDataNotFoundError(dto.error_message or "Nobitex UDF request failed")
    candles: list[Candle] = []
    rejected = 0
    for timestamp, open_price, high, low, close, volume in zip(
        dto.timestamps,
        dto.opens,
        dto.highs,
        dto.lows,
        dto.closes,
        dto.volumes,
        strict=True,
    ):
        try:
            candles.append(
                Candle(
                    exchange="nobitex",
                    symbol=symbol.upper(),
                    timeframe=timeframe,
                    timestamp=datetime.fromtimestamp(timestamp, tz=UTC),
                    close_time=datetime.fromtimestamp(timestamp, tz=UTC) + timeframe.duration,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                )
            )
        except ValidationError:
            rejected += 1
    candles.sort(key=lambda candle: candle.timestamp)
    return tuple(candles), rejected


def map_public_trade(symbol: str, dto: PublicTradeDTO) -> PublicTrade:
    return PublicTrade(
        exchange="nobitex",
        symbol=symbol.upper(),
        side=OrderSide(dto.type.lower()),
        price=dto.price,
        amount=dto.volume,
        timestamp=datetime.fromtimestamp(dto.time / 1000, tz=UTC),
    )
