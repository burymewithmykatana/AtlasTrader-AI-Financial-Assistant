from decimal import Decimal
from typing import cast

from sqlalchemy import CheckConstraint, Numeric, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import insert

from atlas_trader.domain.metadata import Metadata
from atlas_trader.infrastructure.database.models import (
    CandleRecord,
    MarketRecord,
    OrderIntentRecord,
    PaperBalanceRecord,
    PaperFillRecord,
    PaperPositionRecord,
    RiskStateRecord,
    SignalRecord,
)
from atlas_trader.infrastructure.database.repositories.common import (
    decode_metadata,
    encode_metadata,
)


def test_market_schema_has_exchange_symbol_uniqueness() -> None:
    table = cast(Table, MarketRecord.__table__)
    unique_constraints = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "uq_markets_exchange_symbol" in unique_constraints


def test_market_money_column_is_fixed_precision_numeric() -> None:
    table = cast(Table, MarketRecord.__table__)
    column_type = table.c.min_order_amount.type

    assert isinstance(column_type, Numeric)
    assert column_type.precision == 36
    assert column_type.scale == 18


def test_phase1_idempotency_constraints_exist() -> None:
    candle_table = cast(Table, CandleRecord.__table__)
    signal_table = cast(Table, SignalRecord.__table__)

    candle_constraints = {
        constraint.name
        for constraint in candle_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    signal_constraints = {
        constraint.name
        for constraint in signal_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "uq_candles_identity" in candle_constraints
    assert "uq_signals_identity" in signal_constraints
    for name in ("open", "high", "low", "close", "volume"):
        assert isinstance(candle_table.c[name].type, Numeric)


def test_jsonb_metadata_codec_preserves_decimal_without_float() -> None:
    original: Metadata = {
        "rate": Decimal("0.001"),
        "nested": {"amount": Decimal("12.30")},
    }

    encoded = encode_metadata(original)

    assert encoded == {
        "rate": {"__atlas_decimal__": "0.001"},
        "nested": {"amount": {"__atlas_decimal__": "12.30"}},
    }
    assert decode_metadata(encoded) == original


def test_jsonb_orm_inserts_use_non_reserved_metadata_attribute() -> None:
    market_statement = insert(MarketRecord).values(metadata_={})
    signal_statement = insert(SignalRecord).values(metadata_={})

    assert "metadata" in str(market_statement)
    assert "metadata" in str(signal_statement)


def test_risk_state_financial_columns_are_numeric() -> None:
    table = cast(Table, RiskStateRecord.__table__)

    for name in ("starting_equity", "realized_pnl", "peak_equity", "drawdown"):
        assert isinstance(table.c[name].type, Numeric)


def test_order_intent_idempotency_and_numeric_schema() -> None:
    table = cast(Table, OrderIntentRecord.__table__)
    constraints = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "uq_order_intents_client_order_id" in constraints
    for name in (
        "requested_quantity",
        "requested_notional",
        "limit_price",
        "reference_price",
    ):
        assert isinstance(table.c[name].type, Numeric)


def test_phase2_database_safety_checks_are_declared_in_orm_metadata() -> None:
    expected = {
        RiskStateRecord: {
            "ck_risk_starting_equity_positive",
            "ck_risk_peak_equity_positive",
            "ck_risk_drawdown_nonnegative",
            "ck_risk_open_positions_nonnegative",
            "ck_risk_system_state",
        },
        OrderIntentRecord: {
            "ck_intent_client_id_length",
            "ck_intent_quantity_positive",
            "ck_intent_reference_price_positive",
        },
        PaperBalanceRecord: {"ck_paper_balance_nonnegative"},
        PaperPositionRecord: {
            "ck_paper_position_quantity_nonnegative",
            "ck_paper_position_cost_nonnegative",
        },
        PaperFillRecord: {
            "ck_paper_fill_quantity_positive",
            "ck_paper_fill_price_positive",
            "ck_paper_fill_fee_nonnegative",
        },
    }

    for model, names in expected.items():
        table = cast(Table, model.__table__)
        actual = {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert names <= actual
