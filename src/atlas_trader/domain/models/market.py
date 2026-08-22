from decimal import Decimal

from pydantic import AwareDatetime, Field, model_validator

from atlas_trader.domain.enums.asset_class import AssetClass
from atlas_trader.domain.enums.market_status import MarketStatus
from atlas_trader.domain.metadata import Metadata
from atlas_trader.domain.models.base import DomainModel


class MarketSymbol(DomainModel):
    exchange: str = Field(min_length=1)
    value: str = Field(min_length=1)
    base_asset: str = Field(min_length=1)
    quote_asset: str = Field(min_length=1)


class Market(DomainModel):
    exchange: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    base_asset: str = Field(min_length=1)
    quote_asset: str = Field(min_length=1)
    price_precision: int = Field(ge=0)
    amount_precision: int = Field(ge=0)
    min_order_amount: Decimal = Field(gt=0)
    price_step: Decimal = Field(default=Decimal("1"), gt=0)
    amount_step: Decimal = Field(default=Decimal("1"), gt=0)
    status: MarketStatus = MarketStatus.ACTIVE
    base_asset_class: AssetClass = AssetClass.UNKNOWN
    quote_asset_class: AssetClass = AssetClass.UNKNOWN
    metadata: Metadata = Field(default_factory=dict)
    active: bool = True


class MarketDiscoverySnapshot(DomainModel):
    exchange: str = Field(min_length=1)
    markets: tuple[Market, ...]
    complete: bool
    allow_empty_deactivation: bool = False

    @model_validator(mode="after")
    def validate_snapshot_policy(self) -> "MarketDiscoverySnapshot":
        if any(market.exchange != self.exchange for market in self.markets):
            raise ValueError("all discovered markets must match the snapshot exchange")
        if self.allow_empty_deactivation and (not self.complete or self.markets):
            raise ValueError("empty deactivation is valid only for a complete empty snapshot")
        if self.complete and not self.markets and not self.allow_empty_deactivation:
            raise ValueError("complete empty snapshots require explicit deactivation approval")
        return self


class Ticker(DomainModel):
    exchange: str
    symbol: str
    bid: Decimal = Field(gt=0)
    ask: Decimal = Field(gt=0)
    last: Decimal = Field(gt=0)
    timestamp: AwareDatetime

    @model_validator(mode="after")
    def validate_spread(self) -> "Ticker":
        if self.ask < self.bid:
            raise ValueError("ask cannot be below bid")
        return self


class OrderBookLevel(DomainModel):
    price: Decimal = Field(gt=0)
    amount: Decimal = Field(gt=0)


class OrderBook(DomainModel):
    exchange: str
    symbol: str
    bids: tuple[OrderBookLevel, ...] = ()
    asks: tuple[OrderBookLevel, ...] = ()
    timestamp: AwareDatetime


class MarketSnapshot(DomainModel):
    market: Market
    order_book: OrderBook
    last_price: Decimal | None = Field(default=None, gt=0)
