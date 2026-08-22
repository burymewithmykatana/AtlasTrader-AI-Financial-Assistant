from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_trader.domain.enums.system_state import SystemState
from atlas_trader.domain.models.risk import RiskState
from atlas_trader.infrastructure.database.models import RiskStateRecord


class SqlAlchemyRiskStateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, account_id: str) -> RiskState | None:
        record = await self._session.get(RiskStateRecord, account_id)
        if record is None:
            return None
        return RiskState(
            account_id=record.account_id,
            system_state=SystemState(record.system_state),
            trading_day=record.trading_day,
            starting_equity=record.starting_equity,
            realized_pnl=record.realized_pnl,
            peak_equity=record.peak_equity,
            drawdown=record.drawdown,
            cooldown_until=record.cooldown_until,
            open_positions=record.open_positions,
            updated_at=record.updated_at,
        )

    async def save(self, state: RiskState) -> None:
        values = {
            "account_id": state.account_id,
            "system_state": state.system_state.value,
            "trading_day": state.trading_day,
            "starting_equity": state.starting_equity,
            "realized_pnl": state.realized_pnl,
            "peak_equity": state.peak_equity,
            "drawdown": state.drawdown,
            "cooldown_until": state.cooldown_until,
            "open_positions": state.open_positions,
            "updated_at": state.updated_at,
        }
        statement = insert(RiskStateRecord).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[RiskStateRecord.account_id],
            set_={key: value for key, value in values.items() if key != "account_id"},
        )
        await self._session.execute(statement)
