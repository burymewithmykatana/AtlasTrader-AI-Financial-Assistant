from decimal import Decimal

from pydantic import AwareDatetime, Field, field_validator

from atlas_trader.domain.enums.signal_action import SignalAction
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.metadata import Metadata
from atlas_trader.domain.models.base import ZERO, DomainModel


class Signal(DomainModel):
    strategy: str
    strategy_version: str = "1"
    exchange: str
    symbol: str
    timeframe: Timeframe
    candle_timestamp: AwareDatetime
    action: SignalAction
    score: Decimal
    reference_price: Decimal = Field(gt=ZERO)
    stop_price: Decimal | None = Field(default=None, gt=ZERO)
    metadata: Metadata = Field(default_factory=dict)

    @field_validator("timeframe", mode="before")
    @classmethod
    def parse_timeframe(cls, value: object) -> object:
        return Timeframe(value) if isinstance(value, str) else value

    @property
    def candle_open_time(self) -> AwareDatetime:
        return self.candle_timestamp
