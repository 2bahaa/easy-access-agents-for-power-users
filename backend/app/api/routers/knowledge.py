"""Knowledge collections, documents, search and agent memories."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import PrincipalDep, ProviderResolverDep, SessionDep, SettingsDep
from app.db.models import KnowledgeCollection
from app.services import knowledge_service

router = APIRouter(tags=["knowledge"])


class CollectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    embedding_provider: str = Field(default="ollama", max_length=50)
    embedding_connection_id: uuid.UUID | None = None
    embedding_model: str = Field(min_length=1, max_length=200)
    chunk_size: int = Field(default=900, ge=200, le=4000)
    chunk_overlap: int = Field(default=150, ge=0, le=1000)


class CollectionRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    embedding_provider: str
    embedding_connection_id: uuid.UUID | None
    embedding_model: str
    dims: int | None
    chunk_size: int
    chunk_overlap: int
    document_count: int = 0
    chunk_count: int = 0
    created_at: datetime


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    collection_id: uuid.UUID
    title: str
    mime: str
    size_bytes: int
    status: str
    error: str | None
    chunk_count: int
    created_at: datetime


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)


class HitRead(BaseModel):
    document_id: uuid.UUID
    document_title: str
    collection_id: uuid.UUID
    chunk: int
    page: int | None
    text: str
    score: float


class MemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    content: str
    run_id: uuid.UUID | None
    created_at: datetime


def _read(c: KnowledgeCollection, docs: int = 0, chunks: int = 0) -> CollectionRead:
    return CollectionRead(
        id=c.id,
        name=c.name,
        description=c.description,
        embedding_provider=c.embedding_provider,
        embedding_connection_id=c.embedding_connection_id,
        embedding_model=c.embedding_model,
        dims=c.dims,
        chunk_size=c.chunk_size,
        chunk_overlap=c.chunk_overlap,
        document_count=docs,
        chunk_count=chunks,
        created_at=c.created_at,
    )


@router.get("/knowledge/collections")
async def list_collections(principal: PrincipalDep, session: SessionDep) -> list[CollectionRead]:
    return [
        _read(c, d, k) for c, d, k in await knowledge_service.list_collections(session, principal)
    ]


@router.post("/knowledge/collections", status_code=status.HTTP_201_CREATED)
async def create_collection(
    data: CollectionCreate, principal: PrincipalDep, session: SessionDep
) -> CollectionRead:
    c = await knowledge_service.create_collection(session, principal, **data.model_dump())
    return _read(c)


@router.delete("/knowledge/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> None:
    await knowledge_service.delete_collection(session, principal, collection_id)


@router.get("/knowledge/collections/{collection_id}/documents")
async def list_documents(
    collection_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[DocumentRead]:
    return [
        DocumentRead.model_validate(d)
        for d in await knowledge_service.list_documents(session, principal, collection_id)
    ]


@router.post(
    "/knowledge/collections/{collection_id}/documents", status_code=status.HTTP_201_CREATED
)
async def upload_document(
    collection_id: uuid.UUID,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    filename: Annotated[str, Query(min_length=1, max_length=300)],
) -> DocumentRead:
    """Upload a file as the raw request body (`?filename=` names it). It is indexed in the
    background; poll the document status."""
    data = await request.body()
    doc = await knowledge_service.upload_document(
        session,
        principal,
        settings,
        collection_id,
        filename,
        data,
        request.headers.get("content-type", "application/octet-stream"),
    )
    return DocumentRead.model_validate(doc)


@router.delete("/knowledge/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> None:
    await knowledge_service.delete_document(session, principal, document_id)


@router.post("/knowledge/documents/{document_id}/reindex")
async def reindex_document(
    document_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> DocumentRead:
    return DocumentRead.model_validate(
        await knowledge_service.reindex_document(session, principal, document_id)
    )


@router.post("/knowledge/search")
async def search(
    data: SearchRequest,
    principal: PrincipalDep,
    session: SessionDep,
    resolver: ProviderResolverDep,
    settings: SettingsDep,
) -> list[HitRead]:
    hits = await knowledge_service.search(
        session,
        resolver,
        settings,
        principal.workspace_id,
        data.collection_ids,
        data.query,
        data.top_k,
    )
    return [
        HitRead(
            document_id=h.document_id,
            document_title=h.document_title,
            collection_id=h.collection_id,
            chunk=h.ord,
            page=h.page,
            text=h.text,
            score=h.score,
        )
        for h in hits
    ]


@router.get("/agents/{agent_id}/memories")
async def list_memories(
    agent_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[MemoryRead]:
    return [
        MemoryRead.model_validate(m)
        for m in await knowledge_service.list_memories(session, principal, agent_id)
    ]


@router.delete("/agents/{agent_id}/memories", status_code=status.HTTP_204_NO_CONTENT)
async def clear_memories(agent_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> None:
    await knowledge_service.clear_memories(session, principal, agent_id)


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> None:
    await knowledge_service.delete_memory(session, principal, memory_id)
