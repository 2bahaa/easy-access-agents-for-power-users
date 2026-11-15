"""MCP servers and tools, custom HTTP tools

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    now = sa.text("now()")
    ts = [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
    ]
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=32), nullable=False),
        sa.Column("transport", sa.String(length=16), nullable=False),
        sa.Column("command", sa.String(length=500), nullable=True),
        sa.Column("args", JSONB, nullable=False),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("secrets_enc", sa.Text(), nullable=True),
        sa.Column("secret_keys", JSONB, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("timeout_s", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        *ts,
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_mcp_servers_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mcp_servers")),
        sa.UniqueConstraint("workspace_id", "slug", name=op.f("uq_mcp_servers_workspace_id")),
    )
    op.create_index(op.f("ix_mcp_servers_workspace_id"), "mcp_servers", ["workspace_id"])
    op.create_table(
        "mcp_tools",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("input_schema", JSONB, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["mcp_servers.id"],
            name=op.f("fk_mcp_tools_server_id_mcp_servers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mcp_tools")),
        sa.UniqueConstraint("server_id", "name", name=op.f("uq_mcp_tools_server_id")),
    )
    op.create_index(op.f("ix_mcp_tools_server_id"), "mcp_tools", ["server_id"])
    op.create_table(
        "custom_tools",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("url_template", sa.String(length=1000), nullable=False),
        sa.Column("params", JSONB, nullable=False),
        sa.Column("headers_enc", sa.Text(), nullable=True),
        sa.Column("header_keys", JSONB, nullable=False),
        sa.Column("timeout_s", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        *[sa.Column(c.name, c.type, server_default=now, nullable=False) for c in ts],
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_custom_tools_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_tools")),
        sa.UniqueConstraint("workspace_id", "slug", name=op.f("uq_custom_tools_workspace_id")),
    )
    op.create_index(op.f("ix_custom_tools_workspace_id"), "custom_tools", ["workspace_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_custom_tools_workspace_id"), table_name="custom_tools")
    op.drop_table("custom_tools")
    op.drop_index(op.f("ix_mcp_tools_server_id"), table_name="mcp_tools")
    op.drop_table("mcp_tools")
    op.drop_index(op.f("ix_mcp_servers_workspace_id"), table_name="mcp_servers")
    op.drop_table("mcp_servers")
