from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from atlas_trader.application.backtest import BacktestEngine
from atlas_trader.domain.enums.signal_action import SignalAction
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.models.backtest import BacktestConfig
from atlas_trader.domain.models.candle import Candle
from atlas_trader.domain.models.signal import Signal


def candles(opens: list[str], closes: list[str] | None = None) -> list[Candle]:
    close_values = closes or opens
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Candle(
            exchange="mock",
            symbol="BTC-USDT",
            timeframe=Timeframe.ONE_HOUR,
            timestamp=start + timedelta(hours=index),
            open=Decimal(open_price),
            high=max(Decimal(open_price), Decimal(close_values[index])) + Decimal("1"),
            low=min(Decimal(open_price), Decimal(close_values[index])) - Decimal("1"),
            close=Decimal(close_values[index]),
            volume=Decimal("1"),
        )
        for index, open_price in enumerate(opens)
    ]


@dataclass
class ScheduledStrategy:
    schedule: dict[int, SignalAction]
    name: str = "scheduled"
    version: str = "1"
    required_history: int = 1

    @property
    def parameters(self) -> dict[str, int]:
        return {"scheduled_signals": len(self.schedule)}

    def evaluate(self, available: list[Candle]) -> Signal:
        latest = available[-1]
        return Signal(
            strategy=self.name,
            strategy_version=self.version,
            exchange=latest.exchange,
            symbol=latest.symbol,
            timeframe=latest.timeframe,
            candle_timestamp=latest.timestamp,
            action=self.schedule.get(len(available) - 1, SignalAction.HOLD),
            score=Decimal("1"),
            reference_price=latest.close,
        )


def config(data: list[Candle], *, fee: str = "0", slippage: str = "0") -> BacktestConfig:
    return BacktestConfig(
        exchange="mock",
        symbol="BTC-USDT",
        timeframe=Timeframe.ONE_HOUR,
        start_time=data[0].timestamp,
        end_time=data[-1].timestamp,
        initial_capital=Decimal("1000"),
        fee_rate=Decimal(fee),
        slippage_bps=Decimal(slippage),
    )


def test_signal_executes_only_at_next_candle_open() -> None:
    data = candles(["100", "110", "120", "130"])
    result = BacktestEngine().run(
        ScheduledStrategy({0: SignalAction.BUY, 1: SignalAction.SELL}), data, config(data)
    )

    assert result.trades[0].signal_time == data[0].timestamp
    assert result.trades[0].execution_time == data[1].timestamp
    assert result.trades[0].price == data[1].open
    assert result.trades[1].signal_time == data[1].timestamp
    assert result.trades[1].execution_time == data[2].timestamp


def test_fee_accounting_and_profit_metrics() -> None:
    data = candles(["100", "100", "110", "110"])
    result = BacktestEngine().run(
        ScheduledStrategy({0: SignalAction.BUY, 1: SignalAction.SELL}),
        data,
        config(data, fee="0.01"),
    )

    buy = result.trades[0]
    sell = result.trades[1]
    assert sell.realized_pnl is not None
    assert result.metrics.total_fees == buy.fee + sell.fee
    assert result.metrics.ending_equity == Decimal("1000") + sell.realized_pnl
    assert result.metrics.gross_profit == sell.realized_pnl
    assert result.metrics.completed_trades == 1
    assert result.metrics.wins == 1


def test_adverse_slippage_reduces_result() -> None:
    data = candles(["100", "100", "110", "110"])
    strategy = ScheduledStrategy({0: SignalAction.BUY, 1: SignalAction.SELL})
    without_slippage = BacktestEngine().run(strategy, data, config(data))
    with_slippage = BacktestEngine().run(strategy, data, config(data, slippage="50"))

    assert with_slippage.trades[0].price > without_slippage.trades[0].price
    assert with_slippage.trades[1].price < without_slippage.trades[1].price
    assert with_slippage.metrics.ending_equity < without_slippage.metrics.ending_equity


def test_maximum_drawdown_calculation() -> None:
    amount, percentage = BacktestEngine._drawdown(
        [Decimal("100"), Decimal("120"), Decimal("90"), Decimal("150")]
    )

    assert amount == Decimal("30")
    assert percentage == Decimal("25")


def test_profit_factor_buy_hold_and_exposure() -> None:
    data = candles(["100", "100", "120", "120", "110", "110", "90"])
    strategy = ScheduledStrategy(
        {
            0: SignalAction.BUY,
            1: SignalAction.SELL,
            2: SignalAction.BUY,
            3: SignalAction.SELL,
        }
    )
    result = BacktestEngine().run(strategy, data, config(data))

    assert result.metrics.gross_profit > 0
    assert result.metrics.gross_loss > 0
    assert result.metrics.profit_factor == (result.metrics.gross_profit / result.metrics.gross_loss)
    assert result.metrics.buy_and_hold_return_pct == Decimal("-10.0")
    assert Decimal("0") < result.metrics.exposure_pct < Decimal("100")


def test_open_position_reports_unrealized_pnl() -> None:
    data = candles(["100", "100", "110"])
    result = BacktestEngine().run(ScheduledStrategy({0: SignalAction.BUY}), data, config(data))

    assert result.metrics.unrealized_pnl == Decimal("100")
    assert result.metrics.ending_equity == Decimal("1100")


def test_strategy_never_receives_future_candles() -> None:
    data = candles(["100", "101", "102", "103"])
    seen_lengths: list[int] = []

    @dataclass
    class InspectingStrategy(ScheduledStrategy):
        def evaluate(self, available: list[Candle]) -> Signal:
            seen_lengths.append(len(available))
            assert available[-1].timestamp == data[len(available) - 1].timestamp
            return super().evaluate(available)

    BacktestEngine().run(InspectingStrategy({}), data, config(data))

    assert seen_lengths == [1, 2, 3, 4]


def test_dataset_fingerprint_and_effective_range_are_explicit() -> None:
    data = candles(["100", "101", "102", "103"])

    result = BacktestEngine().run(ScheduledStrategy({}), data, config(data))

    assert result.dataset.candle_count == 4
    assert result.dataset.effective_start_time == data[0].timestamp
    assert result.dataset.effective_end_time == data[-1].timestamp
    assert result.dataset.fingerprint.startswith("sha256:")
    assert len(result.dataset.fingerprint) == 71
    assert result.code_version
    assert result.execution_assumptions["fee_model"] == "percentage_of_fill_notional"


def test_future_candle_mutation_cannot_change_earlier_signal_or_fill() -> None:
    data = candles([str(100 + index) for index in range(15)])
    mutated = list(data)
    future = mutated[12]
    mutated[12] = Candle(
        exchange=future.exchange,
        symbol=future.symbol,
        timeframe=future.timeframe,
        timestamp=future.timestamp,
        open=Decimal("999"),
        high=Decimal("1000"),
        low=Decimal("998"),
        close=Decimal("999"),
        volume=future.volume,
    )

    original = BacktestEngine().run(
        ScheduledStrategy({2: SignalAction.BUY, 4: SignalAction.SELL}), data, config(data)
    )
    changed = BacktestEngine().run(
        ScheduledStrategy({2: SignalAction.BUY, 4: SignalAction.SELL}),
        mutated,
        config(mutated),
    )

    assert original.trades == changed.trades
    assert original.dataset.fingerprint != changed.dataset.fingerprint


def test_identical_inputs_have_identical_reproducible_outputs() -> None:
    data = candles(["100", "100", "110", "110"])
    strategy = ScheduledStrategy({0: SignalAction.BUY, 1: SignalAction.SELL})

    first = BacktestEngine().run(strategy, data, config(data, fee="0.001", slippage="5"))
    second = BacktestEngine().run(strategy, data, config(data, fee="0.001", slippage="5"))

    assert first.model_dump(exclude={"id", "started_at", "completed_at"}) == second.model_dump(
        exclude={"id", "started_at", "completed_at"}
    )
