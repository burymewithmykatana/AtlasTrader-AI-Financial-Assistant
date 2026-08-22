from decimal import Decimal

from pydantic import AwareDatetime, Field

from atlas_trader.domain.enums.execution_mode import ExecutionMode
from atlas_trader.domain.models.base import ZERO, DomainModel
from atlas_trader.domain.models.position import Position


class Balance(DomainModel):
    asset: str
    available: Decimal = Field(ge=ZERO)
    locked: Decimal = Field(default=ZERO, ge=ZERO)

    @property
    def total(self) -> Decimal:
        return self.available + self.locked


class PortfolioSnapshot(DomainModel):
    exchange: str
    mode: ExecutionMode
    balances: tuple[Balance, ...] = ()
    positions: tuple[Position, ...] = ()
    total_equity: Decimal = Field(ge=ZERO)
    timestamp: AwareDatetime
