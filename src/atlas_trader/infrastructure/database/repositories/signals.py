from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_trader.domain.enums.signal_action import SignalAction
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.models.signal import Signal
from atlas_trader.infrastructure.database.models import SignalRecord
from atlas_trader.infrastructure.database.repositories.common import (
    UpsertStats,
    decode_metadata,
    encode_metadata,
)


class SqlAlchemySignalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, signal: Signal) -> UpsertStats:
        values = {
            "strategy_name": signal.strategy,
            "strategy_version": signal.strategy_version,
            "exchange": signal.exchange,
            "symbol": signal.symbol,
            "timeframe": signal.timeframe.value,
            "candle_open_time": signal.candle_timestamp,
            "action": signal.action.value,
            "score": signal.score,
            "reference_price": signal.reference_price,
            "stop_price": signal.stop_price,
            "metadata_": encode_metadata(signal.metadata),
        }
        statement = (
            insert(SignalRecord)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_signals_identity")
            .returning(SignalRecord.id)
        )
        inserted_id = await self._session.scalar(statement)
        inserted = 1 if inserted_id is not None else 0
        return UpsertStats(inserted=inserted, updated=0)

    async def get_stored(self, signal_id: UUID) -> Signal | None:
        record = await self._session.get(SignalRecord, signal_id)
        return None if record is None else self._to_domain(record)

    async def list(self, *, limit: int = 100) -> list[tuple[UUID, Signal]]:
        records = await self._session.scalars(
            select(SignalRecord).order_by(SignalRecord.created_at.desc()).limit(limit)
        )
        return [(record.id, self._to_domain(record)) for record in records]

    @staticmethod
    def _to_domain(record: SignalRecord) -> Signal:
        return Signal(
            strategy=record.strategy_name,
            strategy_version=record.strategy_version,
            exchange=record.exchange,
            symbol=record.symbol,
            timeframe=Timeframe(record.timeframe),
            candle_timestamp=record.candle_open_time,
            action=SignalAction(record.action),
            score=record.score,
            reference_price=record.reference_price,
            stop_price=record.stop_price,
            metadata=decode_metadata(record.metadata_),
        )
