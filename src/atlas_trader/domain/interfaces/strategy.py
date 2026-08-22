from typing import Protocol

from atlas_trader.domain.models.candle import Candle
from atlas_trader.domain.models.signal import Signal


class Strategy(Protocol):
    name: str
    version: str

    @property
    def required_history(self) -> int: ...

    def evaluate(self, candles: list[Candle]) -> Signal: ...
