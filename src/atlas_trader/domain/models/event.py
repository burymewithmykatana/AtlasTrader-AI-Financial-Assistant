from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field

from atlas_trader.domain.metadata import Metadata
from atlas_trader.domain.models.base import DomainModel


class SystemEvent(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    event_type: str
    correlation_id: str
    exchange: str | None = None
    symbol: str | None = None
    strategy: str | None = None
    client_order_id: str | None = None
    payload: Metadata = Field(default_factory=dict)
    created_at: AwareDatetime
