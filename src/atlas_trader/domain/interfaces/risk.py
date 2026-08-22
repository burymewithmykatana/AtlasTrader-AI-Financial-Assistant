from decimal import Decimal
from typing import Protocol

from pydantic import Field

from atlas_trader.domain.metadata import Metadata
from atlas_trader.domain.models.base import ZERO, DomainModel
from atlas_trader.domain.models.signal import Signal


class RiskDecision(DomainModel):
    approved: bool
    reasons: tuple[str, ...] = ()
    requested_size: Decimal = Field(ge=ZERO)
    approved_size: Decimal = Field(ge=ZERO)
    metadata: Metadata = Field(default_factory=dict)


class RiskRule(Protocol):
    name: str

    async def evaluate(self, signal: Signal, requested_size: Decimal) -> RiskDecision: ...
