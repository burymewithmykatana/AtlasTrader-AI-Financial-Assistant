from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_trader.domain.models.signal import Signal
from atlas_trader.infrastructure.database.repositories.signals import (
    SqlAlchemySignalRepository,
)
from atlas_trader.infrastructure.database.session import get_session

router = APIRouter(prefix="/signals", tags=["strategies"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class StoredSignalResponse(BaseModel):
    id: UUID
    signal: Signal


@router.get("", response_model=list[StoredSignalResponse])
async def list_signals(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[StoredSignalResponse]:
    values = await SqlAlchemySignalRepository(session).list(limit=limit)
    return [StoredSignalResponse(id=signal_id, signal=signal) for signal_id, signal in values]
