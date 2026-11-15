"""Hosted / OpenAI-compatible providers.

Model discovery uses each provider's documented REST listing endpoint over httpx (so tests
can inject a transport with recorded responses); chat models are LangChain integrations.
Capabilities are only reported when the provider's listing states them explicitly.

* openai            GET {base}/models (Bearer)               → ChatOpenAI
* openai_compatible same API at a custom base URL (HF router, vLLM, LM Studio, Ollama /v1…)
* anthropic         GET {base}/v1/models (x-api-key)         → ChatAnthropic
* gemini            GET {base}/v1beta/models (x-goog-api-key) → ChatGoogleGenerativeAI
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx
from langchain_core.language_models import BaseChatModel

from app.runtime.providers.base import (
    ModelCapabilities,
    ModelInfo,
    ModelNotFoundError,
    ProviderError,
)

ProviderKind = Literal["ollama", "openai", "openai_compatible", "anthropic", "gemini"]
CLOUD_KINDS: tuple[ProviderKind, ...] = ("openai", "openai_compatible", "anthropic", "gemini")

DEFAULT_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com",
}
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096  # Anthropic requires max_tokens


@dataclass(frozen=True)
class ProviderSpec:
    """Everything needed to talk to one provider connection (secrets already decrypted)."""

    kind: ProviderKind
    base_url: str | None = None
    api_key: str | None = None


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _is_sdk_error(exc: BaseException) -> bool:
    module = type(exc).__module__.split(".")[0]
    return isinstance(exc, httpx.HTTPError) or module in {"openai", "anthropic", "google", "httpx"}


class _HttpProvider:
    """Shared discovery plumbing for providers with a REST model listing."""

    name: str
    kind: ProviderKind
    label: str

    def __init__(
        self,
        spec: ProviderSpec,
        name: str,
        *,
        timeout_s: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,  # injectable for tests
    ) -> None:
        self.name = name
        self.spec = spec
        self.base_url = (spec.base_url or DEFAULT_BASE_URLS.get(spec.kind, "")).rstrip("/")
        self.timeout_s = timeout_s
        self._transport = transport
        self._models: dict[str, ModelInfo] | None = None

    # -- to implement -------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _list_path(self) -> str:
        raise NotImplementedError

    def _parse(self, payload: Any) -> list[ModelInfo]:
        raise NotImplementedError

    def create_chat_model(self, model: str, params: dict[str, Any]) -> BaseChatModel:
        raise NotImplementedError

    # -- Provider protocol ----------------------------------------------------------
    async def _fetch(self) -> list[ModelInfo]:
        if not self.base_url:
            raise ProviderError(f"{self.label}: a base URL is required")
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_s, transport=self._transport
            ) as client:
                resp = await client.get(self._list_path(), headers=self._headers())
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.label} is not reachable") from e
        if resp.status_code in (401, 403):
            raise ProviderError(f"{self.label} rejected the credentials (HTTP {resp.status_code})")
        if resp.status_code >= 400:
            raise ProviderError(f"{self.label} returned HTTP {resp.status_code}")
        try:
            models = self._parse(resp.json())
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise ProviderError(f"{self.label} returned an unexpected model list") from e
        self._models = {m.name: m for m in models}
        return models

    async def is_available(self) -> bool:
        try:
            await self._fetch()
            return True
        except ProviderError:
            return False

    async def list_models(self) -> list[ModelInfo]:
        return sorted(await self._fetch(), key=lambda m: m.name)

    async def get_capabilities(self, model: str) -> ModelCapabilities:
        models = (
            self._models if self._models is not None else {m.name: m for m in await self._fetch()}
        )
        info = models.get(model)
        if info is None:
            raise ModelNotFoundError(f"Model '{model}' is not available from {self.label}")
        return ModelCapabilities(info.supports_tools, info.supports_thinking)

    def is_provider_error(self, exc: BaseException) -> bool:
        return _is_sdk_error(exc)


class OpenAICompatibleProvider(_HttpProvider):
    def __init__(self, spec: ProviderSpec, name: str, **kw: Any) -> None:
        super().__init__(spec, name, **kw)
        self.kind = spec.kind
        self.label = "OpenAI" if spec.kind == "openai" else "OpenAI-compatible endpoint"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.spec.api_key}"} if self.spec.api_key else {}

    def _list_path(self) -> str:
        return "/models"

    def _parse(self, payload: Any) -> list[ModelInfo]:
        out = []
        for m in payload["data"]:
            caps = m.get("capabilities") if isinstance(m.get("capabilities"), dict) else {}
            out.append(
                ModelInfo(
                    name=str(m["id"]),
                    size=None,
                    # The OpenAI listing has no capability flags; some compatible servers do.
                    supports_tools=_bool_or_none(caps.get("tools", caps.get("function_calling"))),
                    supports_thinking=_bool_or_none(caps.get("reasoning")),
                    context_window=m.get("context_length") or m.get("context_window"),
                )
            )
        return out

    def create_chat_model(self, model: str, params: dict[str, Any]) -> BaseChatModel:
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": self.spec.api_key or "not-needed",  # local servers accept any key
            "base_url": self.base_url,
            "stream_usage": True,
            "max_retries": 1,
            "timeout": 120,
        }
        for key in ("temperature", "top_p", "max_tokens"):
            if params.get(key) is not None:
                kwargs[key] = params[key]
        return ChatOpenAI(**kwargs)


class AnthropicProvider(_HttpProvider):
    kind: ProviderKind = "anthropic"
    label = "Anthropic"

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.spec.api_key or "", "anthropic-version": ANTHROPIC_VERSION}

    def _list_path(self) -> str:
        return "/v1/models?limit=1000"

    def _parse(self, payload: Any) -> list[ModelInfo]:
        out = []
        for m in payload["data"]:
            caps = m.get("capabilities") if isinstance(m.get("capabilities"), dict) else {}
            out.append(
                ModelInfo(
                    name=str(m["id"]),
                    size=None,
                    supports_tools=_bool_or_none(caps.get("tool_use", caps.get("tools"))),
                    supports_thinking=_bool_or_none(
                        caps.get("thinking", caps.get("extended_thinking"))
                    ),
                    context_window=m.get("max_input_tokens") or m.get("context_window"),
                    display_name=m.get("display_name"),
                )
            )
        return out

    def create_chat_model(self, model: str, params: dict[str, Any]) -> BaseChatModel:
        from langchain_anthropic import ChatAnthropic

        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": self.spec.api_key or "",
            "base_url": self.base_url,
            "max_tokens": params.get("max_tokens") or DEFAULT_MAX_TOKENS,
            "max_retries": 1,
            "timeout": 120,
            "stream_usage": True,
        }
        for key in ("temperature", "top_p"):
            if params.get(key) is not None:
                kwargs[key] = params[key]
        return ChatAnthropic(**kwargs)


class GeminiProvider(_HttpProvider):
    kind: ProviderKind = "gemini"
    label = "Google Gemini"

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.spec.api_key or ""}

    def _list_path(self) -> str:
        return "/v1beta/models?pageSize=1000"

    def _parse(self, payload: Any) -> list[ModelInfo]:
        out = []
        for m in payload.get("models", []):
            methods = m.get("supportedGenerationMethods") or []
            if "generateContent" not in methods:  # embeddings, etc.
                continue
            out.append(
                ModelInfo(
                    name=str(m["name"]).removeprefix("models/"),
                    size=None,
                    supports_tools=None,  # not stated by the listing
                    supports_thinking=_bool_or_none(m.get("thinking")),
                    context_window=m.get("inputTokenLimit"),
                    display_name=m.get("displayName"),
                )
            )
        return out

    def create_chat_model(self, model: str, params: dict[str, Any]) -> BaseChatModel:
        from langchain_google_genai import ChatGoogleGenerativeAI

        kwargs: dict[str, Any] = {
            "model": model,
            "google_api_key": self.spec.api_key or "",
            "max_retries": 1,
            "timeout": 120,
        }
        if params.get("max_tokens") is not None:
            kwargs["max_output_tokens"] = params["max_tokens"]
        for key in ("temperature", "top_p"):
            if params.get(key) is not None:
                kwargs[key] = params[key]
        return ChatGoogleGenerativeAI(**kwargs)


def build_cloud_provider(
    spec: ProviderSpec, name: str, transport: httpx.AsyncBaseTransport | None = None
) -> _HttpProvider:
    if spec.kind in ("openai", "openai_compatible"):
        return OpenAICompatibleProvider(spec, name, transport=transport)
    if spec.kind == "anthropic":
        return AnthropicProvider(spec, name, transport=transport)
    if spec.kind == "gemini":
        return GeminiProvider(spec, name, transport=transport)
    raise ValueError(f"Not a cloud provider kind: {spec.kind}")
