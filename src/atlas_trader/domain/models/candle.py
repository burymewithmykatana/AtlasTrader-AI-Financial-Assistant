from decimal import Decimal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.models.base import ZERO, DomainModel


class Candle(DomainModel):
    exchange: str
    symbol: str
    timeframe: Timeframe
    timestamp: AwareDatetime
    close_time: AwareDatetime | None = None
    open: Decimal = Field(gt=ZERO)
    high: Decimal = Field(gt=ZERO)
    low: Decimal = Field(gt=ZERO)
    close: Decimal = Field(gt=ZERO)
    volume: Decimal = Field(ge=ZERO)

    @field_validator("timeframe", mode="before")
    @classmethod
    def parse_timeframe(cls, value: object) -> object:
        return Timeframe(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_ohlc_range(self) -> "Candle":
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be the greatest OHLC value")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be the smallest OHLC value")
        return self

    @property
    def open_time(self) -> AwareDatetime:
        return self.timestamp


class CandlePage(DomainModel):
    candles: tuple[Candle, ...]
    page: int = Field(ge=1)
    has_more: bool
    rejected: int = Field(default=0, ge=0)
