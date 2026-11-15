"""provider connections (encrypted secrets), model capability overrides, agents.connection_id

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    now = sa.text("now()")
    op.create_table(
        "provider_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("secret_enc", sa.Text(), nullable=True),
        sa.Column("secret_hint", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_provider_connections_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_connections")),
        sa.UniqueConstraint(
            "workspace_id", "name", name=op.f("uq_provider_connections_workspace_id")
        ),
    )
    op.create_index(
        op.f("ix_provider_connections_workspace_id"), "provider_connections", ["workspace_id"]
    )
    op.create_table(
        "model_capability_overrides",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("supports_tools", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_model_capability_overrides_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "provider_key", "model", name=op.f("pk_model_capability_overrides")
        ),
    )
    op.add_column("agents", sa.Column("connection_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_agents_connection_id_provider_connections"),
        "agents",
        "provider_connections",
        ["connection_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_agents_connection_id"), "agents", ["connection_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_agents_connection_id"), table_name="agents")
    op.drop_constraint(
        op.f("fk_agents_connection_id_provider_connections"), "agents", type_="foreignkey"
    )
    op.drop_column("agents", "connection_id")
    op.drop_table("model_capability_overrides")
    op.drop_index(op.f("ix_provider_connections_workspace_id"), table_name="provider_connections")
    op.drop_table("provider_connections")
