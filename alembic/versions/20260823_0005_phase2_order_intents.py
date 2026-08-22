"""Add durable idempotent order intents.

Revision ID: 20260823_0005
Revises: 20260823_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260823_0005"
down_revision: str | None = "20260823_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "order_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("client_order_id", sa.String(length=32), nullable=False),
        sa.Column(
            "signal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("signals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("requested_quantity", sa.Numeric(36, 18), nullable=False),
        sa.Column("requested_notional", sa.Numeric(36, 18), nullable=True),
        sa.Column("limit_price", sa.Numeric(36, 18), nullable=True),
        sa.Column("reference_price", sa.Numeric(36, 18), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("trading_mode", sa.String(length=16), nullable=False),
        sa.Column("execution_model", sa.String(length=32), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=24), nullable=False),
        sa.Column("risk_decision", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("client_order_id", name="uq_order_intents_client_order_id"),
        sa.CheckConstraint("char_length(client_order_id) <= 32", name="ck_intent_client_id_length"),
        sa.CheckConstraint("requested_quantity > 0", name="ck_intent_quantity_positive"),
        sa.CheckConstraint("reference_price > 0", name="ck_intent_reference_price_positive"),
    )
    op.create_index("ix_order_intents_status", "order_intents", ["status"])
    op.create_index("ix_order_intents_correlation_id", "order_intents", ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_order_intents_correlation_id", table_name="order_intents")
    op.drop_index("ix_order_intents_status", table_name="order_intents")
    op.drop_table("order_intents")
