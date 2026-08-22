from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from atlas_trader.application.admin import AdminStateService
from atlas_trader.application.reconciliation import PaperReconciliationService
from atlas_trader.domain.enums.execution_mode import ExecutionMode
from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.order_type import OrderType
from atlas_trader.domain.enums.system_state import SystemState
from atlas_trader.domain.exceptions import InvalidSystemStateTransitionError
from atlas_trader.domain.models.event import SystemEvent
from atlas_trader.domain.models.order import (
    OrderIntent,
    OrderIntentStatus,
    deterministic_client_order_id,
)
from atlas_trader.domain.models.paper import (
    PaperBalance,
    PaperFill,
    PaperPortfolioSnapshot,
    PaperPosition,
)
from atlas_trader.domain.models.risk import RiskDecision, RiskState

NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)


class MemoryRiskStates:
    def __init__(self) -> None:
        self.value = RiskState(
            account_id="paper:default",
            trading_day=NOW.date(),
            starting_equity=Decimal("1000"),
            peak_equity=Decimal("1000"),
            updated_at=NOW,
        )

    async def get(self, account_id: str) -> RiskState | None:
        return self.value if account_id == self.value.account_id else None

    async def save(self, state: RiskState) -> None:
        self.value = state


class MemoryEvents:
    def __init__(self) -> None:
        self.values: list[SystemEvent] = []

    async def append(self, event: SystemEvent) -> None:
        self.values.append(event)

    async def list(self, *, correlation_id: str | None = None) -> list[SystemEvent]:
        return [
            event
            for event in self.values
            if correlation_id is None or event.correlation_id == correlation_id
        ]


@pytest.mark.asyncio
async def test_transition_matrix_audit_and_restart_persistence() -> None:
    states = MemoryRiskStates()
    events = MemoryEvents()
    service = AdminStateService(states, events, account_id="paper:default")
    assert (
        await service.pause(
            reason="operator requested",
            operator_id="operator-1",
            correlation_id="admin-cycle",
            now=NOW,
        )
    ).system_state is SystemState.PAUSED
    assert (
        await service.resume(
            reason="operator requested",
            operator_id="operator-1",
            correlation_id="admin-cycle",
            now=NOW,
        )
    ).system_state is SystemState.ENABLED
    assert (
        await service.kill(
            reason="operator requested",
            operator_id="operator-1",
            correlation_id="admin-cycle",
            now=NOW,
        )
    ).system_state is SystemState.KILLED
    with pytest.raises(InvalidSystemStateTransitionError):
        await service.resume(
            reason="routine resume",
            operator_id="operator-1",
            correlation_id="admin-cycle",
            now=NOW,
        )

    restarted = AdminStateService(states, events, account_id="paper:default")
    assert (await restarted.status()).system_state is SystemState.KILLED
    assert (
        await restarted.reset_killed(
            reason="explicit operator reset",
            operator_id="operator-1",
            correlation_id="admin-cycle",
            now=NOW,
        )
    ).system_state is SystemState.PAUSED
    assert (
        await restarted.resume(
            reason="resume after review",
            operator_id="operator-1",
            correlation_id="admin-cycle",
            now=NOW,
        )
    ).system_state is SystemState.ENABLED
    assert [event.payload["to"] for event in events.values] == [
        "paused",
        "enabled",
        "killed",
        "paused",
        "enabled",
    ]


def filled_intent() -> OrderIntent:
    decision = RiskDecision(
        approved=True,
        requested_size=Decimal("1"),
        approved_size=Decimal("1"),
    )
    return OrderIntent(
        client_order_id=deterministic_client_order_id("reconcile", NOW),
        exchange="mock",
        symbol="BTC-USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        requested_quantity=Decimal("1"),
        requested_notional=Decimal("100"),
        reference_price=Decimal("100"),
        execution_mode=ExecutionMode.PAPER,
        trading_mode=ExecutionMode.PAPER,
        execution_model="paper_market_snapshot",
        strategy="test",
        risk_decision=decision,
        status=OrderIntentStatus.FILLED,
        correlation_id="cycle-reconcile",
        created_at=NOW,
        updated_at=NOW,
    )


class MemoryIntents:
    def __init__(self, intent: OrderIntent | None = None) -> None:
        self.intent = intent

    async def get(self, intent_id: UUID) -> OrderIntent | None:
        return self.intent if self.intent is not None and self.intent.id == intent_id else None

    async def create_or_get(self, intent: OrderIntent) -> tuple[OrderIntent, bool]:
        self.intent = intent
        return intent, True

    async def list(self, *, limit: int = 100) -> list[OrderIntent]:
        del limit
        return [] if self.intent is None else [self.intent]

    async def update_status(self, intent: OrderIntent, expected_status: OrderIntentStatus) -> bool:
        del expected_status
        self.intent = intent
        return True


class ReconciliationPortfolio:
    def __init__(self) -> None:
        self.balance = PaperBalance(
            account_id="paper:default", asset="USDT", available=Decimal("900"), updated_at=NOW
        )
        self.positions: list[PaperPosition] = []
        self.fills: list[PaperFill] = []

    async def list_balances(self, account_id: str) -> list[PaperBalance]:
        return [self.balance]

    async def list_positions(self, account_id: str) -> list[PaperPosition]:
        return self.positions

    async def list_fills(self, account_id: str) -> list[PaperFill]:
        return self.fills

    async def get_balance(self, account_id: str, asset: str) -> PaperBalance | None:
        return self.balance

    async def set_balance(self, balance: PaperBalance) -> None:
        self.balance = balance

    async def get_position(
        self, account_id: str, exchange: str, symbol: str
    ) -> PaperPosition | None:
        return self.positions[0] if self.positions else None

    async def get_fill_for_intent(self, intent_id: UUID) -> PaperFill | None:
        return next((fill for fill in self.fills if fill.intent_id == intent_id), None)

    async def apply_execution(
        self,
        intent: OrderIntent,
        fill: PaperFill,
        balance: PaperBalance,
        position: PaperPosition,
        snapshot: PaperPortfolioSnapshot,
    ) -> tuple[PaperFill, bool]:
        del intent, balance, position, snapshot
        self.fills.append(fill)
        return fill, True

    async def latest_snapshot(self, account_id: str) -> PaperPortfolioSnapshot | None:
        return None


def reconciliation(
    intents: MemoryIntents,
    portfolio: ReconciliationPortfolio,
    states: MemoryRiskStates,
    events: MemoryEvents,
) -> PaperReconciliationService:
    return PaperReconciliationService(
        intents,
        portfolio,
        states,
        events,
        initial_quote_balance=Decimal("1000"),
        quote_asset="USDT",
    )


@pytest.mark.asyncio
async def test_reconciliation_mismatch_kills_and_recovery_never_auto_clears() -> None:
    states = MemoryRiskStates()
    events = MemoryEvents()
    portfolio = ReconciliationPortfolio()
    service = reconciliation(MemoryIntents(), portfolio, states, events)

    failed = await service.run("paper:default", correlation_id="reconcile-1", now=NOW)

    assert failed.anomalies == ("quote_balance_mismatch",)
    assert states.value.system_state is SystemState.KILLED
    portfolio.balance = portfolio.balance.model_copy(update={"available": Decimal("1000")})
    recovered = await service.run("paper:default", correlation_id="reconcile-2", now=NOW)
    assert recovered.consistent is True
    assert states.value.system_state is SystemState.KILLED


@pytest.mark.asyncio
async def test_reconciliation_detects_duplicate_fill_and_execution_event() -> None:
    order = filled_intent()
    portfolio = ReconciliationPortfolio()
    first = PaperFill(
        execution_event_id="paper_duplicate_event",
        intent_id=order.id,
        client_order_id=order.client_order_id,
        account_id="paper:default",
        exchange="mock",
        symbol="BTC-USDT",
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        price=Decimal("100"),
        notional=Decimal("100"),
        fee=Decimal("0"),
        fee_asset="USDT",
        correlation_id="cycle-reconcile",
        executed_at=NOW,
    )
    portfolio.fills = [first, first.model_copy(update={"id": first.id})]
    portfolio.balance = portfolio.balance.model_copy(update={"available": Decimal("800")})
    portfolio.positions = [
        PaperPosition(
            account_id="paper:default",
            exchange="mock",
            symbol="BTC-USDT",
            base_asset="BTC",
            quote_asset="USDT",
            quantity=Decimal("2"),
            average_cost=Decimal("100"),
            updated_at=NOW,
        )
    ]
    states = MemoryRiskStates()
    events = MemoryEvents()

    report = await reconciliation(MemoryIntents(order), portfolio, states, events).run(
        "paper:default", correlation_id="reconcile-duplicates", now=NOW
    )

    assert "duplicate_fill_for_intent" in report.anomalies
    assert "duplicate_execution_event" in report.anomalies
