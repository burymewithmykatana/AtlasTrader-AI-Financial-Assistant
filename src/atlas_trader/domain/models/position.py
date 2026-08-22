from decimal import Decimal

from pydantic import AwareDatetime, Field

from atlas_trader.domain.models.base import ZERO, DomainModel


class Position(DomainModel):
    exchange: str
    symbol: str
    quantity: Decimal
    average_entry_price: Decimal = Field(ge=ZERO)
    realized_pnl: Decimal = ZERO
    unrealized_pnl: Decimal = ZERO
    updated_at: AwareDatetime
