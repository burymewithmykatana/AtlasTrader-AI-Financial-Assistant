from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.models.candle import Candle
from atlas_trader.infrastructure.database.models import CandleRecord
from atlas_trader.infrastructure.database.repositories.common import UpsertStats


class SqlAlchemyCandleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, candles: list[Candle]) -> UpsertStats:
        if not candles:
            return UpsertStats(inserted=0, updated=0)
        identities = {(c.exchange, c.symbol, c.timeframe.value, c.timestamp) for c in candles}
        existing: set[tuple[str, str, str, datetime]] = set()
        for exchange, symbol, timeframe, open_time in identities:
            found = await self._session.scalar(
                select(CandleRecord.id).where(
                    CandleRecord.exchange == exchange,
                    CandleRecord.symbol == symbol,
                    CandleRecord.timeframe == timeframe,
                    CandleRecord.open_time == open_time,
                )
            )
            if found is not None:
                existing.add((exchange, symbol, timeframe, open_time))

        for candle in candles:
            values = {
                "exchange": candle.exchange,
                "symbol": candle.symbol,
                "timeframe": candle.timeframe.value,
                "open_time": candle.timestamp,
                "close_time": candle.close_time,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
            }
            statement = insert(CandleRecord).values(**values)
            await self._session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_candles_identity",
                    set_={key: value for key, value in values.items() if key != "open_time"},
                )
            )
        return UpsertStats(inserted=len(identities - existing), updated=len(identities & existing))

    async def list_range(
        self,
        exchange: str,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        records = (
            await self._session.scalars(
                select(CandleRecord)
                .where(
                    CandleRecord.exchange == exchange,
                    CandleRecord.symbol == symbol,
                    CandleRecord.timeframe == timeframe.value,
                    CandleRecord.open_time >= start,
                    CandleRecord.open_time <= end,
                )
                .order_by(CandleRecord.open_time)
            )
        ).all()
        return [
            Candle(
                exchange=record.exchange,
                symbol=record.symbol,
                timeframe=Timeframe(record.timeframe),
                timestamp=record.open_time,
                close_time=record.close_time,
                open=record.open,
                high=record.high,
                low=record.low,
                close=record.close,
                volume=record.volume,
            )
            for record in records
        ]
