"""Nobitex-only response DTOs. These never cross the adapter boundary."""

from decimal import Decimal
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from atlas_trader.infrastructure.exchanges.nobitex.errors import NobitexResponseError


class NobitexDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CoinDTO(NobitexDTO):
    coin: str
    name: str = ""
    default_network: str | None = Field(default=None, alias="defaultNetwork")


class OptionsDataDTO(NobitexDTO):
    min_orders: dict[str, Decimal] = Field(default_factory=dict, alias="minOrders")
    amount_precisions: dict[str, Decimal] = Field(default_factory=dict, alias="amountPrecisions")
    price_precisions: dict[str, Decimal] = Field(default_factory=dict, alias="pricePrecisions")

    @field_validator("min_orders", "amount_precisions", "price_precisions", mode="before")
    @classmethod
    def parse_decimal_mapping(cls, value: object) -> object:
        if not isinstance(value, dict):
            return {}
        return {str(key): Decimal(str(item)) for key, item in value.items()}


class OptionsResponseDTO(NobitexDTO):
    status: str
    nobitex: OptionsDataDTO
    coins: tuple[CoinDTO, ...] = ()

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        normalized = dict(payload)
        normalized["nobitex"] = payload.get("nobitex", payload)
        try:
            result = cls.model_validate(normalized)
        except ValidationError as exc:
            raise NobitexResponseError("invalid /v2/options response") from exc
        if result.status != "ok":
            raise NobitexResponseError("/v2/options returned a failed status")
        return result


class OrderBookDTO(NobitexDTO):
    status: str = "ok"
    last_update: int = Field(alias="lastUpdate")
    last_trade_price: Decimal | None = Field(default=None, alias="lastTradePrice")
    bids: tuple[tuple[Decimal, Decimal], ...] = ()
    asks: tuple[tuple[Decimal, Decimal], ...] = ()

    @field_validator("last_trade_price", mode="before")
    @classmethod
    def parse_optional_decimal(cls, value: object) -> Decimal | None:
        return None if value in (None, "") else Decimal(str(value))

    @field_validator("bids", "asks", mode="before")
    @classmethod
    def parse_levels(cls, value: object) -> tuple[tuple[Decimal, Decimal], ...]:
        if not isinstance(value, list):
            return ()
        try:
            return tuple((Decimal(str(level[0])), Decimal(str(level[1]))) for level in value)
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError("invalid order-book level") from exc


class OrderBooksResponseDTO(NobitexDTO):
    status: str
    books: dict[str, OrderBookDTO]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        if payload.get("status") != "ok":
            raise NobitexResponseError("/v3/orderbook/all returned a failed status")
        try:
            books = {
                key: OrderBookDTO.model_validate(value)
                for key, value in payload.items()
                if key != "status" and isinstance(value, dict)
            }
            result = cls(status=str(payload.get("status", "")), books=books)
        except (ValidationError, ValueError) as exc:
            raise NobitexResponseError("invalid /v3/orderbook/all response") from exc
        if not result.books:
            raise NobitexResponseError("/v3/orderbook/all returned no markets")
        return result


class UdfHistoryDTO(NobitexDTO):
    status: str = Field(alias="s")
    timestamps: tuple[int, ...] = Field(default=(), alias="t")
    opens: tuple[Decimal, ...] = Field(default=(), alias="o")
    highs: tuple[Decimal, ...] = Field(default=(), alias="h")
    lows: tuple[Decimal, ...] = Field(default=(), alias="l")
    closes: tuple[Decimal, ...] = Field(default=(), alias="c")
    volumes: tuple[Decimal, ...] = Field(default=(), alias="v")
    error_message: str | None = Field(default=None, alias="errmsg")

    @field_validator("opens", "highs", "lows", "closes", "volumes", mode="before")
    @classmethod
    def parse_decimals(cls, value: object) -> tuple[Decimal, ...]:
        if value is None:
            return ()
        if not isinstance(value, list):
            raise ValueError("UDF value arrays must be lists")
        return tuple(Decimal(str(item)) for item in value)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        try:
            result = cls.model_validate(payload)
        except ValidationError as exc:
            raise NobitexResponseError("invalid UDF history response") from exc
        lengths = {
            len(result.timestamps),
            len(result.opens),
            len(result.highs),
            len(result.lows),
            len(result.closes),
            len(result.volumes),
        }
        if result.status == "ok" and len(lengths) != 1:
            raise NobitexResponseError("UDF history arrays have inconsistent lengths")
        return result


class PublicTradeDTO(NobitexDTO):
    time: int
    price: Decimal
    volume: Decimal
    type: str

    @field_validator("price", "volume", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return Decimal(str(value))


class TradesResponseDTO(NobitexDTO):
    status: str
    trades: tuple[PublicTradeDTO, ...] = Field(default=(), max_length=20)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        try:
            result = cls.model_validate(payload)
        except ValidationError as exc:
            raise NobitexResponseError("invalid public trades response") from exc
        if result.status != "ok":
            raise NobitexResponseError("public trades endpoint returned a failed status")
        return result
