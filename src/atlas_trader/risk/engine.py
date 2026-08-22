from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.system_state import SystemState
from atlas_trader.domain.interfaces.risk import RiskRule, RiskStateRepository
from atlas_trader.domain.models.base import ZERO
from atlas_trader.domain.models.risk import RiskContext, RiskDecision, RiskState


@dataclass(frozen=True, slots=True)
class SystemStateRule:
    name: str = "system_state"

    def evaluate(
        self, requested_size: Decimal, context: RiskContext, state: RiskState
    ) -> str | None:
        del requested_size, context
        if state.system_state is not SystemState.ENABLED:
            return f"system_{state.system_state.value}"
        return None


@dataclass(frozen=True, slots=True)
class MaxPositionRule:
    maximum_pct: Decimal
    name: str = "max_position"

    def evaluate(
        self, requested_size: Decimal, context: RiskContext, state: RiskState
    ) -> str | None:
        del state
        projected = context.position_quantity
        projected += requested_size if context.side is OrderSide.BUY else -requested_size
        if projected < ZERO:
            return "insufficient_position"
        if projected * context.reference_price > context.portfolio_equity * self.maximum_pct:
            return "max_position_exceeded"
        return None


@dataclass(frozen=True, slots=True)
class MaxDailyLossRule:
    maximum_pct: Decimal
    name: str = "max_daily_loss"

    def evaluate(
        self, requested_size: Decimal, context: RiskContext, state: RiskState
    ) -> str | None:
        del requested_size, context
        loss = max(-state.realized_pnl, ZERO)
        if loss >= state.starting_equity * self.maximum_pct:
            return "max_daily_loss_reached"
        return None


@dataclass(frozen=True, slots=True)
class MaxOpenPositionsRule:
    maximum: int
    name: str = "max_open_positions"

    def evaluate(
        self, requested_size: Decimal, context: RiskContext, state: RiskState
    ) -> str | None:
        del requested_size
        opening = context.side is OrderSide.BUY and context.position_quantity == ZERO
        if opening and state.open_positions >= self.maximum:
            return "max_open_positions_reached"
        return None


@dataclass(frozen=True, slots=True)
class SpreadRule:
    maximum_bps: Decimal
    name: str = "spread"

    def evaluate(
        self, requested_size: Decimal, context: RiskContext, state: RiskState
    ) -> str | None:
        del requested_size, state
        if context.spread_bps is None:
            return "spread_unavailable"
        if context.spread_bps > self.maximum_bps:
            return "spread_too_wide"
        return None


@dataclass(frozen=True, slots=True)
class StaleMarketDataRule:
    maximum_age_seconds: int
    name: str = "stale_market_data"

    def evaluate(
        self, requested_size: Decimal, context: RiskContext, state: RiskState
    ) -> str | None:
        del requested_size, state
        if context.market_data_at is None:
            return "market_data_unavailable"
        age = context.now - context.market_data_at
        if age < timedelta(0) or age > timedelta(seconds=self.maximum_age_seconds):
            return "market_data_stale"
        return None


@dataclass(frozen=True, slots=True)
class CooldownRule:
    name: str = "cooldown"

    def evaluate(
        self, requested_size: Decimal, context: RiskContext, state: RiskState
    ) -> str | None:
        del requested_size
        if state.cooldown_until is not None and context.now < state.cooldown_until:
            return "loss_cooldown_active"
        return None


@dataclass(frozen=True, slots=True)
class AvailableBalanceRule:
    name: str = "available_balance"

    def evaluate(
        self, requested_size: Decimal, context: RiskContext, state: RiskState
    ) -> str | None:
        del state
        if context.side is OrderSide.BUY:
            if requested_size * context.reference_price > context.available_quote:
                return "insufficient_quote_balance"
        elif requested_size > context.available_base:
            return "insufficient_base_balance"
        return None


class RiskEngine:
    def __init__(self, rules: tuple[RiskRule, ...]) -> None:
        self._rules = rules

    def evaluate(
        self, requested_size: Decimal, context: RiskContext, state: RiskState
    ) -> RiskDecision:
        reasons: list[str] = []
        for rule in self._rules:
            try:
                reason = rule.evaluate(requested_size, context, state)
            except Exception:
                reason = f"{rule.name}_evaluation_failed"
            if reason is not None:
                reasons.append(reason)
        approved = not reasons
        return RiskDecision(
            approved=approved,
            reasons=tuple(reasons),
            requested_size=requested_size,
            approved_size=requested_size if approved else ZERO,
            metadata={"rules_evaluated": len(self._rules)},
        )


def default_risk_engine(
    *,
    maximum_position_pct: Decimal,
    maximum_daily_loss_pct: Decimal,
    maximum_open_positions: int,
    maximum_spread_bps: Decimal,
    stale_data_seconds: int,
) -> RiskEngine:
    return RiskEngine(
        (
            SystemStateRule(),
            MaxPositionRule(maximum_position_pct),
            MaxDailyLossRule(maximum_daily_loss_pct),
            MaxOpenPositionsRule(maximum_open_positions),
            SpreadRule(maximum_spread_bps),
            StaleMarketDataRule(stale_data_seconds),
            CooldownRule(),
            AvailableBalanceRule(),
        )
    )


class RiskService:
    def __init__(self, engine: RiskEngine, repository: RiskStateRepository) -> None:
        self._engine = engine
        self._repository = repository

    async def evaluate(
        self, account_id: str, requested_size: Decimal, context: RiskContext
    ) -> RiskDecision:
        state = await self._repository.get(account_id)
        if state is None:
            return RiskDecision(
                approved=False,
                reasons=("risk_state_unavailable",),
                requested_size=requested_size,
                approved_size=ZERO,
            )
        reset = state.reset_for_day(
            context.now.date(), equity=context.portfolio_equity, now=context.now
        )
        if reset != state:
            await self._repository.save(reset)
        return self._engine.evaluate(requested_size, context, reset)
