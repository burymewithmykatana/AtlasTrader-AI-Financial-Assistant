from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.exceptions import ReconciliationError
from atlas_trader.domain.models.order import OrderIntent, OrderIntentStatus
from atlas_trader.domain.models.paper import (
    PaperBalance,
    PaperFill,
    PaperPortfolioSnapshot,
    PaperPosition,
)
from atlas_trader.infrastructure.database.models import (
    OrderIntentRecord,
    PaperBalanceRecord,
    PaperFillRecord,
    PaperPortfolioSnapshotRecord,
    PaperPositionRecord,
)
from atlas_trader.infrastructure.database.repositories.common import (
    decode_metadata,
    encode_metadata,
)


class SqlAlchemyPaperPortfolioRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_balance(self, account_id: str, asset: str) -> PaperBalance | None:
        record = await self._session.get(PaperBalanceRecord, (account_id, asset))
        return None if record is None else self._balance(record)

    async def set_balance(self, balance: PaperBalance) -> None:
        statement = insert(PaperBalanceRecord).values(
            account_id=balance.account_id,
            asset=balance.asset,
            available=balance.available,
            updated_at=balance.updated_at,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[PaperBalanceRecord.account_id, PaperBalanceRecord.asset],
            set_={"available": balance.available, "updated_at": balance.updated_at},
        )
        await self._session.execute(statement)

    async def get_position(
        self, account_id: str, exchange: str, symbol: str
    ) -> PaperPosition | None:
        record = await self._session.scalar(
            select(PaperPositionRecord).where(
                PaperPositionRecord.account_id == account_id,
                PaperPositionRecord.exchange == exchange,
                PaperPositionRecord.symbol == symbol,
            )
        )
        return None if record is None else self._position(record)

    async def get_fill_for_intent(self, intent_id: UUID) -> PaperFill | None:
        record = await self._session.scalar(
            select(PaperFillRecord).where(PaperFillRecord.intent_id == intent_id)
        )
        return None if record is None else self._fill(record)

    async def list_balances(self, account_id: str) -> list[PaperBalance]:
        records = await self._session.scalars(
            select(PaperBalanceRecord).where(PaperBalanceRecord.account_id == account_id)
        )
        return [self._balance(record) for record in records]

    async def list_positions(self, account_id: str) -> list[PaperPosition]:
        records = await self._session.scalars(
            select(PaperPositionRecord).where(PaperPositionRecord.account_id == account_id)
        )
        return [self._position(record) for record in records]

    async def list_fills(self, account_id: str) -> list[PaperFill]:
        records = await self._session.scalars(
            select(PaperFillRecord)
            .where(PaperFillRecord.account_id == account_id)
            .order_by(PaperFillRecord.executed_at, PaperFillRecord.id)
        )
        return [self._fill(record) for record in records]

    async def apply_execution(
        self,
        intent: OrderIntent,
        fill: PaperFill,
        balance: PaperBalance,
        position: PaperPosition,
        snapshot: PaperPortfolioSnapshot,
    ) -> tuple[PaperFill, bool]:
        fill_statement = (
            insert(PaperFillRecord)
            .values(
                id=fill.id,
                execution_event_id=fill.execution_event_id,
                intent_id=fill.intent_id,
                client_order_id=fill.client_order_id,
                account_id=fill.account_id,
                exchange=fill.exchange,
                symbol=fill.symbol,
                side=fill.side.value,
                quantity=fill.quantity,
                price=fill.price,
                notional=fill.notional,
                fee=fill.fee,
                fee_asset=fill.fee_asset,
                realized_pnl=fill.realized_pnl,
                correlation_id=fill.correlation_id,
                executed_at=fill.executed_at,
                assumptions=encode_metadata(fill.assumptions),
            )
            .on_conflict_do_nothing(constraint="uq_paper_fills_intent")
            .returning(PaperFillRecord.id)
        )
        inserted_id = await self._session.scalar(fill_statement)
        if inserted_id is None:
            existing = await self.get_fill_for_intent(intent.id)
            if existing is None:
                raise ReconciliationError("duplicate paper fill could not be recovered")
            return existing, False

        await self.set_balance(balance)
        position_statement = insert(PaperPositionRecord).values(
            account_id=position.account_id,
            exchange=position.exchange,
            symbol=position.symbol,
            base_asset=position.base_asset,
            quote_asset=position.quote_asset,
            quantity=position.quantity,
            average_cost=position.average_cost,
            realized_pnl=position.realized_pnl,
            updated_at=position.updated_at,
        )
        position_statement = position_statement.on_conflict_do_update(
            constraint="uq_paper_positions_identity",
            set_={
                "quantity": position.quantity,
                "average_cost": position.average_cost,
                "realized_pnl": position.realized_pnl,
                "updated_at": position.updated_at,
            },
        )
        await self._session.execute(position_statement)
        await self._session.execute(
            insert(PaperPortfolioSnapshotRecord).values(
                id=snapshot.id,
                account_id=snapshot.account_id,
                quote_asset=snapshot.quote_asset,
                cash=snapshot.cash,
                positions_value=snapshot.positions_value,
                total_equity=snapshot.total_equity,
                realized_pnl=snapshot.realized_pnl,
                unrealized_pnl=snapshot.unrealized_pnl,
                timestamp=snapshot.timestamp,
            )
        )
        status_result = await self._session.execute(
            update(OrderIntentRecord)
            .where(
                OrderIntentRecord.id == intent.id,
                OrderIntentRecord.status == OrderIntentStatus.APPROVED.value,
            )
            .values(status=OrderIntentStatus.FILLED.value, updated_at=fill.executed_at)
        )
        if cast(CursorResult[object], status_result).rowcount != 1:
            raise ReconciliationError("paper fill could not atomically finalize its intent")
        return fill, True

    async def latest_snapshot(self, account_id: str) -> PaperPortfolioSnapshot | None:
        record = await self._session.scalar(
            select(PaperPortfolioSnapshotRecord)
            .where(PaperPortfolioSnapshotRecord.account_id == account_id)
            .order_by(PaperPortfolioSnapshotRecord.timestamp.desc())
            .limit(1)
        )
        return None if record is None else self._snapshot(record)

    @staticmethod
    def _balance(record: PaperBalanceRecord) -> PaperBalance:
        return PaperBalance(
            account_id=record.account_id,
            asset=record.asset,
            available=record.available,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _position(record: PaperPositionRecord) -> PaperPosition:
        return PaperPosition(
            account_id=record.account_id,
            exchange=record.exchange,
            symbol=record.symbol,
            base_asset=record.base_asset,
            quote_asset=record.quote_asset,
            quantity=record.quantity,
            average_cost=record.average_cost,
            realized_pnl=record.realized_pnl,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _fill(record: PaperFillRecord) -> PaperFill:
        return PaperFill(
            id=record.id,
            execution_event_id=record.execution_event_id,
            intent_id=record.intent_id,
            client_order_id=record.client_order_id,
            account_id=record.account_id,
            exchange=record.exchange,
            symbol=record.symbol,
            side=OrderSide(record.side),
            quantity=record.quantity,
            price=record.price,
            notional=record.notional,
            fee=record.fee,
            fee_asset=record.fee_asset,
            realized_pnl=record.realized_pnl,
            correlation_id=record.correlation_id,
            executed_at=record.executed_at,
            assumptions=decode_metadata(record.assumptions),
        )

    @staticmethod
    def _snapshot(record: PaperPortfolioSnapshotRecord) -> PaperPortfolioSnapshot:
        return PaperPortfolioSnapshot(
            id=record.id,
            account_id=record.account_id,
            quote_asset=record.quote_asset,
            cash=record.cash,
            positions_value=record.positions_value,
            total_equity=record.total_equity,
            realized_pnl=record.realized_pnl,
            unrealized_pnl=record.unrealized_pnl,
            timestamp=record.timestamp,
        )
