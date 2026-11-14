import uuid

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from app.api.deps import (
    ProviderRegistryDep,
    RunManagerDep,
    SessionDep,
    SessionFactoryDep,
    SettingsDep,
    ToolRegistryDep,
)
from app.api.sse import sse_stream
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
    session: SessionDep, agent_id: uuid.UUID | None = None
) -> list[ConversationSummary]:
    items = await conversation_service.list_conversations(session, agent_id)
    return [ConversationSummary.model_validate(c) for c in items]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(data: ConversationCreate, session: SessionDep) -> ConversationSummary:
    conversation = await conversation_service.create_conversation(session, data)
    return ConversationSummary.model_validate(conversation)


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: uuid.UUID, session: SessionDep) -> ConversationRead:
    conversation = await conversation_service.get_conversation(session, conversation_id)
    messages = await conversation_service.list_messages(session, conversation_id)
    runs = await conversation_service.list_runs(session, conversation_id)
    return ConversationRead(
        **ConversationSummary.model_validate(conversation).model_dump(),
        messages=[MessageRead.model_validate(m) for m in messages],
        runs=[RunRead.model_validate(r) for r in runs],
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: uuid.UUID, session: SessionDep) -> None:
    await conversation_service.delete_conversation(session, conversation_id)


@router.post(
    "/{conversation_id}/messages",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "Run event stream"}},
)
async def post_message(
    conversation_id: uuid.UUID,
    data: MessageCreate,
    session: SessionDep,
    session_factory: SessionFactoryDep,
    settings: SettingsDep,
    providers: ProviderRegistryDep,
    tools: ToolRegistryDep,
    manager: RunManagerDep,
) -> StreamingResponse:
    """Persist the user message, start a run and stream its events (SSE).
    Errors before the run starts are normal HTTP errors; later ones arrive as run.failed."""
    active = await run_service.start_run(
        session,
        conversation_id,
        data.content,
        settings=settings,
        providers=providers,
        tools=tools,
        manager=manager,
        session_factory=session_factory,
    )
    return StreamingResponse(
        sse_stream(active.queue, on_disconnect=lambda: manager.cancel(active.run_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
