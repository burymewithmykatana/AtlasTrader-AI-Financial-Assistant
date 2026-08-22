from datetime import datetime
from decimal import Decimal
from uuid import UUID

from atlas_trader.domain.enums.execution_mode import ExecutionMode
from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.order_type import OrderType
from atlas_trader.domain.interfaces.orders import OrderIntentRepository
from atlas_trader.domain.models.order import (
    OrderIntent,
    OrderIntentStatus,
    deterministic_client_order_id,
)
from atlas_trader.domain.models.risk import RiskDecision


class OrderIntentService:
    def __init__(self, repository: OrderIntentRepository) -> None:
        self._repository = repository

    async def create(
        self,
        *,
        signal_id: UUID | None,
        exchange: str,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        reference_price: Decimal,
        limit_price: Decimal | None,
        strategy: str,
        strategy_version: str,
        risk_decision: RiskDecision,
        correlation_id: str,
        now: datetime,
    ) -> tuple[OrderIntent, bool]:
        client_order_id = deterministic_client_order_id(
            signal_id,
            exchange,
            symbol,
            side.value,
            order_type.value,
            quantity.normalize(),
            limit_price.normalize() if limit_price is not None else "market",
            strategy,
            strategy_version,
            ExecutionMode.PAPER.value,
        )
        intent = OrderIntent(
            client_order_id=client_order_id,
            signal_id=signal_id,
            exchange=exchange,
            symbol=symbol,
            side=side,
            order_type=order_type,
            requested_quantity=quantity,
            requested_notional=quantity * reference_price,
            limit_price=limit_price,
            reference_price=reference_price,
            execution_mode=ExecutionMode.PAPER,
            trading_mode=ExecutionMode.PAPER,
            execution_model="paper_market_snapshot",
            strategy=strategy,
            strategy_version=strategy_version,
            risk_decision=risk_decision,
            status=(
                OrderIntentStatus.APPROVED if risk_decision.approved else OrderIntentStatus.REJECTED
            ),
            correlation_id=correlation_id,
            created_at=now,
            updated_at=now,
        )
        return await self._repository.create_or_get(intent)
