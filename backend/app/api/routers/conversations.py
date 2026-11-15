import uuid
from typing import Literal

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from app.api.deps import (
    PrincipalDep,
    ProviderResolverDep,
    SessionDep,
    SessionFactoryDep,
    SettingsDep,
)
from app.api.hardening import RunRateLimit
from app.api.sse import SSE_HEADERS, follow_run_sse
from app.schemas.conversations import (
    ConversationCreate,
    ConversationRead,
    ConversationSummary,
    MessageCreate,
    MessageRead,
)
from app.schemas.runs import RunRead
from app.services import conversation_service, run_service

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(
    principal: PrincipalDep,
    session: SessionDep,
    agent_id: uuid.UUID | None = None,
    kind: Literal["chat", "playground"] = "chat",
) -> list[ConversationSummary]:
    items = await conversation_service.list_conversations(
        session, principal.workspace_id, agent_id, kind
    )
    return [ConversationSummary.model_validate(c) for c in items]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    data: ConversationCreate, principal: PrincipalDep, session: SessionDep
) -> ConversationSummary:
    conversation = await conversation_service.create_conversation(session, principal, data)
    return ConversationSummary.model_validate(conversation)


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> ConversationRead:
    conversation = await conversation_service.get_conversation(
        session, conversation_id, principal.workspace_id
    )
    messages = await conversation_service.list_messages(session, conversation_id)
    runs = await conversation_service.list_runs(session, conversation_id)
    return ConversationRead(
        **ConversationSummary.model_validate(conversation).model_dump(),
        messages=[MessageRead.model_validate(m) for m in messages],
        runs=[RunRead.model_validate(r) for r in runs],
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> None:
    await conversation_service.delete_conversation(session, principal, conversation_id)


@router.post(
    "/{conversation_id}/messages",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "Run event stream"}},
)
async def post_message(
    conversation_id: uuid.UUID,
    data: MessageCreate,
    principal: PrincipalDep,
    session: SessionDep,
    session_factory: SessionFactoryDep,
    settings: SettingsDep,
    resolver: ProviderResolverDep,
    _: RunRateLimit,
) -> StreamingResponse:
    """Persist the user message, queue a run and stream its events (SSE).
    Errors before the run is queued are normal HTTP errors; later ones arrive as run.failed.
    The run is durable: if the client disconnects it keeps running; reattach with
    GET /runs/{id}/stream (Last-Event-ID supported)."""
    run = await run_service.start_run(
        session, principal, conversation_id, data.content, resolver=resolver
    )
    return StreamingResponse(
        follow_run_sse(session_factory, settings.listen_dsn, run.id),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
