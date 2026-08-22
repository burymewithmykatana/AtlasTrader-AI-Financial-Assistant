from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_trader.api.dependencies import (
    create_nobitex_public_adapter,
    create_nobitex_public_client,
)
from atlas_trader.application.orders import OrderIntentService
from atlas_trader.application.paper import PaperExecutionService
from atlas_trader.application.reconciliation import PaperReconciliationService
from atlas_trader.application.trading import PaperAccountService, PaperTradingCycleService
from atlas_trader.config.settings import get_settings
from atlas_trader.domain.exceptions import AtlasTraderError
from atlas_trader.domain.models.order import OrderIntent
from atlas_trader.domain.models.paper import (
    PaperPortfolioView,
    PaperTradingCycleResult,
    ReconciliationReport,
)
from atlas_trader.infrastructure.database.repositories.events import (
    SqlAlchemySystemEventRepository,
)
from atlas_trader.infrastructure.database.repositories.markets import SqlAlchemyMarketRepository
from atlas_trader.infrastructure.database.repositories.orders import (
    SqlAlchemyOrderIntentRepository,
)
from atlas_trader.infrastructure.database.repositories.paper import (
    SqlAlchemyPaperPortfolioRepository,
)
from atlas_trader.infrastructure.database.repositories.risk import (
    SqlAlchemyRiskStateRepository,
)
from atlas_trader.infrastructure.database.repositories.signals import (
    SqlAlchemySignalRepository,
)
from atlas_trader.infrastructure.database.session import get_session
from atlas_trader.infrastructure.database.unit_of_work import SqlAlchemyTradingUnitOfWork
from atlas_trader.risk.engine import RiskService, default_risk_engine

router = APIRouter(tags=["paper-trading"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class TradingCycleRequest(BaseModel):
    signal_id: UUID
    quantity: Decimal | None = Field(default=None, gt=0)


def _correlation_id(request: Request) -> str:
    return str(request.state.correlation_id)


def _components(
    session: AsyncSession,
) -> tuple[
    SqlAlchemyOrderIntentRepository,
    SqlAlchemyPaperPortfolioRepository,
    SqlAlchemyRiskStateRepository,
    SqlAlchemySystemEventRepository,
]:
    return (
        SqlAlchemyOrderIntentRepository(session),
        SqlAlchemyPaperPortfolioRepository(session),
        SqlAlchemyRiskStateRepository(session),
        SqlAlchemySystemEventRepository(session),
    )


async def _initialize_account(
    portfolio: SqlAlchemyPaperPortfolioRepository,
    risk_states: SqlAlchemyRiskStateRepository,
    session: AsyncSession,
    now: datetime,
) -> PaperAccountService:
    settings = get_settings()
    account = PaperAccountService(
        portfolio,
        risk_states,
        account_id=settings.paper_account_id,
        quote_asset=settings.paper_quote_asset,
        initial_balance=settings.paper_initial_balance,
    )
    await account.ensure_initialized(now)
    await session.commit()
    return account


@router.post("/trading/cycle", response_model=PaperTradingCycleResult)
async def trading_cycle(
    body: TradingCycleRequest, request: Request, session: SessionDep
) -> PaperTradingCycleResult:
    settings = get_settings()
    now = datetime.now(UTC)
    intents, portfolio, risk_states, events = _components(session)
    await _initialize_account(portfolio, risk_states, session, now)
    risk = RiskService(
        default_risk_engine(
            maximum_position_pct=settings.max_position_pct,
            maximum_daily_loss_pct=settings.max_daily_loss_pct,
            maximum_open_positions=settings.max_open_positions,
            maximum_spread_bps=Decimal(settings.max_spread_bps),
            stale_data_seconds=settings.stale_data_seconds,
        ),
        risk_states,
    )
    reconciliation = PaperReconciliationService(
        intents,
        portfolio,
        risk_states,
        events,
        initial_quote_balance=settings.paper_initial_balance,
        quote_asset=settings.paper_quote_asset,
    )
    client = create_nobitex_public_client(settings)
    try:
        async with client:
            service = PaperTradingCycleService(
                signals=SqlAlchemySignalRepository(session),
                markets=SqlAlchemyMarketRepository(session),
                quotes=create_nobitex_public_adapter(client, settings),
                risk=risk,
                intents=OrderIntentService(intents),
                execution=PaperExecutionService(
                    intents,
                    portfolio,
                    risk_states,
                    fee_rate=settings.paper_fee_rate,
                    slippage_bps=settings.paper_slippage_bps,
                ),
                reconciliation=reconciliation,
                portfolio=portfolio,
                events=events,
                unit_of_work=SqlAlchemyTradingUnitOfWork(session),
                account_id=settings.paper_account_id,
                mode=settings.trading_mode,
                cooldown_minutes=settings.cooldown_minutes,
            )
            return await service.run(
                body.signal_id,
                body.quantity or settings.paper_default_order_quantity,
                correlation_id=_correlation_id(request),
                now=now,
            )
    except AtlasTraderError as exc:
        raise HTTPException(status_code=409, detail="paper_trading_cycle_rejected") from exc


@router.get("/orders", response_model=list[OrderIntent])
async def orders(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[OrderIntent]:
    return await SqlAlchemyOrderIntentRepository(session).list(limit=limit)


@router.get("/portfolio", response_model=PaperPortfolioView)
async def portfolio(session: SessionDep) -> PaperPortfolioView:
    now = datetime.now(UTC)
    _, paper, risk_states, _ = _components(session)
    account = await _initialize_account(paper, risk_states, session, now)
    return await account.view()


@router.post("/trading/reconcile", response_model=ReconciliationReport)
async def reconcile(request: Request, session: SessionDep) -> ReconciliationReport:
    settings = get_settings()
    now = datetime.now(UTC)
    intents, portfolio, risk_states, events = _components(session)
    await _initialize_account(portfolio, risk_states, session, now)
    report = await PaperReconciliationService(
        intents,
        portfolio,
        risk_states,
        events,
        initial_quote_balance=settings.paper_initial_balance,
        quote_asset=settings.paper_quote_asset,
    ).run(settings.paper_account_id, correlation_id=_correlation_id(request), now=now)
    await session.commit()
    return report
