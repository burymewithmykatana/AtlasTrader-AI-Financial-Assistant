"""Deterministic, long-only, single-market backtesting."""

import hashlib
import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from uuid import uuid4

from atlas_trader.domain.enums.backtest import BacktestStatus
from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.signal_action import SignalAction
from atlas_trader.domain.interfaces.strategy import Strategy
from atlas_trader.domain.models.backtest import (
    BacktestConfig,
    BacktestDataset,
    BacktestMetrics,
    BacktestResult,
    BacktestTrade,
)
from atlas_trader.domain.models.candle import Candle
from atlas_trader.domain.models.signal import Signal

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
BPS_DENOMINATOR = Decimal("10000")
PERSISTED_QUANTUM = Decimal("0.000000000000000001")


def persisted_decimal(value: Decimal) -> Decimal:
    """Match PostgreSQL NUMERIC(36,18) before results cross the application boundary."""
    with localcontext() as context:
        context.prec = 60
        return value.quantize(PERSISTED_QUANTUM)


def candle_dataset_fingerprint(candles: Sequence[Candle]) -> str:
    canonical = [
        [
            candle.exchange,
            candle.symbol,
            candle.timeframe.value,
            _canonical_datetime(candle.timestamp),
            _canonical_datetime(candle.close_time) if candle.close_time is not None else None,
            _canonical_decimal(candle.open),
            _canonical_decimal(candle.high),
            _canonical_decimal(candle.low),
            _canonical_decimal(candle.close),
            _canonical_decimal(candle.volume),
        ]
        for candle in candles
    ]
    encoded = json.dumps(canonical, ensure_ascii=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _canonical_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == ZERO else format(normalized, "f")


class BacktestEngine:
    """Execute a signal from candle N no earlier than candle N+1 open."""

    def run(
        self,
        strategy: Strategy,
        candles: list[Candle],
        config: BacktestConfig,
    ) -> BacktestResult:
        started_at = datetime.now(UTC)
        ordered = sorted(
            (
                candle
                for candle in candles
                if config.start_time <= candle.timestamp <= config.end_time
            ),
            key=lambda candle: candle.timestamp,
        )
        self._validate_input(ordered, config)

        cash = config.initial_capital
        quantity = ZERO
        open_cost = ZERO
        total_fees = ZERO
        pending_signal: Signal | None = None
        trades: list[BacktestTrade] = []
        realized_results: list[Decimal] = []
        equity_curve: list[Decimal] = [config.initial_capital]
        exposed_candles = 0

        for index, candle in enumerate(ordered):
            if pending_signal is not None:
                if pending_signal.action is SignalAction.BUY and quantity == ZERO:
                    execution_price = persisted_decimal(
                        self._execution_price(candle.open, OrderSide.BUY, config.slippage_bps)
                    )
                    gross = persisted_decimal(cash / (ONE + config.fee_rate))
                    fee = persisted_decimal(gross * config.fee_rate)
                    quantity = persisted_decimal(gross / execution_price)
                    open_cost = persisted_decimal(gross + fee)
                    cash = ZERO
                    total_fees += fee
                    trades.append(
                        BacktestTrade(
                            sequence=len(trades) + 1,
                            side=OrderSide.BUY,
                            signal_time=pending_signal.candle_timestamp,
                            execution_time=candle.timestamp,
                            price=execution_price,
                            quantity=quantity,
                            fee=fee,
                        )
                    )
                elif pending_signal.action is SignalAction.SELL and quantity > ZERO:
                    execution_price = persisted_decimal(
                        self._execution_price(candle.open, OrderSide.SELL, config.slippage_bps)
                    )
                    gross = persisted_decimal(quantity * execution_price)
                    fee = persisted_decimal(gross * config.fee_rate)
                    proceeds = persisted_decimal(gross - fee)
                    realized_pnl = persisted_decimal(proceeds - open_cost)
                    cash = proceeds
                    total_fees += fee
                    trades.append(
                        BacktestTrade(
                            sequence=len(trades) + 1,
                            side=OrderSide.SELL,
                            signal_time=pending_signal.candle_timestamp,
                            execution_time=candle.timestamp,
                            price=execution_price,
                            quantity=quantity,
                            fee=fee,
                            realized_pnl=realized_pnl,
                        )
                    )
                    realized_results.append(realized_pnl)
                    quantity = ZERO
                    open_cost = ZERO

            if quantity > ZERO:
                exposed_candles += 1
            equity_curve.append(persisted_decimal(cash + (quantity * candle.close)))

            pending_signal = None
            if index + 1 >= strategy.required_history:
                pending_signal = strategy.evaluate(ordered[: index + 1])

        ending_equity = persisted_decimal(cash + (quantity * ordered[-1].close))
        metrics = self._metrics(
            config=config,
            candles=ordered,
            ending_equity=ending_equity,
            equity_curve=equity_curve,
            trades=trades,
            realized_results=realized_results,
            total_fees=total_fees,
            exposed_candles=exposed_candles,
            unrealized_pnl=(
                persisted_decimal(quantity * ordered[-1].close - open_cost)
                if quantity > ZERO
                else ZERO
            ),
        )
        parameters = getattr(strategy, "parameters", {})
        effective_config = config.model_copy(update={"strategy_parameters": dict(parameters)})
        return BacktestResult(
            id=uuid4(),
            status=BacktestStatus.COMPLETED,
            strategy_name=strategy.name,
            strategy_version=strategy.version,
            strategy_parameters=dict(parameters),
            config=effective_config,
            dataset=BacktestDataset(
                candle_count=len(ordered),
                effective_start_time=ordered[0].timestamp,
                effective_end_time=ordered[-1].timestamp,
                fingerprint=candle_dataset_fingerprint(ordered),
            ),
            metrics=metrics,
            trades=tuple(trades),
            execution_assumptions={
                "execution_model": config.execution_model.value,
                "signal_execution_delay_candles": 1,
                "portfolio": "spot_long_only_single_market",
                "fee_application": "each_fill_notional",
                "fee_model": "percentage_of_fill_notional",
                "slippage": "fixed_basis_points_adverse",
            },
            code_version=os.getenv("GIT_SHA") or "unavailable",
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )

    @staticmethod
    def _validate_input(candles: list[Candle], config: BacktestConfig) -> None:
        if not candles:
            raise ValueError("backtest requires candles in the requested period")
        if len({c.timestamp for c in candles}) != len(candles):
            raise ValueError("backtest candles must have unique timestamps")
        if any(
            c.exchange != config.exchange
            or c.symbol != config.symbol
            or c.timeframe != config.timeframe
            for c in candles
        ):
            raise ValueError("backtest candles do not match the requested market")

    @staticmethod
    def _execution_price(price: Decimal, side: OrderSide, slippage_bps: Decimal) -> Decimal:
        adjustment = slippage_bps / BPS_DENOMINATOR
        return price * (ONE + adjustment if side is OrderSide.BUY else ONE - adjustment)

    @staticmethod
    def _drawdown(equity_curve: list[Decimal]) -> tuple[Decimal, Decimal]:
        peak = equity_curve[0]
        maximum_amount = ZERO
        maximum_pct = ZERO
        for equity in equity_curve:
            peak = max(peak, equity)
            drawdown = peak - equity
            drawdown_pct = (drawdown / peak * HUNDRED) if peak > ZERO else ZERO
            maximum_amount = max(maximum_amount, drawdown)
            maximum_pct = max(maximum_pct, drawdown_pct)
        return persisted_decimal(maximum_amount), persisted_decimal(maximum_pct)

    def _metrics(
        self,
        *,
        config: BacktestConfig,
        candles: list[Candle],
        ending_equity: Decimal,
        equity_curve: list[Decimal],
        trades: list[BacktestTrade],
        realized_results: list[Decimal],
        total_fees: Decimal,
        exposed_candles: int,
        unrealized_pnl: Decimal,
    ) -> BacktestMetrics:
        entries = sum(trade.side is OrderSide.BUY for trade in trades)
        exits = sum(trade.side is OrderSide.SELL for trade in trades)
        wins = sum(result > ZERO for result in realized_results)
        losses = sum(result < ZERO for result in realized_results)
        gross_profit = sum((result for result in realized_results if result > ZERO), ZERO)
        gross_loss = sum((-result for result in realized_results if result < ZERO), ZERO)
        max_drawdown, max_drawdown_pct = self._drawdown(equity_curve)
        completed = len(realized_results)
        return BacktestMetrics(
            initial_capital=config.initial_capital,
            ending_equity=ending_equity,
            absolute_pnl=persisted_decimal(ending_equity - config.initial_capital),
            return_pct=persisted_decimal(
                ((ending_equity / config.initial_capital) - ONE) * HUNDRED
            ),
            number_of_entries=entries,
            number_of_exits=exits,
            completed_trades=completed,
            wins=wins,
            losses=losses,
            win_rate_pct=(
                persisted_decimal(Decimal(wins) / Decimal(completed) * HUNDRED)
                if completed
                else ZERO
            ),
            gross_profit=persisted_decimal(gross_profit),
            gross_loss=persisted_decimal(gross_loss),
            profit_factor=(
                persisted_decimal(gross_profit / gross_loss) if gross_loss > ZERO else None
            ),
            maximum_drawdown_amount=max_drawdown,
            maximum_drawdown_pct=max_drawdown_pct,
            total_fees=persisted_decimal(total_fees),
            unrealized_pnl=persisted_decimal(unrealized_pnl),
            buy_and_hold_return_pct=persisted_decimal(
                ((candles[-1].close / candles[0].open) - ONE) * HUNDRED
            ),
            exposure_pct=persisted_decimal(
                Decimal(exposed_candles) / Decimal(len(candles)) * HUNDRED
            ),
        )
