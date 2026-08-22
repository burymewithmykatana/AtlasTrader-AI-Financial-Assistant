"""Add Phase 1 market data, signals, and backtests.

Revision ID: 20260822_0002
Revises: 20260822_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260822_0002"
down_revision: str | None = "20260822_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MONEY = sa.Numeric(precision=36, scale=18)


def upgrade() -> None:
    op.add_column("markets", sa.Column("price_step", MONEY, server_default="1", nullable=False))
    op.add_column("markets", sa.Column("amount_step", MONEY, server_default="1", nullable=False))
    op.add_column(
        "markets",
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
    )
    op.add_column(
        "markets",
        sa.Column(
            "base_asset_class", sa.String(length=24), server_default="unknown", nullable=False
        ),
    )
    op.add_column(
        "markets",
        sa.Column(
            "quote_asset_class", sa.String(length=24), server_default="unknown", nullable=False
        ),
    )
    op.add_column(
        "markets",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "markets",
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "markets",
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "candles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open", MONEY, nullable=False),
        sa.Column("high", MONEY, nullable=False),
        sa.Column("low", MONEY, nullable=False),
        sa.Column("close", MONEY, nullable=False),
        sa.Column("volume", MONEY, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "exchange", "symbol", "timeframe", "open_time", name="uq_candles_identity"
        ),
    )
    op.create_index(
        "ix_candles_lookup",
        "candles",
        ["exchange", "symbol", "timeframe", sa.text("open_time DESC")],
    )

    op.create_table(
        "signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_name", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=24), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("candle_open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.String(length=8), nullable=False),
        sa.Column("score", MONEY, nullable=False),
        sa.Column("reference_price", MONEY, nullable=False),
        sa.Column("stop_price", MONEY, nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "strategy_name",
            "strategy_version",
            "exchange",
            "symbol",
            "timeframe",
            "candle_open_time",
            name="uq_signals_identity",
        ),
    )

    op.create_table(
        "backtest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_name", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=24), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_capital", MONEY, nullable=False),
        sa.Column("ending_equity", MONEY, nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("execution_model", sa.String(length=32), nullable=False),
        sa.Column("fee_rate", sa.Numeric(precision=18, scale=12), nullable=False),
        sa.Column("slippage_model", sa.String(length=32), nullable=False),
        sa.Column("slippage_bps", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("code_version", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "backtest_trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "backtest_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("backtest_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("signal_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", MONEY, nullable=False),
        sa.Column("quantity", MONEY, nullable=False),
        sa.Column("fee", MONEY, nullable=False),
        sa.Column("realized_pnl", MONEY, nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("backtest_run_id", "sequence", name="uq_backtest_trades_sequence"),
    )
    op.create_index("ix_backtest_trades_backtest_run_id", "backtest_trades", ["backtest_run_id"])


def downgrade() -> None:
    op.drop_index("ix_backtest_trades_backtest_run_id", table_name="backtest_trades")
    op.drop_table("backtest_trades")
    op.drop_table("backtest_runs")
    op.drop_table("signals")
    op.drop_index("ix_candles_lookup", table_name="candles")
    op.drop_table("candles")
    for column in (
        "last_seen_at",
        "first_seen_at",
        "metadata",
        "quote_asset_class",
        "base_asset_class",
        "status",
        "amount_step",
        "price_step",
    ):
        op.drop_column("markets", column)
