"""durable runs: queue status, cancel flag, worker heartbeat, one active run per conversation

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "cancel_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column("runs", sa.Column("worker_id", sa.String(length=100), nullable=True))
    op.add_column("runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    # Runs left active by the pre-queue runtime can never finish.
    op.execute(
        "UPDATE runs SET status = 'failed', error = 'Interrupted by a server restart', "
        "finished_at = now() WHERE status IN ('queued', 'running')"
    )
    op.create_index(
        "uq_runs_active_conversation",
        "runs",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_index(
        "ix_runs_queued", "runs", ["started_at"], postgresql_where=sa.text("status = 'queued'")
    )


def downgrade() -> None:
    op.drop_index("ix_runs_queued", table_name="runs")
    op.drop_index("uq_runs_active_conversation", table_name="runs")
    op.drop_column("runs", "heartbeat_at")
    op.drop_column("runs", "worker_id")
    op.drop_column("runs", "cancel_requested")
