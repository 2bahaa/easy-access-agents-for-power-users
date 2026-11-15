"""Providers & models: built-in providers (registry), workspace connections (encrypted
credentials), capability overrides, health checks and the live tool-calling probe.

`ProviderResolver` is the only way services and workers obtain a `Provider` for an agent:
it scopes connections to the workspace, decrypts secrets in memory only, and applies
capability overrides for models whose provider does not report tool support.
"""

import asyncio
import ipaddress
import logging
import socket
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.crypto import SecretBox, SecretDecryptionError, SecretsNotConfiguredError, secret_hint
from app.db.models import Agent, AgentVersion, ModelCapabilityOverride, ProviderConnection
from app.runtime.providers.base import ModelCapabilities, ModelInfo, Provider, ProviderError
from app.runtime.providers.cloud import ProviderSpec
from app.runtime.providers.registry import ProviderRegistry, UnknownProviderError, build_provider
from app.schemas.providers import (
    ModelRead,
    ProbeResult,
    ProviderConnectionCreate,
    ProviderConnectionUpdate,
    ProviderRead,
)
from app.services import audit_service
from app.services.errors import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
    ProviderUnavailableError,
)
from app.services.principal import Principal

logger = logging.getLogger(__name__)

ProviderFactory = Callable[[ProviderSpec, str], Provider]
KIND_LABELS = {
    "ollama": "Ollama",
    "openai": "OpenAI",
    "openai_compatible": "OpenAI-compatible",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
}
NEEDS_KEY = {"openai", "anthropic", "gemini"}
NEEDS_URL = {"ollama", "openai_compatible"}
PROBE_TIMEOUT_S = 45.0


# ---- resolution -------------------------------------------------------------------------


class _WithOverrides:
    """Provider wrapper applying probe/user tool-support overrides (only where the provider
    itself reports nothing)."""

    def __init__(self, inner: Provider, overrides: dict[str, bool]) -> None:
        self._inner = inner
        self._overrides = overrides
        self.name = inner.name

    async def is_available(self) -> bool:
        return await self._inner.is_available()

    async def list_models(self) -> list[ModelInfo]:
        return await self._inner.list_models()

    async def get_capabilities(self, model: str) -> ModelCapabilities:
        caps = await self._inner.get_capabilities(model)
        if caps.supports_tools is None and model in self._overrides:
            return ModelCapabilities(self._overrides[model], caps.supports_thinking)
        return caps

    def create_chat_model(self, model: str, params: dict[str, Any]) -> BaseChatModel:
        return self._inner.create_chat_model(model, params)

    def is_provider_error(self, exc: BaseException) -> bool:
        return self._inner.is_provider_error(exc)


@dataclass
class ProviderResolver:
    registry: ProviderRegistry  # built-in providers (server configuration)
    secrets: SecretBox
    factory: ProviderFactory = build_provider

    def spec_for(self, conn: ProviderConnection) -> ProviderSpec:
        api_key = None
        if conn.secret_enc:
            try:
                api_key = self.secrets.decrypt(conn.secret_enc)
            except (SecretsNotConfiguredError, SecretDecryptionError) as e:
                raise ProviderUnavailableError(
                    f"The API key of '{conn.name}' cannot be decrypted on this server; re-enter it"
                ) from e
        return ProviderSpec(kind=conn.kind, base_url=conn.base_url, api_key=api_key)  # type: ignore[arg-type]

    async def resolve(
        self,
        session: AsyncSession,
        workspace_id: uuid.UUID,
        provider_name: str,
        connection_id: uuid.UUID | None,
    ) -> Provider:
        """The provider for an agent. Raises DomainValidationError for unknown ones."""
        if connection_id is None:
            try:
                provider = self.registry.get(provider_name)
            except UnknownProviderError:
                raise DomainValidationError(f"Unknown provider: '{provider_name}'") from None
            key = provider_name
        else:
            conn = await get_connection(session, workspace_id, connection_id)
            provider = self.factory(self.spec_for(conn), str(conn.id))
            key = str(conn.id)
        overrides = await _overrides(session, workspace_id, key)
        return _WithOverrides(provider, overrides) if overrides else provider


async def _overrides(session: AsyncSession, workspace_id: uuid.UUID, key: str) -> dict[str, bool]:
    rows = await session.execute(
        select(ModelCapabilityOverride.model, ModelCapabilityOverride.supports_tools).where(
            ModelCapabilityOverride.workspace_id == workspace_id,
            ModelCapabilityOverride.provider_key == key,
        )
    )
    return {m: t for m, t in rows.all()}


# ---- connections ------------------------------------------------------------------------


async def get_connection(
    session: AsyncSession, workspace_id: uuid.UUID, connection_id: uuid.UUID
) -> ProviderConnection:
    conn = await session.get(ProviderConnection, connection_id, populate_existing=True)
    if conn is None or conn.workspace_id != workspace_id:
        raise NotFoundError(f"Provider connection {connection_id} not found")
    return conn


def _parse_ref(ref: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(ref)
    except ValueError:
        return None


def validate_base_url(url: str | None, settings: Settings) -> str | None:
    """http(s) only; never link-local/metadata addresses or explicitly blocked hosts (SSRF).
    Loopback and private networks stay allowed: local model servers are a core use case."""
    if url is None or not url.strip():
        return None
    url = url.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise DomainValidationError("Base URL must be an http(s) URL with a host")
    if parsed.username or parsed.password:
        raise DomainValidationError("Put credentials in the API key field, not in the URL")
    host = parsed.hostname.lower()
    blocked = {h.strip().lower() for h in settings.provider_blocked_hosts.split(",") if h.strip()}
    blocked |= {"metadata.google.internal", "metadata", "169.254.169.254"}
    if host in blocked:
        raise DomainValidationError("This host is not allowed as a provider endpoint")
    try:
        infos = socket.getaddrinfo(host, None)
        addresses = {ipaddress.ip_address(i[4][0]) for i in infos}
    except (socket.gaierror, ValueError):
        addresses = set()  # unresolvable now: allowed (may resolve later); checked again on use
    if any(a.is_link_local or a.is_multicast or a.is_unspecified for a in addresses):
        raise DomainValidationError("Link-local and metadata addresses are not allowed")
    return url


def _to_read(conn: ProviderConnection) -> ProviderRead:
    return ProviderRead(
        name=str(conn.id),
        id=conn.id,
        label=conn.name,
        kind=conn.kind,
        builtin=False,
        base_url=conn.base_url,
        has_secret=conn.secret_enc is not None,
        secret_hint=conn.secret_hint,
        available=None if conn.status == "unknown" else conn.status == "ok",
        status=conn.status,
        last_error=conn.last_error,
        last_checked_at=conn.last_checked_at,
    )


async def list_providers(
    session: AsyncSession, principal: Principal, resolver: ProviderResolver
) -> list[ProviderRead]:
    builtins = resolver.registry.all()
    available = await asyncio.gather(*(p.is_available() for p in builtins))
    out = [
        ProviderRead(
            name=p.name,
            label=f"{KIND_LABELS.get(p.name, p.name)} (server)",
            kind=getattr(p, "kind", "ollama"),
            builtin=True,
            available=a,
            status="ok" if a else "error",
        )
        for p, a in zip(builtins, available, strict=True)
    ]
    conns = await session.scalars(
        select(ProviderConnection)
        .where(ProviderConnection.workspace_id == principal.workspace_id)
        .order_by(ProviderConnection.name)
    )
    return out + [_to_read(c) for c in conns]


def _check_kind_requirements(kind: str, base_url: str | None, has_key: bool) -> None:
    if kind in NEEDS_URL and not base_url:
        raise DomainValidationError(f"A base URL is required for {KIND_LABELS[kind]}")
    if kind in NEEDS_KEY and not has_key:
        raise DomainValidationError(f"An API key is required for {KIND_LABELS[kind]}")


def _encrypt(resolver: ProviderResolver, api_key: str) -> tuple[str, str]:
    try:
        return resolver.secrets.encrypt(api_key), secret_hint(api_key)
    except SecretsNotConfiguredError as e:
        raise DomainValidationError(str(e)) from e


async def create_connection(
    session: AsyncSession,
    principal: Principal,
    resolver: ProviderResolver,
    settings: Settings,
    data: ProviderConnectionCreate,
) -> ProviderConnection:
    principal.require("admin")
    base_url = validate_base_url(data.base_url, settings)
    _check_kind_requirements(data.kind, base_url, bool(data.api_key))
    if await session.scalar(
        select(ProviderConnection.id).where(
            ProviderConnection.workspace_id == principal.workspace_id,
            ProviderConnection.name == data.name,
        )
    ):
        raise ConflictError(f"A provider named '{data.name}' already exists")
    conn = ProviderConnection(
        workspace_id=principal.workspace_id, name=data.name, kind=data.kind, base_url=base_url
    )
    if data.api_key:
        conn.secret_enc, conn.secret_hint = _encrypt(resolver, data.api_key)
    session.add(conn)
    await session.flush()
    audit_service.record(
        session,
        "provider.created",
        principal=principal,
        target_type="provider",
        target_id=conn.id,
        kind=data.kind,
        name=data.name,
    )
    await session.commit()
    return conn


async def update_connection(
    session: AsyncSession,
    principal: Principal,
    resolver: ProviderResolver,
    settings: Settings,
    connection_id: uuid.UUID,
    data: ProviderConnectionUpdate,
) -> ProviderConnection:
    principal.require("admin")
    conn = await get_connection(session, principal.workspace_id, connection_id)
    changed: list[str] = []
    if data.name is not None and data.name != conn.name:
        conn.name, changed = data.name, [*changed, "name"]
    if "base_url" in data.model_fields_set:
        conn.base_url, changed = validate_base_url(data.base_url, settings), [*changed, "base_url"]
    if data.api_key is not None:
        if data.api_key == "":
            conn.secret_enc = conn.secret_hint = None
        else:
            conn.secret_enc, conn.secret_hint = _encrypt(resolver, data.api_key)
        changed.append("api_key")
    _check_kind_requirements(conn.kind, conn.base_url, conn.secret_enc is not None)
    if changed:
        conn.status, conn.last_error = "unknown", None
        conn.updated_at = func.now()
        audit_service.record(
            session,
            "provider.updated",
            principal=principal,
            target_type="provider",
            target_id=conn.id,
            fields=changed,
        )
    await session.commit()
    return await get_connection(session, principal.workspace_id, connection_id)


async def delete_connection(
    session: AsyncSession, principal: Principal, connection_id: uuid.UUID
) -> None:
    principal.require("admin")
    conn = await get_connection(session, principal.workspace_id, connection_id)
    used_by = await session.scalar(
        select(func.count()).select_from(Agent).where(Agent.connection_id == connection_id)
    )
    pinned = await session.scalar(
        select(func.count())
        .select_from(AgentVersion)
        .where(AgentVersion.runtime_config["connection_id"].astext == str(connection_id))
    )
    if used_by or pinned:
        raise ConflictError(
            "Agents (or their published versions) use this provider; switch them first"
        )
    await session.execute(
        delete(ModelCapabilityOverride).where(
            ModelCapabilityOverride.workspace_id == principal.workspace_id,
            ModelCapabilityOverride.provider_key == str(connection_id),
        )
    )
    await session.delete(conn)
    audit_service.record(
        session,
        "provider.deleted",
        principal=principal,
        target_type="provider",
        target_id=connection_id,
        name=conn.name,
    )
    await session.commit()


# ---- models, health, probe --------------------------------------------------------------


async def _provider_for_ref(
    session: AsyncSession, principal: Principal, resolver: ProviderResolver, ref: str
) -> tuple[Provider, str, ProviderConnection | None]:
    conn_id = _parse_ref(ref)
    if conn_id is None:
        try:
            return resolver.registry.get(ref), ref, None
        except UnknownProviderError:
            raise NotFoundError(f"Provider '{ref}' not found") from None
    conn = await get_connection(session, principal.workspace_id, conn_id)
    return resolver.factory(resolver.spec_for(conn), str(conn.id)), str(conn.id), conn


async def _record_status(
    session: AsyncSession, conn: ProviderConnection | None, error: str | None
) -> None:
    if conn is None:
        return
    conn.status = "error" if error else "ok"
    conn.last_error = error
    conn.last_checked_at = func.now()
    await session.commit()
    await session.refresh(conn)


async def list_models(
    session: AsyncSession, principal: Principal, resolver: ProviderResolver, ref: str
) -> list[ModelRead]:
    provider, key, conn = await _provider_for_ref(session, principal, resolver, ref)
    try:
        models = await provider.list_models()
    except ProviderError as e:
        await _record_status(session, conn, str(e))
        raise ProviderUnavailableError(str(e)) from e
    await _record_status(session, conn, None)
    overrides = await _override_rows(session, principal.workspace_id, key)
    out = []
    for m in models:
        tools, source = m.supports_tools, "provider" if m.supports_tools is not None else None
        if tools is None and m.name in overrides:
            tools, source = overrides[m.name].supports_tools, overrides[m.name].source
        out.append(
            ModelRead(
                name=m.name,
                size=m.size,
                supports_tools=tools,
                supports_thinking=m.supports_thinking,
                tools_source=source,
                context_window=m.context_window,
                display_name=m.display_name,
            )
        )
    return out


async def _override_rows(
    session: AsyncSession, workspace_id: uuid.UUID, key: str
) -> dict[str, ModelCapabilityOverride]:
    rows = await session.scalars(
        select(ModelCapabilityOverride).where(
            ModelCapabilityOverride.workspace_id == workspace_id,
            ModelCapabilityOverride.provider_key == key,
        )
    )
    return {r.model: r for r in rows}


async def test_connection(
    session: AsyncSession, principal: Principal, resolver: ProviderResolver, ref: str
) -> ProviderRead:
    """Health check: list models; records the result on the connection."""
    provider, _key, conn = await _provider_for_ref(session, principal, resolver, ref)
    try:
        count = len(await provider.list_models())
        await _record_status(session, conn, None)
        logger.info("Provider %s healthy (%d models)", ref, count)
    except ProviderError as e:
        await _record_status(session, conn, str(e))
    if conn is None:
        ok = await provider.is_available()
        return ProviderRead(
            name=ref,
            label=ref,
            kind="ollama",
            builtin=True,
            available=ok,
            status="ok" if ok else "error",
        )
    return _to_read(await get_connection(session, principal.workspace_id, conn.id))


async def set_override(
    session: AsyncSession,
    principal: Principal,
    resolver: ProviderResolver,
    ref: str,
    model: str,
    supports_tools: bool | None,
    source: str = "user",
) -> None:
    principal.require("editor")
    _provider, key, _conn = await _provider_for_ref(session, principal, resolver, ref)
    existing = await session.get(ModelCapabilityOverride, (principal.workspace_id, key, model))
    if supports_tools is None:
        if existing is not None:
            await session.delete(existing)
    elif existing is None:
        session.add(
            ModelCapabilityOverride(
                workspace_id=principal.workspace_id,
                provider_key=key,
                model=model,
                supports_tools=supports_tools,
                source=source,
            )
        )
    else:
        existing.supports_tools, existing.source = supports_tools, source
    await session.commit()


def _ping_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "ping",
            "description": "Health check. Call this tool when asked to.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


async def probe_tool_support(
    session: AsyncSession,
    principal: Principal,
    resolver: ProviderResolver,
    ref: str,
    model: str,
) -> ProbeResult:
    """Ask the model to call a trivial tool; record whether it produced a tool call.
    Costs one small request to the provider (user-initiated)."""
    principal.require("editor")
    provider, _key, _conn = await _provider_for_ref(session, principal, resolver, ref)
    try:
        chat = provider.create_chat_model(model, {"temperature": 0, "max_tokens": 64})
        bound: Any = chat.bind_tools([_ping_tool()])
        reply = await asyncio.wait_for(
            bound.ainvoke([HumanMessage("Call the ping tool now. Do not answer in text.")]),
            timeout=PROBE_TIMEOUT_S,
        )
    except TimeoutError as e:
        raise ProviderUnavailableError(
            "The model did not answer the tool-calling check in time"
        ) from e
    except Exception as e:
        message = str(e).lower()
        if "tool" in message or "function" in message:  # provider explicitly rejects tools
            await set_override(session, principal, resolver, ref, model, False, source="probe")
            return ProbeResult(
                model=model, supports_tools=False, detail="The provider rejected tool use"
            )
        if provider.is_provider_error(e) or isinstance(e, ValueError):
            raise ProviderUnavailableError(f"Tool-calling check failed: {str(e)[:200]}") from e
        raise
    calls = getattr(reply, "tool_calls", None) or []
    ok = any(c.get("name") == "ping" for c in calls)
    await set_override(session, principal, resolver, ref, model, ok, source="probe")
    detail = "The model called the tool" if ok else "The model answered without calling the tool"
    return ProbeResult(model=model, supports_tools=ok, detail=detail)


def validate_params_for_kind(kind: str, params: dict[str, Any]) -> None:
    """Reject parameters the agent's provider kind does not support (no silent ignoring)."""
    if kind != "ollama":
        unsupported = [k for k in ("num_ctx", "think") if params.get(k) is not None]
        if unsupported:
            raise DomainValidationError(
                f"{', '.join(unsupported)} only apply to Ollama models; remove them for "
                f"{KIND_LABELS.get(kind, kind)}"
            )
