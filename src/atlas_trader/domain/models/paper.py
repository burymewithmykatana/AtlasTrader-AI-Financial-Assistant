from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator

from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.signal_action import SignalAction
from atlas_trader.domain.metadata import Metadata
from atlas_trader.domain.models.base import ZERO, DomainModel
from atlas_trader.domain.models.order import OrderIntent
from atlas_trader.domain.models.risk import RiskDecision


class PaperBalance(DomainModel):
    account_id: str
    asset: str
    available: Decimal = Field(ge=ZERO)
    updated_at: AwareDatetime


class PaperPosition(DomainModel):
    account_id: str
    exchange: str
    symbol: str
    base_asset: str
    quote_asset: str
    quantity: Decimal = Field(default=ZERO, ge=ZERO)
    average_cost: Decimal = Field(default=ZERO, ge=ZERO)
    realized_pnl: Decimal = ZERO
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def empty_position_has_no_cost(self) -> "PaperPosition":
        if self.quantity == ZERO and self.average_cost != ZERO:
            raise ValueError("empty position must have zero average cost")
        return self


class PaperFill(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    execution_event_id: str = Field(min_length=8, max_length=64)
    intent_id: UUID
    client_order_id: str
    account_id: str
    exchange: str
    symbol: str
    side: OrderSide
    quantity: Decimal = Field(gt=ZERO)
    price: Decimal = Field(gt=ZERO)
    notional: Decimal = Field(gt=ZERO)
    fee: Decimal = Field(ge=ZERO)
    fee_asset: str
    realized_pnl: Decimal = ZERO
    correlation_id: str
    executed_at: AwareDatetime
    assumptions: Metadata = Field(default_factory=dict)


class PaperPortfolioSnapshot(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    account_id: str
    quote_asset: str
    cash: Decimal = Field(ge=ZERO)
    positions_value: Decimal = Field(ge=ZERO)
    total_equity: Decimal = Field(ge=ZERO)
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    timestamp: AwareDatetime


class PaperExecutionResult(DomainModel):
    fill: PaperFill
    balance: PaperBalance
    position: PaperPosition
    snapshot: PaperPortfolioSnapshot
    created: bool


class ReconciliationReport(DomainModel):
    account_id: str
    consistent: bool
    anomalies: tuple[str, ...] = ()
    fill_count: int = Field(ge=0)
    checked_at: AwareDatetime


class PaperTradingCycleResult(DomainModel):
    correlation_id: str
    signal_action: SignalAction
    risk_decision: RiskDecision | None = None
    intent: OrderIntent | None = None
    execution: PaperExecutionResult | None = None
    reconciliation: ReconciliationReport | None = None
    outcome: str


class PaperPortfolioView(DomainModel):
    account_id: str
    balances: tuple[PaperBalance, ...]
    positions: tuple[PaperPosition, ...]
    latest_snapshot: PaperPortfolioSnapshot | None = None
