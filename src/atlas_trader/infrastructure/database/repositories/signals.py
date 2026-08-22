from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_trader.domain.models.signal import Signal
from atlas_trader.infrastructure.database.models import SignalRecord
from atlas_trader.infrastructure.database.repositories.common import UpsertStats, encode_metadata


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
