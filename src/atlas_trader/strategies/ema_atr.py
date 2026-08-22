"""Deterministic Decimal EMA/ATR architecture-validation strategy."""

from dataclasses import dataclass
from decimal import Decimal

from atlas_trader.domain.enums.signal_action import SignalAction
from atlas_trader.domain.metadata import Metadata
from atlas_trader.domain.models.candle import Candle
from atlas_trader.domain.models.signal import Signal


def ema(values: list[Decimal], period: int) -> list[Decimal | None]:
    if period < 1:
        raise ValueError("EMA period must be positive")
    output: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return output
    current = sum(values[:period], Decimal("0")) / Decimal(period)
    output[period - 1] = current
    multiplier = Decimal("2") / Decimal(period + 1)
    for index in range(period, len(values)):
        current = ((values[index] - current) * multiplier) + current
        output[index] = current
    return output


def atr(candles: list[Candle], period: int) -> list[Decimal | None]:
    if period < 1:
        raise ValueError("ATR period must be positive")
    true_ranges: list[Decimal] = []
    for index, candle in enumerate(candles):
        if index == 0:
            true_ranges.append(candle.high - candle.low)
        else:
            previous_close = candles[index - 1].close
            true_ranges.append(
                max(
                    candle.high - candle.low,
                    abs(candle.high - previous_close),
                    abs(candle.low - previous_close),
                )
            )
    output: list[Decimal | None] = [None] * len(candles)
    if len(true_ranges) < period:
        return output
    current = sum(true_ranges[:period], Decimal("0")) / Decimal(period)
    output[period - 1] = current
    for index in range(period, len(true_ranges)):
        current = ((current * Decimal(period - 1)) + true_ranges[index]) / Decimal(period)
        output[index] = current
    return output


@dataclass(frozen=True, slots=True)
class EmaAtrStrategy:
    fast_period: int = 12
    slow_period: int = 26
    atr_period: int = 14
    atr_stop_multiple: Decimal = Decimal("2")

    name = "ema_atr"
    version = "1"

    @classmethod
    def from_parameters(cls, parameters: Metadata) -> "EmaAtrStrategy":
        defaults = cls()
        allowed = {"fast_period", "slow_period", "atr_period", "atr_stop_multiple"}
        unknown = set(parameters) - allowed
        if unknown:
            raise ValueError(f"unknown EMA/ATR parameters: {', '.join(sorted(unknown))}")

        integer_parameters: dict[str, int] = {}
        for name in ("fast_period", "slow_period", "atr_period"):
            if name not in parameters:
                continue
            value = parameters[name]
            if type(value) is not int:
                raise ValueError(f"{name} must be an integer")
            integer_parameters[name] = value

        stop_multiple = defaults.atr_stop_multiple
        if "atr_stop_multiple" in parameters:
            value = parameters["atr_stop_multiple"]
            if isinstance(value, float) or not isinstance(value, (Decimal, int, str)):
                raise ValueError("atr_stop_multiple must be a decimal string")
            try:
                stop_multiple = Decimal(str(value))
            except ValueError as exc:
                raise ValueError("atr_stop_multiple must be a decimal string") from exc
        return cls(
            fast_period=integer_parameters.get("fast_period", defaults.fast_period),
            slow_period=integer_parameters.get("slow_period", defaults.slow_period),
            atr_period=integer_parameters.get("atr_period", defaults.atr_period),
            atr_stop_multiple=stop_multiple,
        )

    def __post_init__(self) -> None:
        if self.fast_period < 1 or self.slow_period < 2 or self.atr_period < 1:
            raise ValueError("indicator periods must be positive")
        if self.fast_period >= self.slow_period:
            raise ValueError("fast EMA period must be below slow EMA period")
        if self.atr_stop_multiple <= 0:
            raise ValueError("ATR stop multiple must be positive")

    @property
    def required_history(self) -> int:
        return max(self.slow_period + 1, self.atr_period + 1)

    @property
    def parameters(self) -> dict[str, int | Decimal]:
        return {
            "fast_period": self.fast_period,
            "slow_period": self.slow_period,
            "atr_period": self.atr_period,
            "atr_stop_multiple": self.atr_stop_multiple,
        }

    def evaluate(self, candles: list[Candle]) -> Signal:
        ordered = sorted(candles, key=lambda candle: candle.timestamp)
        if len(ordered) < self.required_history:
            raise ValueError(f"strategy requires at least {self.required_history} candles")
        if len({(c.exchange, c.symbol, c.timeframe) for c in ordered}) != 1:
            raise ValueError("strategy candles must belong to one market and timeframe")
        if len({c.timestamp for c in ordered}) != len(ordered):
            raise ValueError("strategy candles must have unique timestamps")

        closes = [candle.close for candle in ordered]
        fast_values = ema(closes, self.fast_period)
        slow_values = ema(closes, self.slow_period)
        atr_values = atr(ordered, self.atr_period)
        fast_previous, fast_current = fast_values[-2], fast_values[-1]
        slow_previous, slow_current = slow_values[-2], slow_values[-1]
        current_atr = atr_values[-1]
        if None in (fast_previous, fast_current, slow_previous, slow_current, current_atr):
            raise ValueError("indicator warm-up did not produce current values")

        assert fast_previous is not None
        assert fast_current is not None
        assert slow_previous is not None
        assert slow_current is not None
        assert current_atr is not None
        action = SignalAction.HOLD
        if fast_previous <= slow_previous and fast_current > slow_current:
            action = SignalAction.BUY
        elif fast_previous >= slow_previous and fast_current < slow_current:
            action = SignalAction.SELL

        latest = ordered[-1]
        stop_price = None
        if action is SignalAction.BUY:
            candidate = latest.close - (current_atr * self.atr_stop_multiple)
            stop_price = candidate if candidate > 0 else None
        elif action is SignalAction.SELL:
            stop_price = latest.close + (current_atr * self.atr_stop_multiple)

        return Signal(
            strategy=self.name,
            strategy_version=self.version,
            exchange=latest.exchange,
            symbol=latest.symbol,
            timeframe=latest.timeframe,
            candle_timestamp=latest.timestamp,
            action=action,
            score=(fast_current - slow_current) / latest.close,
            reference_price=latest.close,
            stop_price=stop_price,
            metadata={
                "fast_ema": fast_current,
                "slow_ema": slow_current,
                "atr": current_atr,
                "fast_period": self.fast_period,
                "slow_period": self.slow_period,
                "atr_period": self.atr_period,
            },
        )
