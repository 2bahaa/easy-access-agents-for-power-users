"""human approval: approval requests and policies, per-tool approval flag, run continuations;
waiting_approval counts as an active run

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def _active_index(statuses: str) -> None:
    op.drop_index("uq_runs_active_conversation", table_name="runs")
    op.create_index(
        "uq_runs_active_conversation",
        "runs",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text(f"status IN ({statuses})"),
    )


def upgrade() -> None:
    now = sa.text("now()")
    op.add_column(
        "agent_tools",
        sa.Column(
            "requires_approval", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column("runs", sa.Column("resume_of", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_runs_resume_of_runs"), "runs", "runs", ["resume_of"], ["id"], ondelete="SET NULL"
    )
    op.create_index(op.f("ix_runs_resume_of"), "runs", ["resume_of"])
    _active_index("'queued', 'running', 'waiting_approval'")

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.String(length=100), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("args", JSONB, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("edited_args", JSONB, nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_approval_requests_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name=op.f("fk_approval_requests_run_id_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_approval_requests_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_approval_requests_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
            name=op.f("fk_approval_requests_decided_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_requests")),
        sa.UniqueConstraint("run_id", "call_id", name=op.f("uq_approval_requests_run_id")),
    )
    op.create_index(
        op.f("ix_approval_requests_workspace_id"), "approval_requests", ["workspace_id"]
    )
    op.create_index(op.f("ix_approval_requests_run_id"), "approval_requests", ["run_id"])
    op.create_index(op.f("ix_approval_requests_status"), "approval_requests", ["status"])

    op.create_table(
        "approval_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("tool_pattern", sa.String(length=100), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_approval_policies_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_approval_policies_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_approval_policies_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_policies")),
    )
    op.create_index(
        op.f("ix_approval_policies_workspace_id"), "approval_policies", ["workspace_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_approval_policies_workspace_id"), table_name="approval_policies")
    op.drop_table("approval_policies")
    op.drop_index(op.f("ix_approval_requests_status"), table_name="approval_requests")
    op.drop_index(op.f("ix_approval_requests_run_id"), table_name="approval_requests")
    op.drop_index(op.f("ix_approval_requests_workspace_id"), table_name="approval_requests")
    op.drop_table("approval_requests")
    op.execute("UPDATE runs SET status = 'cancelled' WHERE status = 'waiting_approval'")
    _active_index("'queued', 'running'")
    op.drop_index(op.f("ix_runs_resume_of"), table_name="runs")
    op.drop_constraint(op.f("fk_runs_resume_of_runs"), "runs", type_="foreignkey")
    op.drop_column("runs", "resume_of")
    op.drop_column("agent_tools", "requires_approval")
