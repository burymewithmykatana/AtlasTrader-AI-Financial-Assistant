from datetime import UTC, datetime
from decimal import Decimal

import pytest

from atlas_trader.domain.enums.execution_mode import ExecutionMode
from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.order_type import OrderType
from atlas_trader.domain.exceptions import (
    ExchangeOrderRejectedError,
    ExchangeRequestError,
    IdempotencyConflictError,
)
from atlas_trader.domain.interfaces.exchange import ExchangeAdapter
from atlas_trader.domain.models.market import Market, Ticker
from atlas_trader.domain.models.order import OrderIntent, OrderStatus
from atlas_trader.infrastructure.exchanges.mock.adapter import MockExchangeAdapter


def make_intent(*, mode: ExecutionMode = ExecutionMode.PAPER) -> OrderIntent:
    return OrderIntent(
        client_order_id="ema-btc-20260822-buy",
        exchange="mock",
        symbol="BTC-USDT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        amount=Decimal("0.001"),
        price=Decimal("65000.00"),
        mode=mode,
        strategy="ema_atr_v1",
        correlation_id="cycle-1",
        created_at=datetime.now(UTC),
    )


def test_mock_adapter_satisfies_exchange_contract() -> None:
    assert isinstance(MockExchangeAdapter(), ExchangeAdapter)


@pytest.mark.asyncio
async def test_market_data_is_seeded_and_retrieved_deterministically() -> None:
    adapter = MockExchangeAdapter()
    now = datetime.now(UTC)
    adapter.seed_market(
        Market(
            exchange="mock",
            symbol="BTC-USDT",
            base_asset="BTC",
            quote_asset="USDT",
            price_precision=2,
            amount_precision=6,
            min_order_amount=Decimal("0.0001"),
        )
    )
    adapter.seed_ticker(
        Ticker(
            exchange="mock",
            symbol="BTC-USDT",
            bid=Decimal("64999"),
            ask=Decimal("65001"),
            last=Decimal("65000"),
            timestamp=now,
        )
    )

    assert [market.symbol for market in await adapter.get_markets()] == ["BTC-USDT"]
    orderbook = await adapter.get_orderbook("BTC-USDT")
    assert orderbook.bids[0].price == Decimal("64999")
    assert orderbook.asks[0].price == Decimal("65001")


@pytest.mark.asyncio
async def test_duplicate_client_order_id_returns_original_order() -> None:
    adapter = MockExchangeAdapter()
    intent = make_intent()

    first = await adapter.place_order(intent)
    duplicate = await adapter.place_order(intent)

    assert duplicate.exchange_order_id == first.exchange_order_id
    assert len(await adapter.get_open_orders()) == 1


@pytest.mark.asyncio
async def test_mock_adapter_never_accepts_live_orders() -> None:
    adapter = MockExchangeAdapter()

    with pytest.raises(ExchangeOrderRejectedError, match="never accepts LIVE"):
        await adapter.place_order(make_intent(mode=ExecutionMode.LIVE))


@pytest.mark.asyncio
async def test_order_can_be_cancelled() -> None:
    adapter = MockExchangeAdapter()
    order = await adapter.place_order(make_intent())

    cancelled = await adapter.cancel_order(order.exchange_order_id)

    assert cancelled.status is OrderStatus.CANCELLED
    assert await adapter.get_open_orders() == []


@pytest.mark.asyncio
async def test_client_order_id_conflict_is_not_silently_accepted() -> None:
    adapter = MockExchangeAdapter()
    intent = make_intent()
    await adapter.place_order(intent)
    conflicting = intent.model_copy(update={"amount": Decimal("0.002")})

    with pytest.raises(IdempotencyConflictError, match="different execution parameters"):
        await adapter.place_order(conflicting)

    assert len(await adapter.get_open_orders()) == 1


@pytest.mark.asyncio
async def test_adapter_rejects_intent_for_another_exchange() -> None:
    adapter = MockExchangeAdapter()
    intent = make_intent().model_copy(update={"exchange": "other"})

    with pytest.raises(ExchangeRequestError, match="cannot handle exchange"):
        await adapter.place_order(intent)


@pytest.mark.asyncio
async def test_order_book_rejects_non_positive_limit() -> None:
    adapter = MockExchangeAdapter()

    with pytest.raises(ExchangeRequestError, match="limit must be positive"):
        await adapter.get_orderbook("BTC-USDT", limit=0)
