from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_trader.domain.enums.execution_mode import ExecutionMode
from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.order_type import OrderType
from atlas_trader.domain.exceptions import IdempotencyConflictError
from atlas_trader.domain.metadata import Metadata
from atlas_trader.domain.models.order import OrderIntent, OrderIntentStatus
from atlas_trader.domain.models.risk import RiskDecision
from atlas_trader.infrastructure.database.models import OrderIntentRecord
from atlas_trader.infrastructure.database.repositories.common import (
    decode_metadata,
    encode_metadata,
)


class SqlAlchemyOrderIntentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_or_get(self, intent: OrderIntent) -> tuple[OrderIntent, bool]:
        statement = (
            insert(OrderIntentRecord)
            .values(**self._values(intent))
            .on_conflict_do_nothing(constraint="uq_order_intents_client_order_id")
            .returning(OrderIntentRecord.id)
        )
        inserted_id = await self._session.scalar(statement)
        if inserted_id is not None:
            return intent, True
        record = await self._session.scalar(
            select(OrderIntentRecord).where(
                OrderIntentRecord.client_order_id == intent.client_order_id
            )
        )
        if record is None:
            raise RuntimeError("conflicting intent disappeared during idempotency check")
        existing = self._to_domain(record)
        if existing.execution_signature() != intent.execution_signature():
            raise IdempotencyConflictError(
                "client_order_id was reused with different execution parameters"
            )
        return existing, False

    async def get(self, intent_id: UUID) -> OrderIntent | None:
        record = await self._session.get(OrderIntentRecord, intent_id)
        return None if record is None else self._to_domain(record)

    async def list(self, *, limit: int = 100) -> list[OrderIntent]:
        records = await self._session.scalars(
            select(OrderIntentRecord).order_by(OrderIntentRecord.created_at.desc()).limit(limit)
        )
        return [self._to_domain(record) for record in records]

    async def update_status(self, intent: OrderIntent, expected_status: OrderIntentStatus) -> bool:
        result = await self._session.execute(
            update(OrderIntentRecord)
            .where(
                OrderIntentRecord.id == intent.id,
                OrderIntentRecord.status == expected_status.value,
            )
            .values(status=intent.status.value, updated_at=intent.updated_at)
        )
        return bool(result.rowcount == 1)  # type: ignore[attr-defined]

    @staticmethod
    def _values(intent: OrderIntent) -> dict[str, object]:
        risk: Metadata = {
            "approved": intent.risk_decision.approved,
            "reasons": list(intent.risk_decision.reasons),
            "requested_size": intent.risk_decision.requested_size,
            "approved_size": intent.risk_decision.approved_size,
            "metadata": intent.risk_decision.metadata,
        }
        return {
            "id": intent.id,
            "client_order_id": intent.client_order_id,
            "signal_id": intent.signal_id,
            "exchange": intent.exchange,
            "symbol": intent.symbol,
            "side": intent.side.value,
            "order_type": intent.order_type.value,
            "requested_quantity": intent.requested_quantity,
            "requested_notional": intent.requested_notional,
            "limit_price": intent.limit_price,
            "reference_price": intent.reference_price,
            "execution_mode": intent.execution_mode.value,
            "trading_mode": intent.trading_mode.value,
            "execution_model": intent.execution_model,
            "strategy": intent.strategy,
            "strategy_version": intent.strategy_version,
            "risk_decision": encode_metadata(risk),
            "status": intent.status.value,
            "correlation_id": intent.correlation_id,
            "metadata_": encode_metadata(intent.metadata),
            "created_at": intent.created_at,
            "updated_at": intent.updated_at,
        }

    @staticmethod
    def _to_domain(record: OrderIntentRecord) -> OrderIntent:
        risk = decode_metadata(record.risk_decision)
        reasons = risk["reasons"]
        metadata = risk["metadata"]
        if not isinstance(reasons, list) or not isinstance(metadata, dict):
            raise ValueError("invalid persisted risk decision")
        decision = RiskDecision(
            approved=cast(bool, risk["approved"]),
            reasons=tuple(cast(list[str], reasons)),
            requested_size=cast(Decimal, risk["requested_size"]),
            approved_size=cast(Decimal, risk["approved_size"]),
            metadata=metadata,
        )
        return OrderIntent(
            id=record.id,
            client_order_id=record.client_order_id,
            signal_id=record.signal_id,
            exchange=record.exchange,
            symbol=record.symbol,
            side=OrderSide(record.side),
            order_type=OrderType(record.order_type),
            requested_quantity=record.requested_quantity,
            requested_notional=record.requested_notional,
            limit_price=record.limit_price,
            reference_price=record.reference_price,
            execution_mode=ExecutionMode(record.execution_mode),
            trading_mode=ExecutionMode(record.trading_mode),
            execution_model=record.execution_model,
            strategy=record.strategy,
            strategy_version=record.strategy_version,
            risk_decision=decision,
            status=OrderIntentStatus(record.status),
            correlation_id=record.correlation_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            metadata=decode_metadata(record.metadata_),
        )
