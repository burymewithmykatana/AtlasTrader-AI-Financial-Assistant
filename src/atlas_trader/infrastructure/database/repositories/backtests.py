import json
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_trader.domain.enums.backtest import BacktestExecutionModel, BacktestStatus
from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.models.backtest import (
    BacktestConfig,
    BacktestDataset,
    BacktestMetrics,
    BacktestResult,
    BacktestTrade,
)
from atlas_trader.infrastructure.database.models import BacktestRunRecord, BacktestTradeRecord
from atlas_trader.infrastructure.database.repositories.common import (
    decode_metadata,
    encode_metadata,
)


class SqlAlchemyBacktestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, result: BacktestResult) -> None:
        serialized = result.model_dump(mode="json")
        self._session.add(
            BacktestRunRecord(
                id=result.id,
                strategy_name=result.strategy_name,
                strategy_version=result.strategy_version,
                exchange=result.config.exchange,
                symbol=result.config.symbol,
                timeframe=result.config.timeframe.value,
                start_time=result.config.start_time,
                end_time=result.config.end_time,
                candle_count=result.dataset.candle_count,
                effective_start_time=result.dataset.effective_start_time,
                effective_end_time=result.dataset.effective_end_time,
                dataset_fingerprint=result.dataset.fingerprint,
                initial_capital=result.metrics.initial_capital,
                ending_equity=result.metrics.ending_equity,
                parameters=encode_metadata(result.strategy_parameters),
                execution_model=result.config.execution_model.value,
                fee_rate=result.config.fee_rate,
                fee_model="percentage_of_fill_notional",
                slippage_model="fixed_basis_points_adverse",
                slippage_bps=result.config.slippage_bps,
                metrics=serialized["metrics"],
                code_version=result.code_version,
                started_at=result.started_at,
                completed_at=result.completed_at,
                status=result.status.value,
            )
        )
        self._session.add_all(
            [
                BacktestTradeRecord(
                    backtest_run_id=result.id,
                    sequence=trade.sequence,
                    side=trade.side.value,
                    signal_time=trade.signal_time,
                    execution_time=trade.execution_time,
                    price=trade.price,
                    quantity=trade.quantity,
                    fee=trade.fee,
                    realized_pnl=trade.realized_pnl,
                )
                for trade in result.trades
            ]
        )

    async def get(self, run_id: UUID) -> BacktestResult | None:
        record = await self._session.get(BacktestRunRecord, run_id)
        if record is None:
            return None
        trades = (
            await self._session.scalars(
                select(BacktestTradeRecord)
                .where(BacktestTradeRecord.backtest_run_id == run_id)
                .order_by(BacktestTradeRecord.sequence)
            )
        ).all()
        return self._to_domain(record, list(trades))

    async def list(self, *, limit: int = 100) -> list[BacktestResult]:
        records = (
            await self._session.scalars(
                select(BacktestRunRecord).order_by(BacktestRunRecord.started_at.desc()).limit(limit)
            )
        ).all()
        results: list[BacktestResult] = []
        for record in records:
            result = await self.get(record.id)
            if result is not None:
                results.append(result)
        return results

    @staticmethod
    def _to_domain(
        record: BacktestRunRecord, trades: Sequence[BacktestTradeRecord]
    ) -> BacktestResult:
        config = BacktestConfig(
            exchange=record.exchange,
            symbol=record.symbol,
            timeframe=Timeframe(record.timeframe),
            start_time=record.start_time,
            end_time=record.end_time,
            initial_capital=record.initial_capital,
            fee_rate=record.fee_rate,
            slippage_bps=record.slippage_bps,
            execution_model=BacktestExecutionModel(record.execution_model),
            strategy_parameters=decode_metadata(record.parameters),
        )
        return BacktestResult(
            id=record.id,
            status=BacktestStatus(record.status),
            strategy_name=record.strategy_name,
            strategy_version=record.strategy_version,
            strategy_parameters=decode_metadata(record.parameters),
            config=config,
            dataset=BacktestDataset(
                candle_count=record.candle_count,
                effective_start_time=record.effective_start_time,
                effective_end_time=record.effective_end_time,
                fingerprint=record.dataset_fingerprint,
            ),
            metrics=BacktestMetrics.model_validate_json(json.dumps(record.metrics)),
            trades=tuple(
                BacktestTrade(
                    sequence=trade.sequence,
                    side=OrderSide(trade.side),
                    signal_time=trade.signal_time,
                    execution_time=trade.execution_time,
                    price=trade.price,
                    quantity=trade.quantity,
                    fee=trade.fee,
                    realized_pnl=trade.realized_pnl,
                )
                for trade in trades
            ),
            execution_assumptions={
                "execution_model": record.execution_model,
                "signal_execution_delay_candles": 1,
                "portfolio": "spot_long_only_single_market",
                "fee_application": "each_fill_notional",
                "fee_model": record.fee_model,
                "slippage": record.slippage_model,
            },
            code_version=record.code_version,
            started_at=record.started_at,
            completed_at=record.completed_at or record.started_at,
        )
