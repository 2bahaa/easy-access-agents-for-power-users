"""Ollama provider (local). Capabilities come from POST /api/show -> "capabilities"."""

import asyncio
from typing import Any

import httpx
import ollama
from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama

from app.runtime.providers.base import (
    ModelCapabilities,
    ModelInfo,
    ModelNotFoundError,
    ProviderError,
)


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,  # injectable for tests
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout_s, transport=self._transport
        )

    async def is_available(self) -> bool:
        try:
            async with self._client() as client:
                (await client.get("/api/version")).raise_for_status()
            return True
        except httpx.HTTPError:
            return False

    async def _show(self, client: httpx.AsyncClient, model: str) -> ModelCapabilities:
        resp = await client.post("/api/show", json={"model": model})
        if resp.status_code == 404:
            raise ModelNotFoundError(f"Model '{model}' is not available in Ollama")
        resp.raise_for_status()
        caps = set(resp.json().get("capabilities") or [])
        return ModelCapabilities(
            supports_tools="tools" in caps, supports_thinking="thinking" in caps
        )

    async def get_capabilities(self, model: str) -> ModelCapabilities:
        try:
            async with self._client() as client:
                return await self._show(client, model)
        except httpx.HTTPError as e:
            raise ProviderError("Ollama is not reachable") from e

    async def list_models(self) -> list[ModelInfo]:
        try:
            async with self._client() as client:
                resp = await client.get("/api/tags")
                resp.raise_for_status()
                models = resp.json().get("models") or []
                caps = await asyncio.gather(*(self._show(client, m["name"]) for m in models))
        except httpx.HTTPError as e:
            raise ProviderError("Ollama is not reachable") from e
        return [
            ModelInfo(
                name=m["name"],
                size=m.get("size"),
                supports_tools=c.supports_tools,
                supports_thinking=c.supports_thinking,
            )
            for m, c in zip(models, caps, strict=True)
        ]

    def create_chat_model(self, model: str, params: dict[str, Any]) -> BaseChatModel:
        return ChatOllama(
            model=model,
            base_url=self.base_url,
            temperature=params.get("temperature"),
            num_ctx=params.get("num_ctx"),
            # True -> thinking goes to additional_kwargs["reasoning_content"];
            # None -> model default.
            reasoning=params.get("think"),
        )

    def is_provider_error(self, exc: BaseException) -> bool:
        return isinstance(
            exc,
            httpx.HTTPError
            | ConnectionError
            | ProviderError
            | ollama.ResponseError
            | ollama.RequestError,
        )
