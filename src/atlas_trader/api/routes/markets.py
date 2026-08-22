from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_trader.domain.models.market import Market
from atlas_trader.infrastructure.database.repositories.markets import SqlAlchemyMarketRepository
from atlas_trader.infrastructure.database.session import get_session

router = APIRouter(prefix="/markets", tags=["market-data"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[Market])
async def list_markets(
    session: SessionDep,
    active_only: bool = False,
) -> list[Market]:
    return await SqlAlchemyMarketRepository(session).list(active_only=active_only)
