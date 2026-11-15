"""Knowledge collections (RAG) and agent memory.

* Upload → text extraction (txt/md/pdf…) → stored document (status `queued`) → a run worker
  chunks and embeds it (status `ready`/`failed`). Deleting a document deletes its chunks.
* Retrieval is hybrid: vector similarity (pgvector when installed, SQL array maths
  otherwise) + Postgres full-text search, merged with reciprocal rank fusion. Results carry
  citations (document, chunk, page) and are marked as untrusted content.
* Memory: agent-scoped facts saved/searched through tools; never shared across agents.
* Agents use both through per-run tools (`knowledge__search`, `memory__save`,
  `memory__search`) built here, so the runtime stays free of database code.
"""

import hashlib
import logging
import uuid
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import KnowledgeChunk, KnowledgeCollection, KnowledgeDocument, Memory
from app.knowledge.text import ExtractionError, chunk_pages, chunk_text, extract_text
from app.runtime.embeddings import Embedder
from app.runtime.providers.base import ProviderError
from app.runtime.providers.cloud import ProviderSpec
from app.services import audit_service
from app.services.errors import ConflictError, DomainValidationError, NotFoundError
from app.services.principal import Principal
from app.services.provider_service import ProviderResolver, get_connection
from app.services.pubsub import RUNS_CHANNEL, notify
from app.tools.base import EmptyConfig, ToolContext, ToolError
from app.tools.external import UNTRUSTED_PREFIX

logger = logging.getLogger(__name__)
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
RRF_K = 60
KNOWLEDGE_TOOL = "knowledge__search"
MEMORY_SAVE = "memory__save"
MEMORY_SEARCH = "memory__search"
DATA_TOOLS = (KNOWLEDGE_TOOL, MEMORY_SAVE, MEMORY_SEARCH)


# ---- embeddings & vector backend ------------------------------------------------------------


def embedder_for(
    resolver: ProviderResolver,
    settings: Settings,
    collection: KnowledgeCollection,
    conn_spec: ProviderSpec | None,
) -> Embedder:
    if conn_spec is not None:
        spec = conn_spec
    elif collection.embedding_provider == "ollama":
        spec = ProviderSpec(kind="ollama", base_url=settings.ollama_base_url)
    else:
        raise DomainValidationError(f"Unknown embedding provider '{collection.embedding_provider}'")
    try:
        return resolver.embedder_factory(spec, collection.embedding_model)
    except ValueError as e:
        raise DomainValidationError(str(e)) from e


async def _collection_embedder(
    session: AsyncSession,
    resolver: ProviderResolver,
    settings: Settings,
    collection: KnowledgeCollection,
) -> Embedder:
    spec = None
    if collection.embedding_connection_id is not None:
        conn = await get_connection(
            session, collection.workspace_id, collection.embedding_connection_id
        )
        spec = resolver.spec_for(conn)
    return embedder_for(resolver, settings, collection, spec)


_PGVECTOR: dict[str, bool] = {}


async def has_pgvector(session: AsyncSession) -> bool:
    key = str(getattr(session.bind, "url", ""))
    if key not in _PGVECTOR:
        found = await session.scalar(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
        _PGVECTOR[key] = found is not None
    return _PGVECTOR[key]


# ---- collections & documents ------------------------------------------------------------


async def get_collection(
    session: AsyncSession, workspace_id: uuid.UUID, collection_id: uuid.UUID
) -> KnowledgeCollection:
    c = await session.get(KnowledgeCollection, collection_id, populate_existing=True)
    if c is None or c.workspace_id != workspace_id:
        raise NotFoundError(f"Collection {collection_id} not found")
    return c


async def list_collections(
    session: AsyncSession, principal: Principal
) -> list[tuple[KnowledgeCollection, int, int]]:
    rows = await session.execute(
        select(
            KnowledgeCollection,
            func.count(KnowledgeDocument.id),
            func.coalesce(func.sum(KnowledgeDocument.chunk_count), 0),
        )
        .outerjoin(KnowledgeDocument, KnowledgeDocument.collection_id == KnowledgeCollection.id)
        .where(KnowledgeCollection.workspace_id == principal.workspace_id)
        .group_by(KnowledgeCollection.id)
        .order_by(KnowledgeCollection.name)
    )
    return [(c, int(n), int(chunks)) for c, n, chunks in rows.all()]


async def create_collection(
    session: AsyncSession,
    principal: Principal,
    *,
    name: str,
    description: str,
    embedding_provider: str,
    embedding_connection_id: uuid.UUID | None,
    embedding_model: str,
    chunk_size: int,
    chunk_overlap: int,
) -> KnowledgeCollection:
    principal.require("editor")
    if chunk_overlap >= chunk_size:
        raise DomainValidationError("Chunk overlap must be smaller than the chunk size")
    if embedding_connection_id is not None:
        try:
            conn = await get_connection(session, principal.workspace_id, embedding_connection_id)
        except NotFoundError:
            raise DomainValidationError("Unknown provider connection") from None
        if conn.kind == "anthropic":
            raise DomainValidationError(
                "Anthropic does not provide embeddings; choose another provider"
            )
    elif embedding_provider != "ollama":
        raise DomainValidationError("Use the built-in 'ollama' provider or a provider connection")
    if await session.scalar(
        select(KnowledgeCollection.id).where(
            KnowledgeCollection.workspace_id == principal.workspace_id,
            KnowledgeCollection.name == name,
        )
    ):
        raise ConflictError(f"A collection named '{name}' already exists")
    c = KnowledgeCollection(
        workspace_id=principal.workspace_id,
        name=name,
        description=description,
        embedding_provider="connection" if embedding_connection_id else embedding_provider,
        embedding_connection_id=embedding_connection_id,
        embedding_model=embedding_model,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    session.add(c)
    await session.flush()
    audit_service.record(
        session,
        "knowledge.collection_created",
        principal=principal,
        target_type="collection",
        target_id=c.id,
        name=name,
    )
    await session.commit()
    return c


async def delete_collection(
    session: AsyncSession, principal: Principal, collection_id: uuid.UUID
) -> None:
    principal.require("editor")
    c = await get_collection(session, principal.workspace_id, collection_id)
    await session.delete(c)  # documents and chunks cascade
    audit_service.record(
        session,
        "knowledge.collection_deleted",
        principal=principal,
        target_type="collection",
        target_id=collection_id,
    )
    await session.commit()


async def list_documents(
    session: AsyncSession, principal: Principal, collection_id: uuid.UUID
) -> Sequence[KnowledgeDocument]:
    await get_collection(session, principal.workspace_id, collection_id)
    stmt = select(KnowledgeDocument).where(KnowledgeDocument.collection_id == collection_id)
    return (await session.scalars(stmt.order_by(KnowledgeDocument.created_at.desc()))).all()


async def upload_document(
    session: AsyncSession,
    principal: Principal,
    settings: Settings,
    collection_id: uuid.UUID,
    filename: str,
    data: bytes,
    mime: str,
) -> KnowledgeDocument:
    principal.require("editor")
    collection = await get_collection(session, principal.workspace_id, collection_id)
    if len(data) > settings.knowledge_max_upload_bytes:
        raise DomainValidationError(
            f"File too large (max {settings.knowledge_max_upload_bytes // 1_000_000} MB)"
        )
    digest = hashlib.sha256(data).hexdigest()
    if await session.scalar(
        select(KnowledgeDocument.id).where(
            KnowledgeDocument.collection_id == collection.id, KnowledgeDocument.sha256 == digest
        )
    ):
        raise ConflictError("This file is already in the collection")
    try:
        body, pages = extract_text(filename, data)
    except ExtractionError as e:
        raise DomainValidationError(str(e)) from e
    doc = KnowledgeDocument(
        workspace_id=principal.workspace_id,
        collection_id=collection.id,
        title=filename[:300],
        mime=mime[:100] or "application/octet-stream",
        size_bytes=len(data),
        sha256=digest,
        text=body,
        pages=[[p, t] for p, t in pages] if pages else None,
        status="queued",
    )
    session.add(doc)
    await session.flush()
    await notify(session, RUNS_CHANNEL, "ingest")
    audit_service.record(
        session,
        "knowledge.document_uploaded",
        principal=principal,
        target_type="document",
        target_id=doc.id,
        title=doc.title,
    )
    await session.commit()
    return doc


async def delete_document(
    session: AsyncSession, principal: Principal, document_id: uuid.UUID
) -> None:
    principal.require("editor")
    doc = await session.get(KnowledgeDocument, document_id)
    if doc is None or doc.workspace_id != principal.workspace_id:
        raise NotFoundError("Document not found")
    await session.delete(doc)  # chunks cascade
    audit_service.record(
        session,
        "knowledge.document_deleted",
        principal=principal,
        target_type="document",
        target_id=document_id,
    )
    await session.commit()


async def process_next_document(
    session_factory: SessionFactory, resolver: ProviderResolver, settings: Settings
) -> bool:
    """Ingest one queued document (worker). Returns False when the queue is empty."""
    async with session_factory() as session:
        doc_id = await session.scalar(
            select(KnowledgeDocument.id)
            .where(KnowledgeDocument.status == "queued")
            .order_by(KnowledgeDocument.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if doc_id is None:
            return False
        doc = await session.get(KnowledgeDocument, doc_id)
        assert doc is not None
        doc.status = "processing"
        await session.commit()
    try:
        async with session_factory() as session:
            doc = await session.get(KnowledgeDocument, doc_id)
            if doc is None:
                return True
            collection = await session.get(KnowledgeCollection, doc.collection_id)
            assert collection is not None
            chunks = (
                chunk_pages(
                    [(int(p), str(t)) for p, t in doc.pages],
                    collection.chunk_size,
                    collection.chunk_overlap,
                )
                if doc.pages
                else chunk_text(doc.text, collection.chunk_size, collection.chunk_overlap)
            )
            embedder = await _collection_embedder(session, resolver, settings, collection)
            vectors = await embedder.embed([c.text for c in chunks])
            dims = {len(v) for v in vectors}
            if len(dims) > 1 or (
                collection.dims is not None and dims and collection.dims not in dims
            ):
                raise ProviderError("Embedding dimensions changed; re-create the collection")
            if collection.dims is None and dims:
                collection.dims = dims.pop()
            await session.execute(
                delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id)
            )
            session.add_all(
                KnowledgeChunk(
                    document_id=doc.id,
                    collection_id=collection.id,
                    ord=c.ord,
                    page=c.page,
                    text=c.text,
                    embedding=v,
                )
                for c, v in zip(chunks, vectors, strict=True)
            )
            doc.status, doc.error, doc.chunk_count = "ready", None, len(chunks)
            await session.commit()
    except (ProviderError, DomainValidationError, NotFoundError) as e:
        await _fail_document(session_factory, doc_id, str(e))
    except Exception:
        logger.exception("Ingestion of document %s failed", doc_id)
        await _fail_document(session_factory, doc_id, "Internal error while indexing the document")
    return True


async def _fail_document(session_factory: SessionFactory, doc_id: uuid.UUID, message: str) -> None:
    async with session_factory() as session:
        doc = await session.get(KnowledgeDocument, doc_id)
        if doc is not None:
            doc.status, doc.error = "failed", message[:500]
            await session.commit()


async def reindex_document(
    session: AsyncSession, principal: Principal, document_id: uuid.UUID
) -> KnowledgeDocument:
    principal.require("editor")
    doc = await session.get(KnowledgeDocument, document_id)
    if doc is None or doc.workspace_id != principal.workspace_id:
        raise NotFoundError("Document not found")
    doc.status, doc.error = "queued", None
    await notify(session, RUNS_CHANNEL, "ingest")
    await session.commit()
    return doc


# ---- retrieval ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    document_id: uuid.UUID
    document_title: str
    collection_id: uuid.UUID
    ord: int
    page: int | None
    text: str
    score: float


async def _vector_candidates(
    session: AsyncSession, collection_id: uuid.UUID, query_vec: list[float], limit: int
) -> list[int]:
    if await has_pgvector(session):
        vec = "[" + ",".join(f"{x:.7f}" for x in query_vec) + "]"
        stmt = text(
            "SELECT id FROM knowledge_chunks WHERE collection_id = :c "
            "AND array_length(embedding, 1) = :d "
            "ORDER BY (embedding::vector) <=> (CAST(:q AS vector)) LIMIT :n"
        ).bindparams(c=collection_id, d=len(query_vec), q=vec, n=limit)
    else:  # portable fallback: dot product of normalised vectors with SQL array maths
        stmt = text(
            "SELECT k.id FROM knowledge_chunks k WHERE k.collection_id = :c "
            "AND array_length(k.embedding, 1) = :d "
            "ORDER BY (SELECT sum(a * b) FROM "
            "unnest(k.embedding, CAST(:q AS double precision[])) AS t(a, b)) DESC "
            "LIMIT :n"
        ).bindparams(c=collection_id, d=len(query_vec), q=query_vec, n=limit)
    return [int(r) for r in (await session.scalars(stmt)).all()]


async def _text_candidates(
    session: AsyncSession, collection_id: uuid.UUID, query: str, limit: int
) -> list[int]:
    stmt = text(
        "SELECT id FROM knowledge_chunks WHERE collection_id = :c "
        "AND tsv @@ websearch_to_tsquery('simple', :q) "
        "ORDER BY ts_rank(tsv, websearch_to_tsquery('simple', :q)) DESC LIMIT :n"
    ).bindparams(c=collection_id, q=query, n=limit)
    return [int(r) for r in (await session.scalars(stmt)).all()]


def rrf(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    return scores


async def search(
    session: AsyncSession,
    resolver: ProviderResolver,
    settings: Settings,
    workspace_id: uuid.UUID,
    collection_ids: Sequence[uuid.UUID],
    query: str,
    top_k: int = 5,
) -> list[Hit]:
    rankings: list[list[int]] = []
    for cid in collection_ids:
        collection = await get_collection(session, workspace_id, cid)
        try:
            embedder = await _collection_embedder(session, resolver, settings, collection)
            (query_vec,) = await embedder.embed([query])
            rankings.append(await _vector_candidates(session, cid, query_vec, top_k * 4))
        except ProviderError as e:  # keyword search still works without the embedder
            logger.warning("Vector search skipped for collection %s: %s", cid, e)
        rankings.append(await _text_candidates(session, cid, query, top_k * 4))
    scores = rrf(rankings)
    best = sorted(scores, key=lambda i: scores[i], reverse=True)[:top_k]
    if not best:
        return []
    rows = await session.execute(
        select(KnowledgeChunk, KnowledgeDocument.title)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .where(KnowledgeChunk.id.in_(best))
    )
    by_id = {c.id: (c, title) for c, title in rows.all()}
    return [
        Hit(
            chunk_id=i,
            document_id=by_id[i][0].document_id,
            document_title=by_id[i][1],
            collection_id=by_id[i][0].collection_id,
            ord=by_id[i][0].ord,
            page=by_id[i][0].page,
            text=by_id[i][0].text,
            score=round(scores[i], 5),
        )
        for i in best
        if i in by_id
    ]


def format_hits(hits: list[Hit]) -> str:
    if not hits:
        return "No relevant passages found."
    blocks = []
    for n, h in enumerate(hits, 1):
        where = (
            f"{h.document_title}" + (f", page {h.page}" if h.page else "") + f", chunk {h.ord + 1}"
        )
        blocks.append(f"[{n}] ({where})\n{h.text}")
    return UNTRUSTED_PREFIX + "Cite sources as [n].\n\n" + "\n\n".join(blocks)


# ---- memory ----------------------------------------------------------------------------------


async def save_memory(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    content: str,
    run_id: uuid.UUID | None,
) -> Memory:
    memory = Memory(
        workspace_id=workspace_id, agent_id=agent_id, content=content.strip()[:2000], run_id=run_id
    )
    session.add(memory)
    await session.commit()
    return memory


async def search_memories(
    session: AsyncSession, workspace_id: uuid.UUID, agent_id: uuid.UUID, query: str, limit: int = 5
) -> list[Memory]:
    """Keyword search over the agent's own memories (most relevant, then most recent)."""
    base = select(Memory).where(Memory.workspace_id == workspace_id, Memory.agent_id == agent_id)
    if query.strip():
        ranked = base.where(text("tsv @@ websearch_to_tsquery('simple', :q)")).order_by(
            text("ts_rank(tsv, websearch_to_tsquery('simple', :q)) DESC"), Memory.created_at.desc()
        )
        found = (await session.scalars(ranked.limit(limit), {"q": query})).all()
        if found:
            return list(found)
    return list((await session.scalars(base.order_by(Memory.created_at.desc()).limit(limit))).all())


async def list_memories(
    session: AsyncSession, principal: Principal, agent_id: uuid.UUID
) -> Sequence[Memory]:
    from app.services.agent_service import get_agent

    await get_agent(session, agent_id, principal.workspace_id)
    stmt = select(Memory).where(
        Memory.workspace_id == principal.workspace_id, Memory.agent_id == agent_id
    )
    return (await session.scalars(stmt.order_by(Memory.created_at.desc()).limit(500))).all()


async def delete_memory(session: AsyncSession, principal: Principal, memory_id: uuid.UUID) -> None:
    principal.require("editor")
    memory = await session.get(Memory, memory_id)
    if memory is None or memory.workspace_id != principal.workspace_id:
        raise NotFoundError("Memory not found")
    await session.delete(memory)
    await session.commit()


async def clear_memories(session: AsyncSession, principal: Principal, agent_id: uuid.UUID) -> int:
    principal.require("editor")
    from app.services.agent_service import get_agent

    await get_agent(session, agent_id, principal.workspace_id)
    result = await session.execute(
        delete(Memory).where(
            Memory.workspace_id == principal.workspace_id, Memory.agent_id == agent_id
        )
    )
    audit_service.record(
        session, "memory.cleared", principal=principal, target_type="agent", target_id=agent_id
    )
    await session.commit()
    return int(getattr(result, "rowcount", 0) or 0)


# ---- per-run data tools ------------------------------------------------------------------------


class KnowledgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)


class _DataTool:
    """ToolLike with a JSON-Schema-free Pydantic argument model and a closure doing the I/O."""

    name: str
    description: str
    timeout_s: float | None = 30.0
    args_model: type[BaseModel]

    def __init__(
        self,
        name: str,
        description: str,
        args_model: type[BaseModel],
        fn: Callable[[BaseModel], Any],
    ) -> None:
        self.name, self.description, self.args_model, self._fn = name, description, args_model, fn

    def parse_args(self, raw: dict[str, Any]) -> BaseModel:
        return self.args_model.model_validate(raw)

    def parse_config(self, raw: dict[str, Any]) -> BaseModel:
        return EmptyConfig()  # access was resolved when the run was prepared

    def args_schema(self) -> dict[str, Any]:
        return self.args_model.model_json_schema()

    def config_schema(self) -> dict[str, Any]:
        return EmptyConfig.model_json_schema()

    def to_function_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_schema(),
            },
        }

    async def run(self, args: BaseModel, config: BaseModel, ctx: ToolContext) -> str:
        result: str = await self._fn(args)
        return result


class SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="What to look for")
    top_k: int = Field(default=5, ge=1, le=10, description="How many passages to return")


class SaveArgs(BaseModel):
    content: str = Field(min_length=1, max_length=1000, description="The fact to remember")


class RecallArgs(BaseModel):
    query: str = Field(default="", max_length=300, description="Keywords (empty = most recent)")


TOOL_DESCRIPTIONS = {
    KNOWLEDGE_TOOL: (
        "Search the agent's knowledge collections and return relevant passages with citations."
    ),
    MEMORY_SAVE: "Save a short fact to the agent's long-term memory for future conversations.",
    MEMORY_SEARCH: "Search the agent's long-term memory.",
}
TOOL_ARGS: dict[str, type[BaseModel]] = {
    KNOWLEDGE_TOOL: SearchArgs,
    MEMORY_SAVE: SaveArgs,
    MEMORY_SEARCH: RecallArgs,
}


def describe_tools() -> list[_DataTool]:
    async def nothing(_: BaseModel) -> str:
        raise ToolError("Not available outside a run")

    return [_DataTool(n, TOOL_DESCRIPTIONS[n], TOOL_ARGS[n], nothing) for n in DATA_TOOLS]


async def normalize_grant(
    session: AsyncSession, workspace_id: uuid.UUID, name: str, config: dict[str, Any]
) -> dict[str, Any]:
    if name == KNOWLEDGE_TOOL:
        try:
            cfg = KnowledgeConfig.model_validate(config)
        except Exception as e:
            raise DomainValidationError(
                "knowledge__search needs config {collection_ids: [...]}"
            ) from e
        found = set(
            await session.scalars(
                select(KnowledgeCollection.id).where(
                    KnowledgeCollection.workspace_id == workspace_id,
                    KnowledgeCollection.id.in_(cfg.collection_ids),
                )
            )
        )
        missing = [str(c) for c in cfg.collection_ids if c not in found]
        if missing:
            raise DomainValidationError(f"Unknown collection id(s): {', '.join(missing)}")
        return cfg.model_dump(mode="json")
    if name in (MEMORY_SAVE, MEMORY_SEARCH):
        if config:
            raise DomainValidationError(f"Tool '{name}' takes no configuration")
        return {}
    raise DomainValidationError(f"Unknown tool: '{name}'")


def runtime_tools(
    session_factory: SessionFactory,
    resolver: ProviderResolver,
    settings: Settings,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    run_id: uuid.UUID,
    grants: dict[str, dict[str, Any]],
) -> list[_DataTool]:
    """Bind the agent's granted data tools to this run (closures open their own sessions)."""
    tools: list[_DataTool] = []
    if KNOWLEDGE_TOOL in grants:
        ids = [uuid.UUID(str(c)) for c in grants[KNOWLEDGE_TOOL].get("collection_ids", [])]

        async def do_search(args: BaseModel) -> str:
            assert isinstance(args, SearchArgs)
            async with session_factory() as s:
                try:
                    hits = await search(
                        s, resolver, settings, workspace_id, ids, args.query, args.top_k
                    )
                except NotFoundError:
                    raise ToolError("A configured collection no longer exists") from None
            return format_hits(hits)

        tools.append(
            _DataTool(KNOWLEDGE_TOOL, TOOL_DESCRIPTIONS[KNOWLEDGE_TOOL], SearchArgs, do_search)
        )
    if MEMORY_SAVE in grants:

        async def do_save(args: BaseModel) -> str:
            assert isinstance(args, SaveArgs)
            async with session_factory() as s:
                await save_memory(s, workspace_id, agent_id, args.content, run_id)
            return "Saved to memory."

        tools.append(_DataTool(MEMORY_SAVE, TOOL_DESCRIPTIONS[MEMORY_SAVE], SaveArgs, do_save))
    if MEMORY_SEARCH in grants:

        async def do_recall(args: BaseModel) -> str:
            assert isinstance(args, RecallArgs)
            async with session_factory() as s:
                found = await search_memories(s, workspace_id, agent_id, args.query)
            if not found:
                return "No memories yet."
            return UNTRUSTED_PREFIX + "\n".join(f"- {m.content}" for m in found)

        tools.append(
            _DataTool(MEMORY_SEARCH, TOOL_DESCRIPTIONS[MEMORY_SEARCH], RecallArgs, do_recall)
        )
    return tools
