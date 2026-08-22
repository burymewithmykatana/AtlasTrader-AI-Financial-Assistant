from datetime import date
from decimal import Decimal

from pydantic import AwareDatetime, Field, model_validator

from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.system_state import SystemState
from atlas_trader.domain.metadata import Metadata
from atlas_trader.domain.models.base import ZERO, DomainModel


class RiskState(DomainModel):
    account_id: str = Field(min_length=1, max_length=64)
    system_state: SystemState = SystemState.ENABLED
    trading_day: date
    starting_equity: Decimal = Field(gt=ZERO)
    realized_pnl: Decimal = ZERO
    peak_equity: Decimal = Field(gt=ZERO)
    drawdown: Decimal = Field(default=ZERO, ge=ZERO)
    cooldown_until: AwareDatetime | None = None
    open_positions: int = Field(default=0, ge=0)
    updated_at: AwareDatetime

    def reset_for_day(self, day: date, *, equity: Decimal, now: AwareDatetime) -> "RiskState":
        if day == self.trading_day:
            return self
        return self.model_copy(
            update={
                "trading_day": day,
                "starting_equity": equity,
                "realized_pnl": ZERO,
                "peak_equity": equity,
                "drawdown": ZERO,
                "cooldown_until": None,
                "updated_at": now,
            }
        )


class RiskContext(DomainModel):
    side: OrderSide
    reference_price: Decimal = Field(gt=ZERO)
    position_quantity: Decimal = Field(default=ZERO, ge=ZERO)
    portfolio_equity: Decimal = Field(gt=ZERO)
    available_quote: Decimal = Field(default=ZERO, ge=ZERO)
    available_base: Decimal = Field(default=ZERO, ge=ZERO)
    spread_bps: Decimal | None = Field(default=None, ge=ZERO)
    market_data_at: AwareDatetime | None = None
    now: AwareDatetime


class RiskDecision(DomainModel):
    approved: bool
    reasons: tuple[str, ...] = ()
    requested_size: Decimal = Field(gt=ZERO)
    approved_size: Decimal = Field(ge=ZERO)
    metadata: Metadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_decision(self) -> "RiskDecision":
        if self.approved and (self.reasons or self.approved_size <= ZERO):
            raise ValueError("approved decisions require positive size and no rejection reasons")
        if not self.approved and self.approved_size != ZERO:
            raise ValueError("rejected decisions must approve zero size")
        return self
