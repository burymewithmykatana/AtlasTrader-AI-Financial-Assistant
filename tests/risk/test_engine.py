from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.system_state import SystemState
from atlas_trader.domain.interfaces.risk import RiskRule
from atlas_trader.domain.models.risk import RiskContext, RiskState
from atlas_trader.risk.engine import (
    AvailableBalanceRule,
    CooldownRule,
    MaxDailyLossRule,
    MaxOpenPositionsRule,
    MaxPositionRule,
    RiskEngine,
    RiskService,
    SpreadRule,
    StaleMarketDataRule,
    SystemStateRule,
    default_risk_engine,
)

NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)


def state(**updates: object) -> RiskState:
    values: dict[str, object] = {
        "account_id": "paper:default",
        "system_state": SystemState.ENABLED,
        "trading_day": NOW.date(),
        "starting_equity": Decimal("1000"),
        "realized_pnl": Decimal("0"),
        "peak_equity": Decimal("1000"),
        "drawdown": Decimal("0"),
        "open_positions": 0,
        "updated_at": NOW,
    }
    values.update(updates)
    return RiskState.model_validate(values)


def context(**updates: object) -> RiskContext:
    values: dict[str, object] = {
        "side": OrderSide.BUY,
        "reference_price": Decimal("100"),
        "position_quantity": Decimal("0"),
        "portfolio_equity": Decimal("1000"),
        "available_quote": Decimal("1000"),
        "available_base": Decimal("10"),
        "spread_bps": Decimal("10"),
        "market_data_at": NOW,
        "now": NOW,
    }
    values.update(updates)
    return RiskContext.model_validate(values)


@pytest.mark.parametrize(
    ("rule", "requested", "ctx", "risk_state", "reason"),
    [
        (
            SystemStateRule(),
            "1",
            context(),
            state(system_state=SystemState.PAUSED),
            "system_paused",
        ),
        (MaxPositionRule(Decimal("0.10")), "2", context(), state(), "max_position_exceeded"),
        (
            MaxDailyLossRule(Decimal("0.01")),
            "1",
            context(),
            state(realized_pnl=Decimal("-10")),
            "max_daily_loss_reached",
        ),
        (
            MaxOpenPositionsRule(3),
            "1",
            context(),
            state(open_positions=3),
            "max_open_positions_reached",
        ),
        (
            SpreadRule(Decimal("40")),
            "1",
            context(spread_bps=Decimal("41")),
            state(),
            "spread_too_wide",
        ),
        (
            StaleMarketDataRule(90),
            "1",
            context(market_data_at=NOW - timedelta(seconds=91)),
            state(),
            "market_data_stale",
        ),
        (
            CooldownRule(),
            "1",
            context(),
            state(cooldown_until=NOW + timedelta(minutes=1)),
            "loss_cooldown_active",
        ),
        (
            AvailableBalanceRule(),
            "1",
            context(available_quote=Decimal("99")),
            state(),
            "insufficient_quote_balance",
        ),
    ],
)
def test_each_risk_rule_rejects_independently(
    rule: RiskRule,
    requested: str,
    ctx: RiskContext,
    risk_state: RiskState,
    reason: str,
) -> None:
    assert rule.evaluate(Decimal(requested), ctx, risk_state) == reason


def test_missing_market_data_and_combined_reasons_fail_closed() -> None:
    engine = default_risk_engine(
        maximum_position_pct=Decimal("0.10"),
        maximum_daily_loss_pct=Decimal("0.01"),
        maximum_open_positions=3,
        maximum_spread_bps=Decimal("40"),
        stale_data_seconds=90,
    )

    decision = engine.evaluate(
        Decimal("2"),
        context(spread_bps=None, market_data_at=None, available_quote=Decimal("1")),
        state(system_state=SystemState.KILLED, realized_pnl=Decimal("-10"), open_positions=3),
    )

    assert decision.approved is False
    assert decision.approved_size == Decimal("0")
    assert decision.reasons == (
        "system_killed",
        "max_position_exceeded",
        "max_daily_loss_reached",
        "max_open_positions_reached",
        "spread_unavailable",
        "market_data_unavailable",
        "insufficient_quote_balance",
    )


@dataclass(frozen=True)
class BrokenRule:
    name: str = "broken"

    def evaluate(self, requested_size: Decimal, context: RiskContext, state: RiskState) -> str:
        del requested_size, context, state
        raise RuntimeError("dependency failed")


def test_rule_exception_fails_closed() -> None:
    decision = RiskEngine((BrokenRule(),)).evaluate(Decimal("1"), context(), state())

    assert decision.reasons == ("broken_evaluation_failed",)
    assert decision.approved is False


class MemoryRiskRepository:
    def __init__(self, value: RiskState | None) -> None:
        self.value = value
        self.saved: list[RiskState] = []

    async def get(self, account_id: str) -> RiskState | None:
        assert account_id == "paper:default"
        return self.value

    async def save(self, value: RiskState) -> None:
        self.value = value
        self.saved.append(value)


@pytest.mark.asyncio
async def test_risk_state_resets_for_new_day_and_is_persisted() -> None:
    previous = state(
        trading_day=date(2026, 8, 22),
        realized_pnl=Decimal("-5"),
        cooldown_until=NOW + timedelta(minutes=2),
    )
    repository = MemoryRiskRepository(previous)
    service = RiskService(RiskEngine(()), repository)

    decision = await service.evaluate("paper:default", Decimal("1"), context())

    assert decision.approved is True
    assert repository.saved[0].trading_day == NOW.date()
    assert repository.saved[0].realized_pnl == Decimal("0")
    assert repository.saved[0].cooldown_until is None


@pytest.mark.asyncio
async def test_missing_persistent_risk_state_fails_closed() -> None:
    decision = await RiskService(RiskEngine(()), MemoryRiskRepository(None)).evaluate(
        "paper:default", Decimal("1"), context()
    )

    assert decision.reasons == ("risk_state_unavailable",)
