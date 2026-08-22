from decimal import Decimal

from pydantic import AwareDatetime, Field

from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.models.base import ZERO, DomainModel


class Trade(DomainModel):
    exchange: str
    exchange_trade_id: str
    exchange_order_id: str
    client_order_id: str | None = None
    symbol: str
    side: OrderSide
    amount: Decimal = Field(gt=ZERO)
    price: Decimal = Field(gt=ZERO)
    fee: Decimal = Field(default=ZERO, ge=ZERO)
    fee_asset: str | None = None
    timestamp: AwareDatetime


class PublicTrade(DomainModel):
    exchange: str
    symbol: str
    side: OrderSide
    price: Decimal = Field(gt=ZERO)
    amount: Decimal = Field(ge=ZERO)
    timestamp: AwareDatetime
