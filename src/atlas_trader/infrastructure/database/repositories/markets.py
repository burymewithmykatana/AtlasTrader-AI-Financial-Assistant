from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_trader.domain.enums.asset_class import AssetClass
from atlas_trader.domain.enums.market_status import MarketStatus
from atlas_trader.domain.models.market import Market
from atlas_trader.infrastructure.database.models import MarketRecord
from atlas_trader.infrastructure.database.repositories.common import UpsertStats


class SqlAlchemyMarketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def reconcile(self, exchange: str, markets: list[Market]) -> UpsertStats:
        symbols = {market.symbol for market in markets}
        existing = set(
            await self._session.scalars(
                select(MarketRecord.symbol).where(MarketRecord.exchange == exchange)
            )
        )
        now = datetime.now(UTC)
        for market in markets:
            values = {
                "exchange": market.exchange,
                "symbol": market.symbol,
                "base_asset": market.base_asset,
                "quote_asset": market.quote_asset,
                "price_precision": market.price_precision,
                "amount_precision": market.amount_precision,
                "min_order_amount": market.min_order_amount,
                "price_step": market.price_step,
                "amount_step": market.amount_step,
                "status": MarketStatus.ACTIVE.value,
                "base_asset_class": market.base_asset_class.value,
                "quote_asset_class": market.quote_asset_class.value,
                "metadata": market.metadata,
                "active": True,
                "last_seen_at": now,
                "updated_at": now,
            }
            statement = insert(MarketRecord).values(**values)
            await self._session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_markets_exchange_symbol",
                    set_={
                        key: value
                        for key, value in values.items()
                        if key not in {"exchange", "symbol"}
                    },
                )
            )

        deactivate = update(MarketRecord).where(MarketRecord.exchange == exchange)
        if symbols:
            deactivate = deactivate.where(MarketRecord.symbol.not_in(symbols))
        await self._session.execute(
            deactivate.values(
                active=False,
                status=MarketStatus.INACTIVE.value,
                updated_at=now,
            )
        )
        return UpsertStats(
            inserted=len(symbols - existing),
            updated=len(symbols & existing),
        )

    async def list(self, *, active_only: bool = False) -> list[Market]:
        statement = select(MarketRecord).order_by(MarketRecord.exchange, MarketRecord.symbol)
        if active_only:
            statement = statement.where(MarketRecord.active.is_(True))
        records = (await self._session.scalars(statement)).all()
        return [self._to_domain(record) for record in records]

    @staticmethod
    def _to_domain(record: MarketRecord) -> Market:
        return Market(
            exchange=record.exchange,
            symbol=record.symbol,
            base_asset=record.base_asset,
            quote_asset=record.quote_asset,
            price_precision=record.price_precision,
            amount_precision=record.amount_precision,
            min_order_amount=record.min_order_amount,
            price_step=record.price_step,
            amount_step=record.amount_step,
            status=MarketStatus(record.status),
            base_asset_class=AssetClass(record.base_asset_class),
            quote_asset_class=AssetClass(record.quote_asset_class),
            metadata=record.metadata_,
            active=record.active,
        )
