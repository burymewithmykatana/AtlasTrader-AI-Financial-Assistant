from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_trader.application.admin import AdminStateService
from atlas_trader.config.settings import get_settings
from atlas_trader.domain.exceptions import InvalidSystemStateTransitionError
from atlas_trader.domain.models.risk import RiskState
from atlas_trader.infrastructure.database.repositories.events import (
    SqlAlchemySystemEventRepository,
)
from atlas_trader.infrastructure.database.repositories.risk import (
    SqlAlchemyRiskStateRepository,
)
from atlas_trader.infrastructure.database.session import get_session

router = APIRouter(prefix="/admin", tags=["admin"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class AdminTransitionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=256)
    operator_id: str = Field(min_length=1, max_length=64)


def _service(session: AsyncSession) -> AdminStateService:
    return AdminStateService(
        SqlAlchemyRiskStateRepository(session),
        SqlAlchemySystemEventRepository(session),
        account_id=get_settings().paper_account_id,
    )


def _correlation_id(request: Request) -> str:
    return str(request.state.correlation_id)


async def _run_transition(action: Awaitable[RiskState]) -> RiskState:
    try:
        return await action
    except InvalidSystemStateTransitionError as exc:
        raise HTTPException(status_code=409, detail="invalid_system_state_transition") from exc


@router.get("/status", response_model=RiskState)
async def status(session: SessionDep) -> RiskState:
    return await _run_transition(_service(session).status())


@router.post("/pause", response_model=RiskState)
async def pause(body: AdminTransitionRequest, request: Request, session: SessionDep) -> RiskState:
    return await _run_transition(
        _service(session).pause(
            reason=body.reason,
            operator_id=body.operator_id,
            correlation_id=_correlation_id(request),
            now=datetime.now(UTC),
        )
    )


@router.post("/resume", response_model=RiskState)
async def resume(body: AdminTransitionRequest, request: Request, session: SessionDep) -> RiskState:
    return await _run_transition(
        _service(session).resume(
            reason=body.reason,
            operator_id=body.operator_id,
            correlation_id=_correlation_id(request),
            now=datetime.now(UTC),
        )
    )


@router.post("/kill", response_model=RiskState)
async def kill(body: AdminTransitionRequest, request: Request, session: SessionDep) -> RiskState:
    return await _run_transition(
        _service(session).kill(
            reason=body.reason,
            operator_id=body.operator_id,
            correlation_id=_correlation_id(request),
            now=datetime.now(UTC),
        )
    )


@router.post("/reset-kill", response_model=RiskState)
async def reset_kill(
    body: AdminTransitionRequest, request: Request, session: SessionDep
) -> RiskState:
    return await _run_transition(
        _service(session).reset_killed(
            reason=body.reason,
            operator_id=body.operator_id,
            correlation_id=_correlation_id(request),
            now=datetime.now(UTC),
        )
    )
