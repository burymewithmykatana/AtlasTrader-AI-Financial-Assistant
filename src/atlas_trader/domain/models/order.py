from decimal import Decimal
from enum import StrEnum

from pydantic import AwareDatetime, Field, model_validator

from atlas_trader.domain.enums.execution_mode import ExecutionMode
from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.order_type import OrderType
from atlas_trader.domain.metadata import Metadata
from atlas_trader.domain.models.base import ZERO, DomainModel


class OrderStatus(StrEnum):
    CREATED = "created"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class OrderIntent(DomainModel):
    client_order_id: str = Field(min_length=8, max_length=64)
    exchange: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    amount: Decimal = Field(gt=ZERO)
    price: Decimal | None = Field(default=None, gt=ZERO)
    mode: ExecutionMode
    strategy: str
    correlation_id: str
    created_at: AwareDatetime
    metadata: Metadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_order_price(self) -> "OrderIntent":
        if self.order_type is OrderType.LIMIT and self.price is None:
            raise ValueError("limit orders require a price")
        if self.order_type is OrderType.MARKET and self.price is not None:
            raise ValueError("market orders cannot specify a price")
        return self


class ExchangeOrder(DomainModel):
    exchange: str
    exchange_order_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    amount: Decimal = Field(gt=ZERO)
    filled_amount: Decimal = Field(default=ZERO, ge=ZERO)
    price: Decimal | None = Field(default=None, gt=ZERO)
    average_price: Decimal | None = Field(default=None, gt=ZERO)
    status: OrderStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_fill_state(self) -> "ExchangeOrder":
        if self.filled_amount > self.amount:
            raise ValueError("filled amount cannot exceed order amount")
        if self.status is OrderStatus.FILLED and self.filled_amount != self.amount:
            raise ValueError("filled orders must have the complete amount filled")
        return self
