import asyncio
import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from atlas_trader.application.orders import OrderIntentService
from atlas_trader.application.paper import PaperExecutionService
from atlas_trader.application.reconciliation import PaperReconciliationService
from atlas_trader.application.trading import PaperAccountService, PaperTradingCycleService
from atlas_trader.domain.enums.execution_mode import ExecutionMode
from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.order_type import OrderType
from atlas_trader.domain.enums.signal_action import SignalAction
from atlas_trader.domain.enums.system_state import SystemState
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.exceptions import IdempotencyConflictError
from atlas_trader.domain.models.market import Market, MarketDiscoverySnapshot, Ticker
from atlas_trader.domain.models.order import OrderIntentStatus
from atlas_trader.domain.models.risk import RiskDecision
from atlas_trader.domain.models.signal import Signal
from atlas_trader.infrastructure.database.models import (
    OrderIntentRecord,
    PaperFillRecord,
    SignalRecord,
    SystemEventRecord,
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
from atlas_trader.infrastructure.database.unit_of_work import SqlAlchemyTradingUnitOfWork
from atlas_trader.risk.engine import RiskService, default_risk_engine

DATABASE_URL = os.getenv("PHASE2_E2E_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    DATABASE_URL is None,
    reason="PHASE2_E2E_DATABASE_URL is required for PostgreSQL release-gate tests",
)
NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)


class StaticQuoteProvider:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    async def get_ticker(self, symbol: str, *, correlation_id: str) -> Ticker:
        assert symbol == self.symbol
        assert correlation_id.startswith("e2e-")
        return Ticker(
            exchange="mock",
            symbol=symbol,
            bid=Decimal("99.9"),
            ask=Decimal("100.1"),
            last=Decimal("100"),
            timestamp=NOW,
        )


async def seed(session: AsyncSession, suffix: str) -> tuple[UUID, str, str]:
    account_id = f"paper:{suffix}"
    symbol = f"BTC-{suffix}"
    market = Market(
        exchange="mock",
        symbol=symbol,
        base_asset="BTC",
        quote_asset="USDT",
        price_precision=2,
        amount_precision=8,
        min_order_amount=Decimal("0.0001"),
    )
    await SqlAlchemyMarketRepository(session).reconcile(
        MarketDiscoverySnapshot(exchange="mock", markets=(market,), complete=True)
    )
    signal = Signal(
        strategy="e2e",
        exchange="mock",
        symbol=symbol,
        timeframe=Timeframe.ONE_MINUTE,
        candle_timestamp=NOW,
        action=SignalAction.BUY,
        score=Decimal("1"),
        reference_price=Decimal("100"),
    )
    await SqlAlchemySignalRepository(session).upsert(signal)
    signal_id = await session.scalar(
        select(SignalRecord.id).where(
            SignalRecord.exchange == "mock", SignalRecord.symbol == symbol
        )
    )
    assert signal_id is not None
    portfolio = SqlAlchemyPaperPortfolioRepository(session)
    risk_states = SqlAlchemyRiskStateRepository(session)
    await PaperAccountService(
        portfolio,
        risk_states,
        account_id=account_id,
        quote_asset="USDT",
        initial_balance=Decimal("1000"),
    ).ensure_initialized(NOW)
    await session.commit()
    return signal_id, account_id, symbol


def cycle(session: AsyncSession, account_id: str, symbol: str) -> PaperTradingCycleService:
    intents = SqlAlchemyOrderIntentRepository(session)
    portfolio = SqlAlchemyPaperPortfolioRepository(session)
    risk_states = SqlAlchemyRiskStateRepository(session)
    events = SqlAlchemySystemEventRepository(session)
    return PaperTradingCycleService(
        signals=SqlAlchemySignalRepository(session),
        markets=SqlAlchemyMarketRepository(session),
        quotes=StaticQuoteProvider(symbol),
        risk=RiskService(
            default_risk_engine(
                maximum_position_pct=Decimal("1"),
                maximum_daily_loss_pct=Decimal("0.5"),
                maximum_open_positions=3,
                maximum_spread_bps=Decimal("40"),
                stale_data_seconds=90,
            ),
            risk_states,
        ),
        intents=OrderIntentService(intents),
        execution=PaperExecutionService(
            intents,
            portfolio,
            risk_states,
            fee_rate=Decimal("0.001"),
            slippage_bps=Decimal("5"),
        ),
        reconciliation=PaperReconciliationService(
            intents,
            portfolio,
            risk_states,
            events,
            initial_quote_balance=Decimal("1000"),
            quote_asset="USDT",
        ),
        portfolio=portfolio,
        events=events,
        unit_of_work=SqlAlchemyTradingUnitOfWork(session),
        account_id=account_id,
        mode=ExecutionMode.PAPER,
        cooldown_minutes=60,
    )


@pytest.mark.asyncio
async def test_postgres_full_paper_cycle_retry_restart_and_reconciliation_failure() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex[:10]
    async with factory() as session:
        signal_id, account_id, symbol = await seed(session, suffix)
        first = await cycle(session, account_id, symbol).run(
            signal_id, Decimal("1"), correlation_id=f"e2e-{suffix}", now=NOW
        )
        assert first.outcome == "filled"
        assert first.intent is not None and first.intent.status is OrderIntentStatus.FILLED

    async with factory() as restarted_session:
        retry = await cycle(restarted_session, account_id, symbol).run(
            signal_id, Decimal("1"), correlation_id=f"e2e-{suffix}", now=NOW
        )
        assert retry.execution is not None and retry.execution.created is False
        total_fills = await restarted_session.scalar(select(func.count(PaperFillRecord.id)))
        assert total_fills is not None and total_fills >= 1
        intent_count = await restarted_session.scalar(
            select(func.count(OrderIntentRecord.id)).where(
                OrderIntentRecord.correlation_id == f"e2e-{suffix}"
            )
        )
        fill_count = await restarted_session.scalar(
            select(func.count(PaperFillRecord.id)).where(
                PaperFillRecord.correlation_id == f"e2e-{suffix}"
            )
        )
        event_count = await restarted_session.scalar(
            select(func.count(SystemEventRecord.id)).where(
                SystemEventRecord.correlation_id == f"e2e-{suffix}"
            )
        )
        assert intent_count == fill_count == 1
        assert event_count is not None and event_count >= 3

        intents = SqlAlchemyOrderIntentRepository(restarted_session)
        stored = retry.intent
        assert stored is not None
        with pytest.raises(IdempotencyConflictError):
            await intents.create_or_get(
                stored.model_copy(update={"requested_quantity": Decimal("2")})
            )
        await restarted_session.rollback()

        portfolio = SqlAlchemyPaperPortfolioRepository(restarted_session)
        balance = await portfolio.get_balance(account_id, "USDT")
        assert balance is not None
        await portfolio.set_balance(
            balance.model_copy(update={"available": balance.available + Decimal("1")})
        )
        await restarted_session.commit()
        report = await PaperReconciliationService(
            intents,
            portfolio,
            SqlAlchemyRiskStateRepository(restarted_session),
            SqlAlchemySystemEventRepository(restarted_session),
            initial_quote_balance=Decimal("1000"),
            quote_asset="USDT",
        ).run(account_id, correlation_id=f"e2e-reconcile-{suffix}", now=NOW)
        await restarted_session.commit()
        assert "quote_balance_mismatch" in report.anomalies
        risk_state = await SqlAlchemyRiskStateRepository(restarted_session).get(account_id)
        assert risk_state is not None and risk_state.system_state is SystemState.KILLED
    await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_concurrent_order_intent_retry_creates_one_row() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    symbol = f"RACE-{uuid4().hex[:10]}"
    decision = RiskDecision(
        approved=True,
        requested_size=Decimal("1"),
        approved_size=Decimal("1"),
    )

    async def worker() -> tuple[UUID, bool]:
        async with factory() as session:
            intent, created = await OrderIntentService(
                SqlAlchemyOrderIntentRepository(session)
            ).create(
                signal_id=None,
                exchange="mock",
                symbol=symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("1"),
                reference_price=Decimal("100"),
                limit_price=None,
                strategy="race",
                strategy_version="1",
                risk_decision=decision,
                correlation_id=f"e2e-race-{symbol}",
                now=NOW,
            )
            await session.commit()
            return intent.id, created

    results = await asyncio.gather(*(worker() for _ in range(5)))

    assert sum(created for _, created in results) == 1
    assert len({intent_id for intent_id, _ in results}) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_restart_recovers_persisted_intent_before_execution() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex[:10]
    async with factory() as session:
        signal_id, account_id, symbol = await seed(session, suffix)
        decision = RiskDecision(
            approved=True,
            requested_size=Decimal("1"),
            approved_size=Decimal("1"),
        )
        pending, _ = await OrderIntentService(SqlAlchemyOrderIntentRepository(session)).create(
            signal_id=signal_id,
            exchange="mock",
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
            reference_price=Decimal("100"),
            limit_price=None,
            strategy="e2e",
            strategy_version="1",
            risk_decision=decision,
            correlation_id=f"e2e-pending-{suffix}",
            now=NOW,
        )
        await session.commit()

    async with factory() as restarted_session:
        intents = SqlAlchemyOrderIntentRepository(restarted_session)
        recovered = await intents.get(pending.id)
        assert recovered is not None and recovered.status is OrderIntentStatus.APPROVED
        market = await SqlAlchemyMarketRepository(restarted_session).get("mock", symbol)
        assert market is not None
        result = await PaperExecutionService(
            intents,
            SqlAlchemyPaperPortfolioRepository(restarted_session),
            SqlAlchemyRiskStateRepository(restarted_session),
            fee_rate=Decimal("0"),
            slippage_bps=Decimal("0"),
        ).execute(
            recovered,
            market,
            await StaticQuoteProvider(symbol).get_ticker(
                symbol, correlation_id=f"e2e-pending-{suffix}"
            ),
            account_id=account_id,
            now=NOW,
        )
        await restarted_session.commit()
        assert result.created is True
        persisted = await intents.get(pending.id)
        assert persisted is not None and persisted.status is OrderIntentStatus.FILLED
    await engine.dispose()
