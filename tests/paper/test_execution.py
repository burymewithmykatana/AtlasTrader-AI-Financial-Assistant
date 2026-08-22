from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from atlas_trader.application.paper import PaperExecutionService
from atlas_trader.domain.enums.execution_mode import ExecutionMode
from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.order_type import OrderType
from atlas_trader.domain.enums.system_state import SystemState
from atlas_trader.domain.exceptions import PaperExecutionRejectedError
from atlas_trader.domain.models.market import Market, Ticker
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
        assert account_id == self.value.account_id
        return self.value

    async def save(self, state: RiskState) -> None:
        self.value = state


class MemoryIntents:
    def __init__(self) -> None:
        self.values: dict[UUID, OrderIntent] = {}

    async def create_or_get(self, intent: OrderIntent) -> tuple[OrderIntent, bool]:
        existing = self.values.get(intent.id)
        if existing is not None:
            return existing, False
        self.values[intent.id] = intent
        return intent, True

    async def get(self, intent_id: UUID) -> OrderIntent | None:
        return self.values.get(intent_id)

    async def list(self, *, limit: int = 100) -> list[OrderIntent]:
        return list(self.values.values())[:limit]

    async def update_status(self, intent: OrderIntent, expected_status: OrderIntentStatus) -> bool:
        del expected_status
        self.values[intent.id] = intent
        return True


class MemoryPortfolio:
    def __init__(self, balance: PaperBalance) -> None:
        self.balances = {(balance.account_id, balance.asset): balance}
        self.positions: dict[tuple[str, str, str], PaperPosition] = {}
        self.fills: dict[UUID, PaperFill] = {}
        self.snapshots: list[PaperPortfolioSnapshot] = []

    async def get_balance(self, account_id: str, asset: str) -> PaperBalance | None:
        return self.balances.get((account_id, asset))

    async def set_balance(self, balance: PaperBalance) -> None:
        self.balances[(balance.account_id, balance.asset)] = balance

    async def get_position(
        self, account_id: str, exchange: str, symbol: str
    ) -> PaperPosition | None:
        return self.positions.get((account_id, exchange, symbol))

    async def get_fill_for_intent(self, intent_id: UUID) -> PaperFill | None:
        return self.fills.get(intent_id)

    async def list_balances(self, account_id: str) -> list[PaperBalance]:
        return [
            balance
            for (stored_account, _), balance in self.balances.items()
            if stored_account == account_id
        ]

    async def list_positions(self, account_id: str) -> list[PaperPosition]:
        return [
            position
            for (stored_account, _, _), position in self.positions.items()
            if stored_account == account_id
        ]

    async def list_fills(self, account_id: str) -> list[PaperFill]:
        return [fill for fill in self.fills.values() if fill.account_id == account_id]

    async def apply_execution(
        self,
        intent: OrderIntent,
        fill: PaperFill,
        balance: PaperBalance,
        position: PaperPosition,
        snapshot: PaperPortfolioSnapshot,
    ) -> tuple[PaperFill, bool]:
        existing = self.fills.get(intent.id)
        if existing is not None:
            return existing, False
        self.fills[intent.id] = fill
        await self.set_balance(balance)
        self.positions[(position.account_id, position.exchange, position.symbol)] = position
        self.snapshots.append(snapshot)
        return fill, True

    async def latest_snapshot(self, account_id: str) -> PaperPortfolioSnapshot | None:
        return next(
            (item for item in reversed(self.snapshots) if item.account_id == account_id), None
        )


def market() -> Market:
    return Market(
        exchange="mock",
        symbol="BTC-USDT",
        base_asset="BTC",
        quote_asset="USDT",
        price_precision=2,
        amount_precision=8,
        min_order_amount=Decimal("0.0001"),
    )


def ticker(price: str) -> Ticker:
    value = Decimal(price)
    return Ticker(
        exchange="mock",
        symbol="BTC-USDT",
        bid=value,
        ask=value,
        last=value,
        timestamp=NOW,
    )


def intent(side: OrderSide, quantity: str = "1") -> OrderIntent:
    size = Decimal(quantity)
    client_id = deterministic_client_order_id(side, quantity, NOW.isoformat())
    return OrderIntent(
        client_order_id=client_id,
        exchange="mock",
        symbol="BTC-USDT",
        side=side,
        order_type=OrderType.MARKET,
        requested_quantity=size,
        requested_notional=size * Decimal("100"),
        reference_price=Decimal("100"),
        execution_mode=ExecutionMode.PAPER,
        trading_mode=ExecutionMode.PAPER,
        execution_model="paper_market_snapshot",
        strategy="test",
        risk_decision=RiskDecision(
            approved=True,
            requested_size=size,
            approved_size=size,
        ),
        status=OrderIntentStatus.APPROVED,
        correlation_id=f"cycle-{side.value}",
        created_at=NOW,
        updated_at=NOW,
    )


async def setup(cash: str = "1000") -> tuple[MemoryIntents, MemoryPortfolio]:
    intents = MemoryIntents()
    portfolio = MemoryPortfolio(
        PaperBalance(
            account_id="paper:default",
            asset="USDT",
            available=Decimal(cash),
            updated_at=NOW,
        )
    )
    return intents, portfolio


@pytest.mark.asyncio
async def test_buy_applies_adverse_slippage_and_fee_with_decimal_accounting() -> None:
    intents, portfolio = await setup()
    order = intent(OrderSide.BUY)
    intents.values[order.id] = order
    service = PaperExecutionService(
        intents,
        portfolio,
        MemoryRiskStates(),
        fee_rate=Decimal("0.01"),
        slippage_bps=Decimal("100"),
    )

    result = await service.execute(
        order, market(), ticker("100"), account_id="paper:default", now=NOW
    )

    assert result.fill.price == Decimal("101")
    assert result.fill.fee == Decimal("1.01")
    assert result.balance.available == Decimal("897.99")
    assert result.position.quantity == Decimal("1")
    assert result.position.average_cost == Decimal("102.01")
    assert result.snapshot.total_equity == Decimal("997.99")


@pytest.mark.asyncio
async def test_profitable_sell_updates_realized_pnl_and_cash() -> None:
    intents, portfolio = await setup()
    buy = intent(OrderSide.BUY)
    intents.values[buy.id] = buy
    service = PaperExecutionService(
        intents,
        portfolio,
        MemoryRiskStates(),
        fee_rate=Decimal("0.01"),
        slippage_bps=Decimal("0"),
    )
    await service.execute(buy, market(), ticker("100"), account_id="paper:default", now=NOW)
    sell = intent(OrderSide.SELL)
    intents.values[sell.id] = sell

    result = await service.execute(
        sell, market(), ticker("110"), account_id="paper:default", now=NOW
    )

    assert result.fill.realized_pnl == Decimal("7.90")
    assert result.position.quantity == Decimal("0")
    assert result.position.average_cost == Decimal("0")
    assert result.balance.available == Decimal("1007.90")


@pytest.mark.asyncio
async def test_loss_trade_is_recorded() -> None:
    intents, portfolio = await setup()
    service = PaperExecutionService(
        intents,
        portfolio,
        MemoryRiskStates(),
        fee_rate=Decimal("0"),
        slippage_bps=Decimal("0"),
    )
    buy = intent(OrderSide.BUY)
    intents.values[buy.id] = buy
    await service.execute(buy, market(), ticker("100"), account_id="paper:default", now=NOW)
    sell = intent(OrderSide.SELL)
    intents.values[sell.id] = sell

    result = await service.execute(
        sell, market(), ticker("90"), account_id="paper:default", now=NOW
    )

    assert result.fill.realized_pnl == Decimal("-10")


@pytest.mark.asyncio
async def test_insufficient_cash_and_position_are_rejected_without_fill() -> None:
    intents, portfolio = await setup(cash="50")
    service = PaperExecutionService(
        intents,
        portfolio,
        MemoryRiskStates(),
        fee_rate=Decimal("0"),
        slippage_bps=Decimal("0"),
    )
    buy = intent(OrderSide.BUY)
    intents.values[buy.id] = buy
    with pytest.raises(PaperExecutionRejectedError, match="insufficient paper cash"):
        await service.execute(buy, market(), ticker("100"), account_id="paper:default", now=NOW)

    sell = intent(OrderSide.SELL)
    intents.values[sell.id] = sell
    with pytest.raises(PaperExecutionRejectedError, match="insufficient paper position"):
        await service.execute(sell, market(), ticker("100"), account_id="paper:default", now=NOW)
    assert portfolio.fills == {}


@pytest.mark.asyncio
async def test_duplicate_execution_and_service_restart_reuse_fill_and_state() -> None:
    intents, portfolio = await setup()
    order = intent(OrderSide.BUY)
    intents.values[order.id] = order
    first_service = PaperExecutionService(
        intents,
        portfolio,
        MemoryRiskStates(),
        fee_rate=Decimal("0"),
        slippage_bps=Decimal("0"),
    )
    first = await first_service.execute(
        order, market(), ticker("100"), account_id="paper:default", now=NOW
    )
    restarted_service = PaperExecutionService(
        intents,
        portfolio,
        MemoryRiskStates(),
        fee_rate=Decimal("0"),
        slippage_bps=Decimal("0"),
    )

    retry = await restarted_service.execute(
        order, market(), ticker("100"), account_id="paper:default", now=NOW
    )

    assert first.created is True
    assert retry.created is False
    assert retry.fill.id == first.fill.id
    assert retry.balance.available == Decimal("900")
    assert len(portfolio.fills) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_state", [SystemState.PAUSED, SystemState.KILLED])
async def test_pause_or_kill_after_approval_blocks_pending_execution(
    blocked_state: SystemState,
) -> None:
    intents, portfolio = await setup()
    order = intent(OrderSide.BUY)
    intents.values[order.id] = order
    service = PaperExecutionService(
        intents,
        portfolio,
        MemoryRiskStates(blocked_state),
        fee_rate=Decimal("0"),
        slippage_bps=Decimal("0"),
    )

    with pytest.raises(PaperExecutionRejectedError, match="system state blocks"):
        await service.execute(order, market(), ticker("100"), account_id="paper:default", now=NOW)
    assert portfolio.fills == {}
