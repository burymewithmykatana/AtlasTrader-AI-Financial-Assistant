"""Create Phase 0 foundation tables.

Revision ID: 20260822_0001
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260822_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "markets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("base_asset", sa.String(length=32), nullable=False),
        sa.Column("quote_asset", sa.String(length=32), nullable=False),
        sa.Column("price_precision", sa.Integer(), nullable=False),
        sa.Column("amount_precision", sa.Integer(), nullable=False),
        sa.Column("min_order_amount", sa.Numeric(precision=36, scale=18), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exchange", "symbol", name="uq_markets_exchange_symbol"),
    )
    op.create_index("ix_markets_exchange", "markets", ["exchange"], unique=False)

    op.create_table(
        "system_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("exchange", sa.String(length=32), nullable=True),
        sa.Column("symbol", sa.String(length=64), nullable=True),
        sa.Column("strategy", sa.String(length=64), nullable=True),
        sa.Column("client_order_id", sa.String(length=64), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_system_events_created_at", "system_events", ["created_at"], unique=False)
    op.create_index(
        "ix_system_events_correlation_id", "system_events", ["correlation_id"], unique=False
    )
    op.create_index("ix_system_events_event_type", "system_events", ["event_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_system_events_event_type", table_name="system_events")
    op.drop_index("ix_system_events_correlation_id", table_name="system_events")
    op.drop_index("ix_system_events_created_at", table_name="system_events")
    op.drop_table("system_events")
    op.drop_index("ix_markets_exchange", table_name="markets")
    op.drop_table("markets")
