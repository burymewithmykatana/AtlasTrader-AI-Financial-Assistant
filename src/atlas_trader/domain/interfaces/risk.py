from decimal import Decimal
from typing import Protocol

from atlas_trader.domain.models.risk import RiskContext, RiskState


class RiskRule(Protocol):
    @property
    def name(self) -> str: ...

    def evaluate(
        self, requested_size: Decimal, context: RiskContext, state: RiskState
    ) -> str | None: ...


class RiskStateRepository(Protocol):
    async def get(self, account_id: str) -> RiskState | None: ...

    async def save(self, state: RiskState) -> None: ...
