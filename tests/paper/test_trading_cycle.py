from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from atlas_trader.application.orders import OrderIntentService
from atlas_trader.application.trading import PaperTradingCycleService
from atlas_trader.domain.enums.execution_mode import ExecutionMode
from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.signal_action import SignalAction
from atlas_trader.domain.enums.system_state import SystemState
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.exceptions import IdempotencyConflictError, PaperExecutionRejectedError
from atlas_trader.domain.models.event import SystemEvent
from atlas_trader.domain.models.market import Market, Ticker
from atlas_trader.domain.models.order import OrderIntent, OrderIntentStatus
from atlas_trader.domain.models.paper import (
    PaperBalance,
    PaperExecutionResult,
    PaperFill,
    PaperPortfolioSnapshot,
    PaperPosition,
    ReconciliationReport,
)
from atlas_trader.domain.models.risk import RiskState
from atlas_trader.domain.models.signal import Signal
from atlas_trader.risk.engine import RiskService, default_risk_engine

NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)


class MemoryIntentRepository:
    def __init__(self) -> None:
        self.by_id: dict[UUID, OrderIntent] = {}
        self.by_client: dict[str, UUID] = {}

    async def create_or_get(self, intent: OrderIntent) -> tuple[OrderIntent, bool]:
        existing_id = self.by_client.get(intent.client_order_id)
        if existing_id is not None:
            existing = self.by_id[existing_id]
            if existing.execution_signature() != intent.execution_signature():
                raise IdempotencyConflictError("different execution parameters")
            return existing, False
        self.by_id[intent.id] = intent
        self.by_client[intent.client_order_id] = intent.id
        return intent, True

    async def get(self, intent_id: UUID) -> OrderIntent | None:
        return self.by_id.get(intent_id)

    async def list(self, *, limit: int = 100) -> list[OrderIntent]:
        return list(self.by_id.values())[:limit]

    async def update_status(self, intent: OrderIntent, expected_status: OrderIntentStatus) -> bool:
        current = self.by_id[intent.id]
        if current.status is not expected_status:
            return False
        self.by_id[intent.id] = intent
        return True


class MemoryPortfolio:
    def __init__(self) -> None:
        self.balance = PaperBalance(
            account_id="paper:default",
            asset="USDT",
            available=Decimal("1000"),
            updated_at=NOW,
        )
        self.position: PaperPosition | None = None

    async def get_balance(self, account_id: str, asset: str) -> PaperBalance | None:
        return self.balance

    async def set_balance(self, balance: PaperBalance) -> None:
        self.balance = balance

    async def get_position(
        self, account_id: str, exchange: str, symbol: str
    ) -> PaperPosition | None:
        return self.position

    async def get_fill_for_intent(self, intent_id: UUID) -> PaperFill | None:
        return None

    async def list_balances(self, account_id: str) -> list[PaperBalance]:
        return [self.balance]

    async def list_positions(self, account_id: str) -> list[PaperPosition]:
        return [] if self.position is None else [self.position]

    async def list_fills(self, account_id: str) -> list[PaperFill]:
        return []

    async def apply_execution(
        self,
        intent: OrderIntent,
        fill: PaperFill,
        balance: PaperBalance,
        position: PaperPosition,
        snapshot: PaperPortfolioSnapshot,
    ) -> tuple[PaperFill, bool]:
        del intent, balance, position, snapshot
        return fill, True

    async def latest_snapshot(self, account_id: str) -> PaperPortfolioSnapshot | None:
        return None


class MemoryRiskStates:
    def __init__(self, system_state: SystemState = SystemState.ENABLED) -> None:
        self.value = RiskState(
            account_id="paper:default",
            system_state=system_state,
            trading_day=NOW.date(),
            starting_equity=Decimal("1000"),
            peak_equity=Decimal("1000"),
            updated_at=NOW,
        )

    async def get(self, account_id: str) -> RiskState | None:
        return self.value

    async def save(self, state: RiskState) -> None:
        self.value = state


class MemoryEvents:
    def __init__(self) -> None:
        self.values: list[SystemEvent] = []

    async def append(self, event: SystemEvent) -> None:
        self.values.append(event)

    async def list(self, *, correlation_id: str | None = None) -> list[SystemEvent]:
        return self.values


class FakeSignals:
    def __init__(self, signal_id: UUID, signal: Signal) -> None:
        self.signal_id = signal_id
        self.signal = signal

    async def get_stored(self, signal_id: UUID) -> Signal | None:
        return self.signal if signal_id == self.signal_id else None


class FakeMarkets:
    async def get(self, exchange: str, symbol: str) -> Market | None:
        return Market(
            exchange=exchange,
            symbol=symbol,
            base_asset="BTC",
            quote_asset="USDT",
            price_precision=2,
            amount_precision=8,
            min_order_amount=Decimal("0.0001"),
        )


class FakeQuotes:
    def __init__(self, *, timestamp: datetime = NOW) -> None:
        self.timestamp = timestamp

    async def get_ticker(self, symbol: str, *, correlation_id: str) -> Ticker:
        assert correlation_id == "cycle-1"
        return Ticker(
            exchange="mock",
            symbol=symbol,
            bid=Decimal("99.9"),
            ask=Decimal("100.1"),
            last=Decimal("100"),
            timestamp=self.timestamp,
        )


class FakeExecution:
    def __init__(self) -> None:
        self.results: dict[UUID, PaperExecutionResult] = {}
        self.fail = False

    async def execute(
        self,
        intent: OrderIntent,
        market: Market,
        ticker: Ticker,
        *,
        account_id: str,
        now: datetime,
    ) -> PaperExecutionResult:
        if self.fail:
            raise PaperExecutionRejectedError("injected downstream failure")
        existing = self.results.get(intent.id)
        if existing is not None:
            return existing.model_copy(update={"created": False})
        fill = PaperFill(
            execution_event_id=f"paper_{intent.client_order_id}",
            intent_id=intent.id,
            client_order_id=intent.client_order_id,
            account_id=account_id,
            exchange=intent.exchange,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.requested_quantity,
            price=ticker.last,
            notional=intent.requested_quantity * ticker.last,
            fee=Decimal("0"),
            fee_asset=market.quote_asset,
            correlation_id=intent.correlation_id,
            executed_at=now,
        )
        result = PaperExecutionResult(
            fill=fill,
            balance=PaperBalance(
                account_id=account_id,
                asset="USDT",
                available=Decimal("900"),
                updated_at=now,
            ),
            position=PaperPosition(
                account_id=account_id,
                exchange=intent.exchange,
                symbol=intent.symbol,
                base_asset="BTC",
                quote_asset="USDT",
                quantity=Decimal("1"),
                average_cost=Decimal("100"),
                updated_at=now,
            ),
            snapshot=PaperPortfolioSnapshot(
                account_id=account_id,
                quote_asset="USDT",
                cash=Decimal("900"),
                positions_value=Decimal("100"),
                total_equity=Decimal("1000"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                timestamp=now,
            ),
            created=True,
        )
        self.results[intent.id] = result
        return result


class FakeReconciliation:
    async def run(
        self, account_id: str, *, correlation_id: str, now: datetime
    ) -> ReconciliationReport:
        return ReconciliationReport(
            account_id=account_id,
            consistent=True,
            fill_count=1,
            checked_at=now,
        )


class MemoryUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def signal(action: SignalAction) -> Signal:
    return Signal(
        strategy="test",
        exchange="mock",
        symbol="BTC-USDT",
        timeframe=Timeframe.ONE_MINUTE,
        candle_timestamp=NOW,
        action=action,
        score=Decimal("1"),
        reference_price=Decimal("100"),
    )


def harness(
    action: SignalAction,
    *,
    state: SystemState = SystemState.ENABLED,
    quote_time: datetime = NOW,
) -> tuple[
    PaperTradingCycleService,
    UUID,
    MemoryIntentRepository,
    FakeExecution,
    MemoryUnitOfWork,
    MemoryEvents,
    MemoryPortfolio,
]:
    signal_id = uuid4()
    intents = MemoryIntentRepository()
    execution = FakeExecution()
    unit = MemoryUnitOfWork()
    events = MemoryEvents()
    portfolio = MemoryPortfolio()
    states = MemoryRiskStates(state)
    risk = RiskService(
        default_risk_engine(
            maximum_position_pct=Decimal("1"),
            maximum_daily_loss_pct=Decimal("0.5"),
            maximum_open_positions=3,
            maximum_spread_bps=Decimal("40"),
            stale_data_seconds=90,
        ),
        states,
    )
    service = PaperTradingCycleService(
        signals=FakeSignals(signal_id, signal(action)),
        markets=FakeMarkets(),
        quotes=FakeQuotes(timestamp=quote_time),
        risk=risk,
        intents=OrderIntentService(intents),
        execution=execution,
        reconciliation=FakeReconciliation(),
        portfolio=portfolio,
        events=events,
        unit_of_work=unit,
        account_id="paper:default",
        mode=ExecutionMode.PAPER,
        cooldown_minutes=60,
    )
    return service, signal_id, intents, execution, unit, events, portfolio


@pytest.mark.asyncio
async def test_buy_cycle_checkpoints_intent_executes_and_propagates_correlation() -> None:
    service, signal_id, intents, execution, unit, events, _ = harness(SignalAction.BUY)

    result = await service.run(signal_id, Decimal("1"), correlation_id="cycle-1", now=NOW)

    assert result.outcome == "filled"
    assert result.intent is not None and result.intent.risk_decision.approved is True
    assert len(intents.by_id) == 1
    assert len(execution.results) == 1
    assert unit.commits == 3
    assert all(event.correlation_id == "cycle-1" for event in events.values)


@pytest.mark.asyncio
async def test_hold_creates_no_intent_or_fill() -> None:
    service, signal_id, intents, execution, _, _, _ = harness(SignalAction.HOLD)

    result = await service.run(signal_id, Decimal("1"), correlation_id="cycle-1", now=NOW)

    assert result.outcome == "hold"
    assert intents.by_id == {}
    assert execution.results == {}


@pytest.mark.asyncio
async def test_stale_data_rejection_is_persisted_without_fill() -> None:
    service, signal_id, intents, execution, _, _, _ = harness(
        SignalAction.BUY, quote_time=NOW - timedelta(seconds=91)
    )

    result = await service.run(signal_id, Decimal("1"), correlation_id="cycle-1", now=NOW)

    assert result.outcome == "risk_rejected"
    assert next(iter(intents.by_id.values())).status is OrderIntentStatus.REJECTED
    assert execution.results == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [SystemState.PAUSED, SystemState.KILLED])
async def test_pause_and_kill_reject_cycle(state: SystemState) -> None:
    service, signal_id, _, execution, _, _, _ = harness(SignalAction.BUY, state=state)

    result = await service.run(signal_id, Decimal("1"), correlation_id="cycle-1", now=NOW)

    assert result.outcome == "risk_rejected"
    assert execution.results == {}


@pytest.mark.asyncio
async def test_duplicate_cycle_retry_reuses_intent_and_fill() -> None:
    service, signal_id, intents, execution, _, _, _ = harness(SignalAction.BUY)

    first = await service.run(signal_id, Decimal("1"), correlation_id="cycle-1", now=NOW)
    retry = await service.run(signal_id, Decimal("1"), correlation_id="cycle-1", now=NOW)

    assert first.intent is not None and retry.intent is not None
    assert first.intent.id == retry.intent.id
    assert retry.execution is not None and retry.execution.created is False
    assert len(intents.by_id) == len(execution.results) == 1


@pytest.mark.asyncio
async def test_sell_cycle_uses_existing_position() -> None:
    service, signal_id, _, execution, _, _, portfolio = harness(SignalAction.SELL)
    portfolio.position = PaperPosition(
        account_id="paper:default",
        exchange="mock",
        symbol="BTC-USDT",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("1"),
        average_cost=Decimal("90"),
        updated_at=NOW,
    )

    result = await service.run(signal_id, Decimal("1"), correlation_id="cycle-1", now=NOW)

    assert result.outcome == "filled"
    assert next(iter(execution.results.values())).fill.side is OrderSide.SELL


@pytest.mark.asyncio
async def test_downstream_failure_preserves_intent_and_retry_recovers() -> None:
    service, signal_id, intents, execution, unit, _, _ = harness(SignalAction.BUY)
    execution.fail = True

    with pytest.raises(PaperExecutionRejectedError, match="failed safely"):
        await service.run(signal_id, Decimal("1"), correlation_id="cycle-1", now=NOW)

    assert len(intents.by_id) == 1
    assert execution.results == {}
    assert unit.rollbacks == 1
    execution.fail = False
    recovered = await service.run(signal_id, Decimal("1"), correlation_id="cycle-1", now=NOW)
    assert recovered.outcome == "filled"
