"""Phase 0 persistence models.

Trading tables are introduced with the phases that own their behavior. This migration
starts market discovery and the immutable system-event audit stream.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    desc,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MarketRecord(Base):
    __tablename__ = "markets"
    __table_args__ = (UniqueConstraint("exchange", "symbol", name="uq_markets_exchange_symbol"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    base_asset: Mapped[str] = mapped_column(String(32), nullable=False)
    quote_asset: Mapped[str] = mapped_column(String(32), nullable=False)
    price_precision: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_precision: Mapped[int] = mapped_column(Integer, nullable=False)
    min_order_amount: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    price_step: Mapped[Decimal] = mapped_column(
        Numeric(36, 18), nullable=False, default=Decimal("1")
    )
    amount_step: Mapped[Decimal] = mapped_column(
        Numeric(36, 18), nullable=False, default=Decimal("1")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    base_asset_class: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    quote_asset_class: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SystemEventRecord(Base):
    __tablename__ = "system_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    exchange: Mapped[str | None] = mapped_column(String(32), nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    strategy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


class RiskStateRecord(Base):
    __tablename__ = "risk_state"
    __table_args__ = (
        CheckConstraint("starting_equity > 0", name="ck_risk_starting_equity_positive"),
        CheckConstraint("peak_equity > 0", name="ck_risk_peak_equity_positive"),
        CheckConstraint("drawdown >= 0", name="ck_risk_drawdown_nonnegative"),
        CheckConstraint("open_positions >= 0", name="ck_risk_open_positions_nonnegative"),
        CheckConstraint(
            "system_state IN ('enabled', 'paused', 'killed')",
            name="ck_risk_system_state",
        ),
    )

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    system_state: Mapped[str] = mapped_column(String(16), nullable=False, default="enabled")
    trading_day: Mapped[date] = mapped_column(Date, nullable=False)
    starting_equity: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(36, 18), nullable=False, default=Decimal("0")
    )
    peak_equity: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    drawdown: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False, default=Decimal("0"))
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    open_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CandleRecord(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint(
            "exchange", "symbol", "timeframe", "open_time", name="uq_candles_identity"
        ),
        Index(
            "ix_candles_lookup",
            "exchange",
            "symbol",
            "timeframe",
            desc("open_time"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    open: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SignalRecord(Base):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint(
            "strategy_name",
            "strategy_version",
            "exchange",
            "symbol",
            "timeframe",
            "candle_open_time",
            name="uq_signals_identity",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(24), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    candle_open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(36, 18), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OrderIntentRecord(Base):
    __tablename__ = "order_intents"
    __table_args__ = (
        UniqueConstraint("client_order_id", name="uq_order_intents_client_order_id"),
        CheckConstraint("char_length(client_order_id) <= 32", name="ck_intent_client_id_length"),
        CheckConstraint("requested_quantity > 0", name="ck_intent_quantity_positive"),
        CheckConstraint("reference_price > 0", name="ck_intent_reference_price_positive"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    client_order_id: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("signals.id", ondelete="SET NULL"), nullable=True
    )
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_quantity: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    requested_notional: Mapped[Decimal | None] = mapped_column(Numeric(36, 18), nullable=True)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(36, 18), nullable=True)
    reference_price: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    trading_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    execution_model: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(24), nullable=False)
    risk_decision: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperBalanceRecord(Base):
    __tablename__ = "paper_balances"
    __table_args__ = (CheckConstraint("available >= 0", name="ck_paper_balance_nonnegative"),)

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset: Mapped[str] = mapped_column(String(32), primary_key=True)
    available: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperPositionRecord(Base):
    __tablename__ = "paper_positions"
    __table_args__ = (
        UniqueConstraint("account_id", "exchange", "symbol", name="uq_paper_positions_identity"),
        CheckConstraint("quantity >= 0", name="ck_paper_position_quantity_nonnegative"),
        CheckConstraint("average_cost >= 0", name="ck_paper_position_cost_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    base_asset: Mapped[str] = mapped_column(String(32), nullable=False)
    quote_asset: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperFillRecord(Base):
    __tablename__ = "paper_fills"
    __table_args__ = (
        UniqueConstraint("intent_id", name="uq_paper_fills_intent"),
        UniqueConstraint("execution_event_id", name="uq_paper_fills_execution_event"),
        CheckConstraint("quantity > 0", name="ck_paper_fill_quantity_positive"),
        CheckConstraint("price > 0", name="ck_paper_fill_price_positive"),
        CheckConstraint("fee >= 0", name="ck_paper_fill_fee_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    execution_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    intent_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("order_intents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    client_order_id: Mapped[str] = mapped_column(String(32), nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    notional: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    fee_asset: Mapped[str] = mapped_column(String(32), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class PaperPortfolioSnapshotRecord(Base):
    __tablename__ = "paper_portfolio_snapshots"
    __table_args__ = (Index("ix_paper_snapshots_account_time", "account_id", "timestamp"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    quote_asset: Mapped[str] = mapped_column(String(32), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    positions_value: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    total_equity: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BacktestRunRecord(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(24), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    candle_count: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dataset_fingerprint: Mapped[str] = mapped_column(String(96), nullable=False)
    initial_capital: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    ending_equity: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    execution_model: Mapped[str] = mapped_column(String(32), nullable=False)
    fee_rate: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False)
    fee_model: Mapped[str] = mapped_column(String(32), nullable=False)
    slippage_model: Mapped[str] = mapped_column(String(32), nullable=False)
    slippage_bps: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    code_version: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)


class BacktestTradeRecord(Base):
    __tablename__ = "backtest_trades"
    __table_args__ = (
        UniqueConstraint("backtest_run_id", "sequence", name="uq_backtest_trades_sequence"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    backtest_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    signal_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    execution_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(36, 18), nullable=True)
