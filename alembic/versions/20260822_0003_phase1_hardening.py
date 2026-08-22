"""Add deterministic backtest dataset and execution metadata.

Revision ID: 20260822_0003
Revises: 20260822_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0003"
down_revision: str | None = "20260822_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("backtest_runs", sa.Column("candle_count", sa.Integer(), nullable=True))
    op.add_column(
        "backtest_runs",
        sa.Column("effective_start_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "backtest_runs", sa.Column("effective_end_time", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "backtest_runs", sa.Column("dataset_fingerprint", sa.String(length=96), nullable=True)
    )
    op.add_column("backtest_runs", sa.Column("fee_model", sa.String(length=32), nullable=True))

    op.execute(
        """
        UPDATE backtest_runs
        SET candle_count = 0,
            effective_start_time = start_time,
            effective_end_time = end_time,
            dataset_fingerprint = 'unavailable:pre-hardening',
            fee_model = 'percentage_of_fill_notional',
            code_version = COALESCE(code_version, 'unavailable')
        """
    )

    for column in (
        "candle_count",
        "effective_start_time",
        "effective_end_time",
        "dataset_fingerprint",
        "fee_model",
    ):
        op.alter_column("backtest_runs", column, nullable=False)
    op.alter_column("backtest_runs", "code_version", nullable=False)


def downgrade() -> None:
    op.alter_column("backtest_runs", "code_version", nullable=True)
    op.drop_column("backtest_runs", "fee_model")
    op.drop_column("backtest_runs", "dataset_fingerprint")
    op.drop_column("backtest_runs", "effective_end_time")
    op.drop_column("backtest_runs", "effective_start_time")
    op.drop_column("backtest_runs", "candle_count")
