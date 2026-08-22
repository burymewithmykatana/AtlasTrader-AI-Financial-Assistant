from typing import Protocol

from atlas_trader.domain.models.event import SystemEvent


class SystemEventRepository(Protocol):
    async def append(self, event: SystemEvent) -> None: ...

    async def list(self, *, correlation_id: str | None = None) -> list[SystemEvent]: ...
