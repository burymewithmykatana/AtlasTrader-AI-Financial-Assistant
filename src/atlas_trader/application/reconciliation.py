from datetime import datetime
from decimal import Decimal

from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.system_state import SystemState
from atlas_trader.domain.interfaces.events import SystemEventRepository
from atlas_trader.domain.interfaces.orders import OrderIntentRepository
from atlas_trader.domain.interfaces.paper import PaperPortfolioRepository
from atlas_trader.domain.interfaces.risk import RiskStateRepository
from atlas_trader.domain.models.event import SystemEvent
from atlas_trader.domain.models.order import OrderIntentStatus
from atlas_trader.domain.models.paper import ReconciliationReport


class PaperReconciliationService:
    def __init__(
        self,
        intents: OrderIntentRepository,
        portfolio: PaperPortfolioRepository,
        risk_states: RiskStateRepository,
        events: SystemEventRepository,
        *,
        initial_quote_balance: Decimal,
        quote_asset: str,
    ) -> None:
        self._intents = intents
        self._portfolio = portfolio
        self._risk_states = risk_states
        self._events = events
        self._initial_quote_balance = initial_quote_balance
        self._quote_asset = quote_asset

    async def run(
        self, account_id: str, *, correlation_id: str, now: datetime
    ) -> ReconciliationReport:
        fills = await self._portfolio.list_fills(account_id)
        balances = {item.asset: item for item in await self._portfolio.list_balances(account_id)}
        positions = {
            (item.exchange, item.symbol): item
            for item in await self._portfolio.list_positions(account_id)
        }
        anomalies: list[str] = []
        seen_intents: set[object] = set()
        seen_events: set[str] = set()
        expected_cash = self._initial_quote_balance
        expected_quantities: dict[tuple[str, str], Decimal] = {}

        for fill in fills:
            if fill.intent_id in seen_intents:
                anomalies.append("duplicate_fill_for_intent")
            seen_intents.add(fill.intent_id)
            if fill.execution_event_id in seen_events:
                anomalies.append("duplicate_execution_event")
            seen_events.add(fill.execution_event_id)
            intent = await self._intents.get(fill.intent_id)
            if intent is None:
                anomalies.append("fill_without_intent")
            elif intent.status is not OrderIntentStatus.FILLED:
                anomalies.append("fill_intent_status_mismatch")
            key = (fill.exchange, fill.symbol)
            quantity = expected_quantities.get(key, Decimal("0"))
            if fill.side is OrderSide.BUY:
                quantity += fill.quantity
                expected_cash -= fill.notional + fill.fee
            else:
                quantity -= fill.quantity
                expected_cash += fill.notional - fill.fee
            if quantity < 0:
                anomalies.append("fill_history_has_negative_position")
            expected_quantities[key] = quantity

        quote_balance = balances.get(self._quote_asset)
        if quote_balance is None:
            anomalies.append("quote_balance_missing")
        elif quote_balance.available != expected_cash:
            anomalies.append("quote_balance_mismatch")
        for key, expected in expected_quantities.items():
            position = positions.get(key)
            actual = Decimal("0") if position is None else position.quantity
            if actual != expected:
                anomalies.append(f"position_quantity_mismatch:{key[0]}:{key[1]}")
        for key, position in positions.items():
            if key not in expected_quantities and position.quantity != 0:
                anomalies.append(f"position_without_fill:{key[0]}:{key[1]}")

        unique_anomalies = tuple(dict.fromkeys(anomalies))
        report = ReconciliationReport(
            account_id=account_id,
            consistent=not unique_anomalies,
            anomalies=unique_anomalies,
            fill_count=len(fills),
            checked_at=now,
        )
        await self._events.append(
            SystemEvent(
                event_type=(
                    "paper.reconciliation_succeeded"
                    if report.consistent
                    else "paper.reconciliation_failed"
                ),
                correlation_id=correlation_id,
                payload={"account_id": account_id, "anomalies": list(report.anomalies)},
                created_at=now,
            )
        )
        if not report.consistent:
            state = await self._risk_states.get(account_id)
            if state is not None and state.system_state is not SystemState.KILLED:
                await self._risk_states.save(
                    state.model_copy(update={"system_state": SystemState.KILLED, "updated_at": now})
                )
        return report
