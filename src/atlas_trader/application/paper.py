import hashlib
from datetime import datetime
from decimal import Decimal

from atlas_trader.domain.enums.execution_mode import ExecutionMode
from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.exceptions import PaperExecutionRejectedError
from atlas_trader.domain.interfaces.orders import OrderIntentRepository
from atlas_trader.domain.interfaces.paper import PaperPortfolioRepository
from atlas_trader.domain.models.base import ZERO
from atlas_trader.domain.models.market import Market, Ticker
from atlas_trader.domain.models.order import OrderIntent, OrderIntentStatus
from atlas_trader.domain.models.paper import (
    PaperBalance,
    PaperExecutionResult,
    PaperFill,
    PaperPortfolioSnapshot,
    PaperPosition,
)

BPS = Decimal("10000")


class PaperExecutionService:
    def __init__(
        self,
        intents: OrderIntentRepository,
        portfolio: PaperPortfolioRepository,
        *,
        fee_rate: Decimal,
        slippage_bps: Decimal,
    ) -> None:
        if fee_rate < ZERO or slippage_bps < ZERO:
            raise ValueError("paper fee and slippage must be non-negative")
        self._intents = intents
        self._portfolio = portfolio
        self._fee_rate = fee_rate
        self._slippage_bps = slippage_bps

    async def execute(
        self,
        intent: OrderIntent,
        market: Market,
        ticker: Ticker,
        *,
        account_id: str,
        now: datetime,
    ) -> PaperExecutionResult:
        persisted = await self._intents.get(intent.id)
        if persisted is None or persisted.execution_signature() != intent.execution_signature():
            raise PaperExecutionRejectedError("paper execution requires a persisted order intent")
        existing_fill = await self._portfolio.get_fill_for_intent(intent.id)
        if existing_fill is not None:
            return await self._reload_result(existing_fill, market)
        if intent.execution_mode is not ExecutionMode.PAPER:
            raise PaperExecutionRejectedError("paper engine accepts PAPER intents only")
        if intent.status is not OrderIntentStatus.APPROVED or not intent.risk_decision.approved:
            raise PaperExecutionRejectedError("paper execution requires persisted risk approval")
        if not market.active:
            raise PaperExecutionRejectedError("market is inactive")
        if market.exchange != intent.exchange or market.symbol != intent.symbol:
            raise PaperExecutionRejectedError("market does not match order intent")
        if ticker.exchange != intent.exchange or ticker.symbol != intent.symbol:
            raise PaperExecutionRejectedError("price snapshot does not match order intent")

        quantity = intent.risk_decision.approved_size
        market_price = ticker.ask if intent.side is OrderSide.BUY else ticker.bid
        multiplier = (
            Decimal("1") + self._slippage_bps / BPS
            if intent.side is OrderSide.BUY
            else Decimal("1") - self._slippage_bps / BPS
        )
        price = market_price * multiplier
        if price <= ZERO:
            raise PaperExecutionRejectedError("paper execution price is unavailable")
        notional = price * quantity
        fee = notional * self._fee_rate
        balance = await self._portfolio.get_balance(account_id, market.quote_asset)
        if balance is None:
            raise PaperExecutionRejectedError("paper quote balance is unavailable")
        position = await self._portfolio.get_position(account_id, intent.exchange, intent.symbol)
        if position is None:
            position = PaperPosition(
                account_id=account_id,
                exchange=intent.exchange,
                symbol=intent.symbol,
                base_asset=market.base_asset,
                quote_asset=market.quote_asset,
                updated_at=now,
            )

        updated_balance, updated_position, realized = self._apply(
            intent.side, quantity, price, fee, balance, position, now
        )
        positions_value = updated_position.quantity * ticker.last
        unrealized = (
            updated_position.quantity * (ticker.last - updated_position.average_cost)
            if updated_position.quantity > ZERO
            else ZERO
        )
        snapshot = PaperPortfolioSnapshot(
            account_id=account_id,
            quote_asset=market.quote_asset,
            cash=updated_balance.available,
            positions_value=positions_value,
            total_equity=updated_balance.available + positions_value,
            realized_pnl=updated_position.realized_pnl,
            unrealized_pnl=unrealized,
            timestamp=now,
        )
        event_id = (
            "paper_"
            + hashlib.sha256(
                f"{intent.id}|{ticker.timestamp.isoformat()}|{price.normalize()}".encode()
            ).hexdigest()[:40]
        )
        fill = PaperFill(
            execution_event_id=event_id,
            intent_id=intent.id,
            client_order_id=intent.client_order_id,
            account_id=account_id,
            exchange=intent.exchange,
            symbol=intent.symbol,
            side=intent.side,
            quantity=quantity,
            price=price,
            notional=notional,
            fee=fee,
            fee_asset=market.quote_asset,
            realized_pnl=realized,
            correlation_id=intent.correlation_id,
            executed_at=now,
            assumptions={
                "price_source": "best_ask" if intent.side is OrderSide.BUY else "best_bid",
                "slippage_bps": self._slippage_bps,
                "fee_rate": self._fee_rate,
            },
        )
        stored_fill, created = await self._portfolio.apply_execution(
            intent, fill, updated_balance, updated_position, snapshot
        )
        if not created:
            return await self._reload_result(stored_fill, market)
        return PaperExecutionResult(
            fill=stored_fill,
            balance=updated_balance,
            position=updated_position,
            snapshot=snapshot,
            created=True,
        )

    @staticmethod
    def _apply(
        side: OrderSide,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
        balance: PaperBalance,
        position: PaperPosition,
        now: datetime,
    ) -> tuple[PaperBalance, PaperPosition, Decimal]:
        notional = quantity * price
        if side is OrderSide.BUY:
            debit = notional + fee
            if debit > balance.available:
                raise PaperExecutionRejectedError("insufficient paper cash")
            new_quantity = position.quantity + quantity
            total_cost = position.quantity * position.average_cost + debit
            updated_position = position.model_copy(
                update={
                    "quantity": new_quantity,
                    "average_cost": total_cost / new_quantity,
                    "updated_at": now,
                }
            )
            return (
                balance.model_copy(
                    update={"available": balance.available - debit, "updated_at": now}
                ),
                updated_position,
                ZERO,
            )
        if quantity > position.quantity:
            raise PaperExecutionRejectedError("insufficient paper position")
        realized = notional - fee - quantity * position.average_cost
        remaining = position.quantity - quantity
        updated_position = position.model_copy(
            update={
                "quantity": remaining,
                "average_cost": position.average_cost if remaining > ZERO else ZERO,
                "realized_pnl": position.realized_pnl + realized,
                "updated_at": now,
            }
        )
        return (
            balance.model_copy(
                update={"available": balance.available + notional - fee, "updated_at": now}
            ),
            updated_position,
            realized,
        )

    async def _reload_result(self, fill: PaperFill, market: Market) -> PaperExecutionResult:
        balance = await self._portfolio.get_balance(fill.account_id, market.quote_asset)
        position = await self._portfolio.get_position(fill.account_id, fill.exchange, fill.symbol)
        snapshot = await self._portfolio.latest_snapshot(fill.account_id)
        if balance is None or position is None or snapshot is None:
            raise PaperExecutionRejectedError("persisted paper execution is incomplete")
        return PaperExecutionResult(
            fill=fill,
            balance=balance,
            position=position,
            snapshot=snapshot,
            created=False,
        )
