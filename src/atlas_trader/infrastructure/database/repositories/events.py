from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_trader.domain.models.event import SystemEvent
from atlas_trader.infrastructure.database.models import SystemEventRecord
from atlas_trader.infrastructure.database.repositories.common import (
    decode_metadata,
    encode_metadata,
)


class SqlAlchemySystemEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: SystemEvent) -> None:
        self._session.add(
            SystemEventRecord(
                id=event.id,
                event_type=event.event_type,
                correlation_id=event.correlation_id,
                exchange=event.exchange,
                symbol=event.symbol,
                strategy=event.strategy,
                client_order_id=event.client_order_id,
                payload=encode_metadata(event.payload),
                created_at=event.created_at,
            )
        )

    async def list(self, *, correlation_id: str | None = None) -> list[SystemEvent]:
        statement = select(SystemEventRecord).order_by(SystemEventRecord.created_at)
        if correlation_id is not None:
            statement = statement.where(SystemEventRecord.correlation_id == correlation_id)
        records = await self._session.scalars(statement)
        return [
            SystemEvent(
                id=record.id,
                event_type=record.event_type,
                correlation_id=record.correlation_id or "unavailable",
                exchange=record.exchange,
                symbol=record.symbol,
                strategy=record.strategy,
                client_order_id=record.client_order_id,
                payload=decode_metadata(record.payload),
                created_at=record.created_at,
            )
            for record in records
        ]
