from datetime import datetime
from decimal import Decimal
from uuid import UUID

from atlas_trader.application.orders import OrderIntentService
from atlas_trader.domain.enums.execution_mode import ExecutionMode
from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.order_type import OrderType
from atlas_trader.domain.enums.signal_action import SignalAction
from atlas_trader.domain.exceptions import AtlasTraderError, PaperExecutionRejectedError
from atlas_trader.domain.interfaces.events import SystemEventRepository
from atlas_trader.domain.interfaces.paper import PaperPortfolioRepository
from atlas_trader.domain.interfaces.risk import RiskStateRepository
from atlas_trader.domain.interfaces.trading import (
    MarketReader,
    PaperExecutor,
    PaperReconciler,
    PublicQuoteProvider,
    SignalReader,
    TradingUnitOfWork,
)
from atlas_trader.domain.models.event import SystemEvent
from atlas_trader.domain.models.paper import (
    PaperBalance,
    PaperPortfolioView,
    PaperTradingCycleResult,
)
from atlas_trader.domain.models.risk import RiskContext, RiskState
from atlas_trader.risk.engine import RiskService


class PaperAccountService:
    def __init__(
        self,
        portfolio: PaperPortfolioRepository,
        risk_states: RiskStateRepository,
        *,
        account_id: str,
        quote_asset: str,
        initial_balance: Decimal,
    ) -> None:
        self._portfolio = portfolio
        self._risk_states = risk_states
        self._account_id = account_id
        self._quote_asset = quote_asset
        self._initial_balance = initial_balance

    async def ensure_initialized(self, now: datetime) -> None:
        balance = await self._portfolio.get_balance(self._account_id, self._quote_asset)
        if balance is None:
            await self._portfolio.set_balance(
                PaperBalance(
                    account_id=self._account_id,
                    asset=self._quote_asset,
                    available=self._initial_balance,
                    updated_at=now,
                )
            )
        state = await self._risk_states.get(self._account_id)
        if state is None:
            await self._risk_states.save(
                RiskState(
                    account_id=self._account_id,
                    trading_day=now.date(),
                    starting_equity=self._initial_balance,
                    peak_equity=self._initial_balance,
                    updated_at=now,
                )
            )

    async def view(self) -> PaperPortfolioView:
        return PaperPortfolioView(
            account_id=self._account_id,
            balances=tuple(await self._portfolio.list_balances(self._account_id)),
            positions=tuple(await self._portfolio.list_positions(self._account_id)),
            latest_snapshot=await self._portfolio.latest_snapshot(self._account_id),
        )


class PaperTradingCycleService:
    def __init__(
        self,
        *,
        signals: SignalReader,
        markets: MarketReader,
        quotes: PublicQuoteProvider,
        risk: RiskService,
        intents: OrderIntentService,
        execution: PaperExecutor,
        reconciliation: PaperReconciler,
        portfolio: PaperPortfolioRepository,
        events: SystemEventRepository,
        unit_of_work: TradingUnitOfWork,
        account_id: str,
        mode: ExecutionMode,
        cooldown_minutes: int,
    ) -> None:
        self._signals = signals
        self._markets = markets
        self._quotes = quotes
        self._risk = risk
        self._intents = intents
        self._execution = execution
        self._reconciliation = reconciliation
        self._portfolio = portfolio
        self._events = events
        self._unit_of_work = unit_of_work
        self._account_id = account_id
        self._mode = mode
        self._cooldown_minutes = cooldown_minutes

    async def run(
        self, signal_id: UUID, quantity: Decimal, *, correlation_id: str, now: datetime
    ) -> PaperTradingCycleResult:
        if self._mode is not ExecutionMode.PAPER:
            raise PaperExecutionRejectedError("trading cycle is PAPER-only")
        signal = await self._signals.get_stored(signal_id)
        if signal is None:
            raise PaperExecutionRejectedError("stored signal was not found")
        if signal.action is SignalAction.HOLD:
            await self._event(
                "paper.cycle_hold", signal.exchange, signal.symbol, correlation_id, now
            )
            await self._unit_of_work.commit()
            return PaperTradingCycleResult(
                correlation_id=correlation_id,
                signal_action=signal.action,
                outcome="hold",
            )

        market = await self._markets.get(signal.exchange, signal.symbol)
        if market is None:
            raise PaperExecutionRejectedError("stored market was not found")
        ticker = await self._quotes.get_ticker(signal.symbol, correlation_id=correlation_id)
        balance = await self._portfolio.get_balance(self._account_id, market.quote_asset)
        if balance is None:
            raise PaperExecutionRejectedError("paper account is not initialized")
        position = await self._portfolio.get_position(
            self._account_id, signal.exchange, signal.symbol
        )
        snapshot = await self._portfolio.latest_snapshot(self._account_id)
        mid = (ticker.ask + ticker.bid) / Decimal("2")
        spread_bps = (ticker.ask - ticker.bid) / mid * Decimal("10000")
        side = OrderSide.BUY if signal.action is SignalAction.BUY else OrderSide.SELL
        context = RiskContext(
            side=side,
            reference_price=ticker.last,
            position_quantity=Decimal("0") if position is None else position.quantity,
            portfolio_equity=(balance.available if snapshot is None else snapshot.total_equity),
            available_quote=balance.available,
            available_base=Decimal("0") if position is None else position.quantity,
            spread_bps=spread_bps,
            market_data_at=ticker.timestamp,
            now=now,
        )
        decision = await self._risk.evaluate(self._account_id, quantity, context)
        intent, _ = await self._intents.create(
            signal_id=signal_id,
            exchange=signal.exchange,
            symbol=signal.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            reference_price=ticker.last,
            limit_price=None,
            strategy=signal.strategy,
            strategy_version=signal.strategy_version,
            risk_decision=decision,
            correlation_id=correlation_id,
            now=now,
        )
        await self._event(
            "paper.risk_approved" if decision.approved else "paper.risk_rejected",
            signal.exchange,
            signal.symbol,
            correlation_id,
            now,
            client_order_id=intent.client_order_id,
        )
        await self._unit_of_work.commit()
        if not decision.approved:
            return PaperTradingCycleResult(
                correlation_id=correlation_id,
                signal_action=signal.action,
                risk_decision=decision,
                intent=intent,
                outcome="risk_rejected",
            )

        try:
            execution = await self._execution.execute(
                intent, market, ticker, account_id=self._account_id, now=now
            )
            if execution.created:
                await self._risk.record_execution(
                    self._account_id,
                    realized_pnl=execution.fill.realized_pnl,
                    equity=execution.snapshot.total_equity,
                    open_positions=1 if execution.position.quantity > 0 else 0,
                    cooldown_minutes=self._cooldown_minutes,
                    now=now,
                )
            await self._unit_of_work.commit()
        except AtlasTraderError as exc:
            await self._unit_of_work.rollback()
            await self._event(
                "paper.execution_failed",
                signal.exchange,
                signal.symbol,
                correlation_id,
                now,
                client_order_id=intent.client_order_id,
            )
            await self._unit_of_work.commit()
            raise PaperExecutionRejectedError("paper execution failed safely") from exc

        persisted_intent = await self._intents.get(intent.id)
        if persisted_intent is not None:
            intent = persisted_intent

        report = await self._reconciliation.run(
            self._account_id, correlation_id=correlation_id, now=now
        )
        await self._unit_of_work.commit()
        return PaperTradingCycleResult(
            correlation_id=correlation_id,
            signal_action=signal.action,
            risk_decision=decision,
            intent=intent,
            execution=execution,
            reconciliation=report,
            outcome="filled" if report.consistent else "filled_reconciliation_failed",
        )

    async def _event(
        self,
        event_type: str,
        exchange: str,
        symbol: str,
        correlation_id: str,
        now: datetime,
        *,
        client_order_id: str | None = None,
    ) -> None:
        await self._events.append(
            SystemEvent(
                event_type=event_type,
                correlation_id=correlation_id,
                exchange=exchange,
                symbol=symbol,
                client_order_id=client_order_id,
                created_at=now,
            )
        )
