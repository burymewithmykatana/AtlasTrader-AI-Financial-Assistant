"""Add persistent Phase 2 risk state.

Revision ID: 20260823_0004
Revises: 20260822_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0004"
down_revision: str | None = "20260822_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "risk_state",
        sa.Column("account_id", sa.String(length=64), primary_key=True),
        sa.Column("system_state", sa.String(length=16), nullable=False),
        sa.Column("trading_day", sa.Date(), nullable=False),
        sa.Column("starting_equity", sa.Numeric(36, 18), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(36, 18), nullable=False),
        sa.Column("peak_equity", sa.Numeric(36, 18), nullable=False),
        sa.Column("drawdown", sa.Numeric(36, 18), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open_positions", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("starting_equity > 0", name="ck_risk_starting_equity_positive"),
        sa.CheckConstraint("peak_equity > 0", name="ck_risk_peak_equity_positive"),
        sa.CheckConstraint("drawdown >= 0", name="ck_risk_drawdown_nonnegative"),
        sa.CheckConstraint("open_positions >= 0", name="ck_risk_open_positions_nonnegative"),
        sa.CheckConstraint(
            "system_state IN ('enabled', 'paused', 'killed')",
            name="ck_risk_system_state",
        ),
    )


def downgrade() -> None:
    op.drop_table("risk_state")
