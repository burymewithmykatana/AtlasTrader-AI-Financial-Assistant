import hashlib
from decimal import Decimal
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator

from atlas_trader.domain.enums.execution_mode import ExecutionMode
from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.order_type import OrderType
from atlas_trader.domain.exceptions import InvalidOrderStateError
from atlas_trader.domain.metadata import Metadata
from atlas_trader.domain.models.base import ZERO, DomainModel
from atlas_trader.domain.models.risk import RiskDecision


class OrderStatus(StrEnum):
    CREATED = "created"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class OrderIntentStatus(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


class OrderIntent(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    client_order_id: str = Field(min_length=8, max_length=32)
    signal_id: UUID | None = None
    exchange: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    requested_quantity: Decimal = Field(gt=ZERO)
    requested_notional: Decimal | None = Field(default=None, gt=ZERO)
    limit_price: Decimal | None = Field(default=None, gt=ZERO)
    reference_price: Decimal = Field(gt=ZERO)
    execution_mode: ExecutionMode
    trading_mode: ExecutionMode
    execution_model: str = Field(min_length=1, max_length=32)
    strategy: str
    strategy_version: str = "1"
    risk_decision: RiskDecision
    status: OrderIntentStatus
    correlation_id: str
    created_at: AwareDatetime
    updated_at: AwareDatetime
    metadata: Metadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_order_price(self) -> "OrderIntent":
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit orders require a price")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("market orders cannot specify a price")
        if self.execution_mode is not self.trading_mode:
            raise ValueError("execution mode and trading mode must agree")
        if self.status is OrderIntentStatus.APPROVED and not self.risk_decision.approved:
            raise ValueError("approved intent requires approved risk decision")
        if self.status is OrderIntentStatus.REJECTED and self.risk_decision.approved:
            raise ValueError("rejected intent requires rejected risk decision")
        return self

    @property
    def amount(self) -> Decimal:
        return self.requested_quantity

    @property
    def price(self) -> Decimal | None:
        return self.limit_price

    @property
    def mode(self) -> ExecutionMode:
        return self.execution_mode

    def execution_signature(self) -> tuple[object, ...]:
        return (
            self.signal_id,
            self.exchange,
            self.symbol,
            self.side,
            self.order_type,
            self.requested_quantity,
            self.requested_notional,
            self.limit_price,
            self.reference_price,
            self.execution_mode,
            self.trading_mode,
            self.execution_model,
            self.strategy,
            self.strategy_version,
        )

    def transition_to(self, status: OrderIntentStatus, *, at: AwareDatetime) -> Self:
        allowed = {
            OrderIntentStatus.APPROVED: {
                OrderIntentStatus.EXECUTING,
                OrderIntentStatus.CANCELLED,
                OrderIntentStatus.FAILED,
            },
            OrderIntentStatus.EXECUTING: {
                OrderIntentStatus.PARTIALLY_FILLED,
                OrderIntentStatus.FILLED,
                OrderIntentStatus.FAILED,
            },
            OrderIntentStatus.PARTIALLY_FILLED: {
                OrderIntentStatus.PARTIALLY_FILLED,
                OrderIntentStatus.FILLED,
                OrderIntentStatus.CANCELLED,
                OrderIntentStatus.FAILED,
            },
            OrderIntentStatus.REJECTED: set(),
            OrderIntentStatus.FILLED: set(),
            OrderIntentStatus.CANCELLED: set(),
            OrderIntentStatus.FAILED: set(),
        }
        if status not in allowed[self.status]:
            raise InvalidOrderStateError(
                f"order intent cannot transition from {self.status.value} to {status.value}"
            )
        return self.model_copy(update={"status": status, "updated_at": at})


def deterministic_client_order_id(*parts: object) -> str:
    canonical = "|".join(str(part) for part in parts)
    return f"atp_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:28]}"


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
