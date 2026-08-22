from datetime import UTC, datetime, timedelta
from decimal import Decimal

from atlas_trader.domain.enums.signal_action import SignalAction
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.models.candle import Candle
from atlas_trader.strategies.ema_atr import EmaAtrStrategy, atr, ema


def make_candles(closes: list[str]) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Candle(
            exchange="mock",
            symbol="BTC-USDT",
            timeframe=Timeframe.ONE_HOUR,
            timestamp=start + timedelta(hours=index),
            open=Decimal(close),
            high=Decimal(close) + Decimal("2"),
            low=Decimal(close) - Decimal("2"),
            close=Decimal(close),
            volume=Decimal("1"),
        )
        for index, close in enumerate(closes)
    ]


def test_ema_decimal_calculation() -> None:
    result = ema([Decimal("1"), Decimal("2"), Decimal("3")], period=2)

    assert result == [None, Decimal("1.5"), Decimal("2.5")]


def test_atr_decimal_calculation() -> None:
    candles = make_candles(["100", "105", "103"])
    result = atr(candles, period=2)

    assert result[1] == Decimal("5.5")
    assert result[2] == Decimal("4.75")


def test_strategy_signal_is_deterministic() -> None:
    candles = make_candles([str(100 + index) for index in range(30)])
    strategy = EmaAtrStrategy()

    first = strategy.evaluate(candles)
    second = strategy.evaluate(list(candles))

    assert first == second
    assert first.action in {SignalAction.BUY, SignalAction.SELL, SignalAction.HOLD}
    assert isinstance(first.reference_price, Decimal)
    assert all(not isinstance(value, float) for value in first.metadata.values())


def test_future_candle_cannot_change_historical_signal() -> None:
    candles = make_candles([str(100 + index) for index in range(40)])
    strategy = EmaAtrStrategy()
    historical_slice = candles[:30]
    before = strategy.evaluate(historical_slice)
    candles[39] = candles[39].model_copy(
        update={"high": Decimal("1000000"), "close": Decimal("999999")}
    )
    after = strategy.evaluate(candles[:30])

    assert before == after


def test_strategy_parameters_are_explicit_and_decimal_safe() -> None:
    strategy = EmaAtrStrategy.from_parameters(
        {
            "fast_period": 3,
            "slow_period": 5,
            "atr_period": 4,
            "atr_stop_multiple": "1.5",
        }
    )

    assert strategy.parameters == {
        "fast_period": 3,
        "slow_period": 5,
        "atr_period": 4,
        "atr_stop_multiple": Decimal("1.5"),
    }
