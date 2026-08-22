from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from atlas_trader.domain.enums.execution_mode import ExecutionMode
from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.order_type import OrderType
from atlas_trader.domain.enums.signal_action import SignalAction
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.models.candle import Candle
from atlas_trader.domain.models.order import ExchangeOrder, OrderIntent, OrderStatus
from atlas_trader.domain.models.portfolio import Balance
from atlas_trader.domain.models.signal import Signal


def test_balance_math_remains_decimal() -> None:
    balance = Balance(asset="USDT", available=Decimal("0.1"), locked=Decimal("0.2"))

    assert balance.total == Decimal("0.3")
    assert isinstance(balance.total, Decimal)


def test_financial_fields_reject_float_input() -> None:
    with pytest.raises(ValidationError):
        Balance(asset="USDT", available=0.1)  # type: ignore[arg-type]


def test_candle_rejects_invalid_ohlc_range() -> None:
    with pytest.raises(ValidationError, match="high must be"):
        Candle(
            exchange="mock",
            symbol="BTC-USDT",
            timeframe=Timeframe.ONE_HOUR,
            timestamp=datetime.now(UTC),
            open=Decimal("100"),
            high=Decimal("99"),
            low=Decimal("90"),
            close=Decimal("95"),
            volume=Decimal("1"),
        )


def test_candle_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        Candle(
            exchange="mock",
            symbol="BTC-USDT",
            timeframe=Timeframe.ONE_HOUR,
            timestamp=datetime(2026, 8, 22),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("1"),
        )


def test_domain_metadata_cannot_hide_nested_float() -> None:
    with pytest.raises(ValidationError):
        Signal(
            strategy="test",
            exchange="mock",
            symbol="BTC-USDT",
            timeframe=Timeframe.ONE_HOUR,
            candle_timestamp=datetime.now(UTC),
            action=SignalAction.BUY,
            score=Decimal("1"),
            reference_price=Decimal("100"),
            metadata={"nested": {"financial_value": 0.1}},  # type: ignore[dict-item]
        )


def test_limit_order_requires_price() -> None:
    with pytest.raises(ValidationError, match="limit orders require a price"):
        OrderIntent(
            client_order_id="test-order-1",
            exchange="mock",
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            amount=Decimal("1"),
            mode=ExecutionMode.PAPER,
            strategy="test",
            correlation_id="cycle-1",
            created_at=datetime.now(UTC),
        )


def test_exchange_order_rejects_overfill() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="cannot exceed"):
        ExchangeOrder(
            exchange="mock",
            exchange_order_id="mock-1",
            client_order_id="test-order-1",
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            amount=Decimal("1"),
            filled_amount=Decimal("2"),
            price=Decimal("100"),
            status=OrderStatus.PARTIALLY_FILLED,
            created_at=now,
            updated_at=now,
        )
