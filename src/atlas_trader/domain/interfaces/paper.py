from typing import Protocol
from uuid import UUID

from atlas_trader.domain.models.order import OrderIntent
from atlas_trader.domain.models.paper import (
    PaperBalance,
    PaperFill,
    PaperPortfolioSnapshot,
    PaperPosition,
)


class PaperPortfolioRepository(Protocol):
    async def get_balance(self, account_id: str, asset: str) -> PaperBalance | None: ...

    async def set_balance(self, balance: PaperBalance) -> None: ...

    async def get_position(
        self, account_id: str, exchange: str, symbol: str
    ) -> PaperPosition | None: ...

    async def get_fill_for_intent(self, intent_id: UUID) -> PaperFill | None: ...

    async def list_balances(self, account_id: str) -> list[PaperBalance]: ...

    async def list_positions(self, account_id: str) -> list[PaperPosition]: ...

    async def list_fills(self, account_id: str) -> list[PaperFill]: ...

    async def apply_execution(
        self,
        intent: OrderIntent,
        fill: PaperFill,
        balance: PaperBalance,
        position: PaperPosition,
        snapshot: PaperPortfolioSnapshot,
    ) -> tuple[PaperFill, bool]: ...

    async def latest_snapshot(self, account_id: str) -> PaperPortfolioSnapshot | None: ...
