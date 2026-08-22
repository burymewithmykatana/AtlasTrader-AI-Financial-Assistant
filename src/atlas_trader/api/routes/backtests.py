from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_trader.application.backtest import BacktestEngine
from atlas_trader.domain.models.backtest import BacktestConfig, BacktestResult
from atlas_trader.infrastructure.database.repositories.backtests import (
    SqlAlchemyBacktestRepository,
)
from atlas_trader.infrastructure.database.repositories.candles import SqlAlchemyCandleRepository
from atlas_trader.infrastructure.database.session import get_session
from atlas_trader.strategies.ema_atr import EmaAtrStrategy

router = APIRouter(prefix="/backtests", tags=["backtests"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("", response_model=BacktestResult)
async def create_backtest(
    config: BacktestConfig,
    session: SessionDep,
) -> BacktestResult:
    try:
        strategy = EmaAtrStrategy.from_parameters(config.strategy_parameters)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_strategy_parameters") from exc
    candles = await SqlAlchemyCandleRepository(session).list_range(
        config.exchange,
        config.symbol,
        config.timeframe,
        config.start_time,
        config.end_time,
    )
    try:
        result = BacktestEngine().run(strategy, candles, config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_backtest_input") from exc
    await SqlAlchemyBacktestRepository(session).save(result)
    return result


@router.get("/{run_id}", response_model=BacktestResult)
async def get_backtest(
    run_id: UUID,
    session: SessionDep,
) -> BacktestResult:
    result = await SqlAlchemyBacktestRepository(session).get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="backtest_not_found")
    return result


@router.get("", response_model=list[BacktestResult])
async def list_backtests(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[BacktestResult]:
    return await SqlAlchemyBacktestRepository(session).list(limit=limit)
