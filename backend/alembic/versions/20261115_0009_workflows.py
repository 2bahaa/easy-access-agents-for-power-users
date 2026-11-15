"""visual workflows: workflows, versions; workflow runs share the runs table

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    now = sa.text("now()")
    op.create_table(
        "workflows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("spec", JSONB, nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workflows_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_workflows_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflows")),
    )
    op.create_index(op.f("ix_workflows_workspace_id"), "workflows", ["workspace_id"])
    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("spec", JSONB, nullable=False),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("fk_workflow_versions_workflow_id_workflows"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_workflow_versions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_versions")),
        sa.UniqueConstraint(
            "workflow_id", "version", name=op.f("uq_workflow_versions_workflow_id")
        ),
    )
    op.create_index(op.f("ix_workflow_versions_workflow_id"), "workflow_versions", ["workflow_id"])

    op.add_column(
        "runs", sa.Column("kind", sa.String(length=16), server_default="agent", nullable=False)
    )
    op.add_column("runs", sa.Column("workflow_id", sa.Uuid(), nullable=True))
    op.add_column("runs", sa.Column("inputs", JSONB, nullable=True))
    op.add_column("runs", sa.Column("output", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("state", JSONB, nullable=True))
    op.create_foreign_key(
        op.f("fk_runs_workflow_id_workflows"),
        "runs",
        "workflows",
        ["workflow_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_runs_workflow_id"), "runs", ["workflow_id"])
    op.alter_column("runs", "conversation_id", nullable=True)
    op.alter_column("runs", "agent_id", nullable=True)
    op.alter_column("approval_requests", "conversation_id", nullable=True)
    op.alter_column("approval_requests", "agent_id", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM approval_requests WHERE conversation_id IS NULL OR agent_id IS NULL")
    op.alter_column("approval_requests", "agent_id", nullable=False)
    op.alter_column("approval_requests", "conversation_id", nullable=False)
    op.execute("DELETE FROM runs WHERE kind = 'workflow'")
    op.alter_column("runs", "agent_id", nullable=False)
    op.alter_column("runs", "conversation_id", nullable=False)
    op.drop_index(op.f("ix_runs_workflow_id"), table_name="runs")
    op.drop_constraint(op.f("fk_runs_workflow_id_workflows"), "runs", type_="foreignkey")
    for column in ("state", "output", "inputs", "workflow_id", "kind"):
        op.drop_column("runs", column)
    op.drop_index(op.f("ix_workflow_versions_workflow_id"), table_name="workflow_versions")
    op.drop_table("workflow_versions")
    op.drop_index(op.f("ix_workflows_workspace_id"), table_name="workflows")
    op.drop_table("workflows")
