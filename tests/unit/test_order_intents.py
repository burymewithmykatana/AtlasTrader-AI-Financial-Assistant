import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from atlas_trader.application.orders import OrderIntentService
from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.order_type import OrderType
from atlas_trader.domain.exceptions import IdempotencyConflictError, InvalidOrderStateError
from atlas_trader.domain.models.order import OrderIntent, OrderIntentStatus
from atlas_trader.domain.models.risk import RiskDecision

NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)


class MemoryOrderIntentRepository:
    def __init__(self) -> None:
        self.values: dict[str, OrderIntent] = {}
        self.lock = asyncio.Lock()

    async def create_or_get(self, intent: OrderIntent) -> tuple[OrderIntent, bool]:
        async with self.lock:
            existing = self.values.get(intent.client_order_id)
            if existing is None:
                self.values[intent.client_order_id] = intent
                return intent, True
            if existing.execution_signature() != intent.execution_signature():
                raise IdempotencyConflictError(
                    "client_order_id was reused with different execution parameters"
                )
            return existing, False

    async def get(self, intent_id: UUID) -> OrderIntent | None:
        return next((value for value in self.values.values() if value.id == intent_id), None)

    async def list(self, *, limit: int = 100) -> list[OrderIntent]:
        return list(self.values.values())[:limit]

    async def update_status(self, intent: OrderIntent, expected_status: OrderIntentStatus) -> bool:
        current = self.values[intent.client_order_id]
        if current.status is not expected_status:
            return False
        self.values[intent.client_order_id] = intent
        return True


def approved() -> RiskDecision:
    return RiskDecision(
        approved=True,
        requested_size=Decimal("1"),
        approved_size=Decimal("1"),
    )


async def create(service: OrderIntentService) -> tuple[OrderIntent, bool]:
    return await service.create(
        signal_id=None,
        exchange="mock",
        symbol="BTC-USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        reference_price=Decimal("100"),
        limit_price=None,
        strategy="ema_atr",
        strategy_version="1",
        risk_decision=approved(),
        correlation_id="cycle-1",
        now=NOW,
    )


@pytest.mark.asyncio
async def test_normal_creation_and_exact_retry_reuse_intent() -> None:
    repository = MemoryOrderIntentRepository()
    service = OrderIntentService(repository)

    first, first_created = await create(service)
    retry, retry_created = await create(service)

    assert first_created is True
    assert retry_created is False
    assert retry.id == first.id
    assert len(first.client_order_id) == 32
    assert len(repository.values) == 1


@pytest.mark.asyncio
async def test_concurrent_exact_retries_create_one_intent() -> None:
    repository = MemoryOrderIntentRepository()
    service = OrderIntentService(repository)

    results = await asyncio.gather(*(create(service) for _ in range(10)))

    assert sum(created for _, created in results) == 1
    assert len({intent.id for intent, _ in results}) == 1


@pytest.mark.asyncio
async def test_conflicting_retry_is_explicit() -> None:
    repository = MemoryOrderIntentRepository()
    original, _ = await create(OrderIntentService(repository))
    conflicting = original.model_copy(update={"requested_quantity": Decimal("2")})

    with pytest.raises(IdempotencyConflictError, match="different execution parameters"):
        await repository.create_or_get(conflicting)


def test_intent_state_transitions_are_validated() -> None:
    repository = MemoryOrderIntentRepository()
    intent = asyncio.run(create(OrderIntentService(repository)))[0]

    executing = intent.transition_to(OrderIntentStatus.EXECUTING, at=NOW)
    filled = executing.transition_to(OrderIntentStatus.FILLED, at=NOW)

    assert filled.status is OrderIntentStatus.FILLED
    with pytest.raises(InvalidOrderStateError, match="cannot transition"):
        filled.transition_to(OrderIntentStatus.EXECUTING, at=NOW)
