from typing import Protocol
from uuid import UUID

from atlas_trader.domain.models.order import OrderIntent, OrderIntentStatus


class OrderIntentRepository(Protocol):
    async def create_or_get(self, intent: OrderIntent) -> tuple[OrderIntent, bool]: ...

    async def get(self, intent_id: UUID) -> OrderIntent | None: ...

    async def list(self, *, limit: int = 100) -> list[OrderIntent]: ...

    async def update_status(
        self, intent: OrderIntent, expected_status: OrderIntentStatus
    ) -> bool: ...
