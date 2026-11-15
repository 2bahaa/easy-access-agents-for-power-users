"""knowledge collections, documents and chunks (hybrid search), agent memories

pgvector is enabled when the server provides it (used for fast exact cosine scoring);
otherwise similarity is computed with SQL array arithmetic. Full-text search uses a
generated tsvector column with a GIN index.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    # Optional extension: never fails the migration when unavailable.
    op.execute(
        "DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS vector; "
        "EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'pgvector not available'; END $$;"
    )
    now = sa.text("now()")
    ts = lambda: [  # noqa: E731
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
    ]
    op.create_table(
        "knowledge_collections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("embedding_provider", sa.String(length=50), nullable=False),
        sa.Column("embedding_connection_id", sa.Uuid(), nullable=True),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("dims", sa.Integer(), nullable=True),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False),
        *ts(),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_knowledge_collections_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["embedding_connection_id"],
            ["provider_connections.id"],
            name=op.f("fk_knowledge_collections_embedding_connection_id_provider_connections"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_collections")),
        sa.UniqueConstraint(
            "workspace_id", "name", name=op.f("uq_knowledge_collections_workspace_id")
        ),
    )
    op.create_index(
        op.f("ix_knowledge_collections_workspace_id"), "knowledge_collections", ["workspace_id"]
    )
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("mime", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("pages", JSONB, nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        *ts(),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_knowledge_documents_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["knowledge_collections.id"],
            name=op.f("fk_knowledge_documents_collection_id_knowledge_collections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_documents")),
    )
    op.create_index(
        op.f("ix_knowledge_documents_workspace_id"), "knowledge_documents", ["workspace_id"]
    )
    op.create_index(
        op.f("ix_knowledge_documents_collection_id"), "knowledge_documents", ["collection_id"]
    )
    op.create_index(op.f("ix_knowledge_documents_status"), "knowledge_documents", ["status"])
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", postgresql.ARRAY(sa.Float()), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            name=op.f("fk_knowledge_chunks_document_id_knowledge_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["knowledge_collections.id"],
            name=op.f("fk_knowledge_chunks_collection_id_knowledge_collections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_chunks")),
    )
    op.create_index(op.f("ix_knowledge_chunks_document_id"), "knowledge_chunks", ["document_id"])
    op.create_index(
        op.f("ix_knowledge_chunks_collection_id"), "knowledge_chunks", ["collection_id"]
    )
    # Full-text search: generated tsvector ('simple' config: language-agnostic).
    op.execute(
        "ALTER TABLE knowledge_chunks ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED"
    )
    op.execute("CREATE INDEX ix_knowledge_chunks_tsv ON knowledge_chunks USING gin (tsv)")

    op.create_table(
        "memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_memories_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_memories_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_memories_run_id_runs"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memories")),
    )
    op.create_index(op.f("ix_memories_workspace_id"), "memories", ["workspace_id"])
    op.create_index(op.f("ix_memories_agent_id"), "memories", ["agent_id"])
    op.execute(
        "ALTER TABLE memories ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED"
    )
    op.execute("CREATE INDEX ix_memories_tsv ON memories USING gin (tsv)")


def downgrade() -> None:
    op.drop_table("memories")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
    op.drop_table("knowledge_collections")
