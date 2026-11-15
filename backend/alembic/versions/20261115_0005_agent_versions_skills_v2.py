"""agent versions (published snapshots), playground conversations, run agent_version;
skill versions, tags and category

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    now = sa.text("now()")
    op.create_table(
        "agent_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("write_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("runtime_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_versions_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_agent_versions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_versions")),
        sa.UniqueConstraint("agent_id", "version", name=op.f("uq_agent_versions_agent_id")),
    )
    op.create_index(op.f("ix_agent_versions_agent_id"), "agent_versions", ["agent_id"])
    op.create_table(
        "skill_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            name=op.f("fk_skill_versions_skill_id_skills"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_skill_versions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skill_versions")),
        sa.UniqueConstraint("skill_id", "version", name=op.f("uq_skill_versions_skill_id")),
    )
    op.create_index(op.f("ix_skill_versions_skill_id"), "skill_versions", ["skill_id"])
    op.add_column(
        "skills",
        sa.Column("category", sa.String(length=50), server_default="general", nullable=False),
    )
    op.add_column(
        "skills",
        sa.Column(
            "tags", postgresql.ARRAY(sa.String(length=40)), server_default="{}", nullable=False
        ),
    )
    op.add_column("skills", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column(
        "conversations",
        sa.Column("kind", sa.String(length=16), server_default="chat", nullable=False),
    )
    op.add_column("runs", sa.Column("agent_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "agent_version")
    op.drop_column("conversations", "kind")
    op.drop_column("skills", "version")
    op.drop_column("skills", "tags")
    op.drop_column("skills", "category")
    op.drop_index(op.f("ix_skill_versions_skill_id"), table_name="skill_versions")
    op.drop_table("skill_versions")
    op.drop_index(op.f("ix_agent_versions_agent_id"), table_name="agent_versions")
    op.drop_table("agent_versions")
