"""Add persistent PAPER balances, positions, fills, and snapshots.

Revision ID: 20260823_0006
Revises: 20260823_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260823_0006"
down_revision: str | None = "20260823_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_balances",
        sa.Column("account_id", sa.String(length=64), primary_key=True),
        sa.Column("asset", sa.String(length=32), primary_key=True),
        sa.Column("available", sa.Numeric(36, 18), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("available >= 0", name="ck_paper_balance_nonnegative"),
    )
    op.create_table(
        "paper_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("base_asset", sa.String(length=32), nullable=False),
        sa.Column("quote_asset", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Numeric(36, 18), nullable=False),
        sa.Column("average_cost", sa.Numeric(36, 18), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(36, 18), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "exchange", "symbol", name="uq_paper_positions_identity"),
        sa.CheckConstraint("quantity >= 0", name="ck_paper_position_quantity_nonnegative"),
        sa.CheckConstraint("average_cost >= 0", name="ck_paper_position_cost_nonnegative"),
    )
    op.create_table(
        "paper_fills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("execution_event_id", sa.String(length=64), nullable=False),
        sa.Column(
            "intent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("order_intents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("client_order_id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Numeric(36, 18), nullable=False),
        sa.Column("price", sa.Numeric(36, 18), nullable=False),
        sa.Column("notional", sa.Numeric(36, 18), nullable=False),
        sa.Column("fee", sa.Numeric(36, 18), nullable=False),
        sa.Column("fee_asset", sa.String(length=32), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(36, 18), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assumptions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.UniqueConstraint("intent_id", name="uq_paper_fills_intent"),
        sa.UniqueConstraint("execution_event_id", name="uq_paper_fills_execution_event"),
        sa.CheckConstraint("quantity > 0", name="ck_paper_fill_quantity_positive"),
        sa.CheckConstraint("price > 0", name="ck_paper_fill_price_positive"),
        sa.CheckConstraint("fee >= 0", name="ck_paper_fill_fee_nonnegative"),
    )
    op.create_index("ix_paper_fills_account_id", "paper_fills", ["account_id"])
    op.create_index("ix_paper_fills_correlation_id", "paper_fills", ["correlation_id"])
    op.create_table(
        "paper_portfolio_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("quote_asset", sa.String(length=32), nullable=False),
        sa.Column("cash", sa.Numeric(36, 18), nullable=False),
        sa.Column("positions_value", sa.Numeric(36, 18), nullable=False),
        sa.Column("total_equity", sa.Numeric(36, 18), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(36, 18), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(36, 18), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_paper_snapshots_account_time",
        "paper_portfolio_snapshots",
        ["account_id", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_paper_snapshots_account_time", table_name="paper_portfolio_snapshots")
    op.drop_table("paper_portfolio_snapshots")
    op.drop_index("ix_paper_fills_correlation_id", table_name="paper_fills")
    op.drop_index("ix_paper_fills_account_id", table_name="paper_fills")
    op.drop_table("paper_fills")
    op.drop_table("paper_positions")
    op.drop_table("paper_balances")
