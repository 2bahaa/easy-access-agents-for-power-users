"""Deterministic test doubles: a scripted chat model and an in-memory provider.

No automated test talks to a real Ollama.
"""

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from app.runtime.providers.base import (
    ModelCapabilities,
    ModelInfo,
    ModelNotFoundError,
    ProviderError,
)


def tool_call(name: str, args: dict[str, Any], call_id: str | None = None) -> dict[str, Any]:
    return {"name": name, "args": args, "id": call_id or f"call_{uuid.uuid4().hex[:8]}"}


def reply(content: str = "", *tool_calls: dict[str, Any], reasoning: str = "") -> AIMessage:
    kwargs = {"reasoning_content": reasoning} if reasoning else {}
    return AIMessage(content=content, tool_calls=list(tool_calls), additional_kwargs=kwargs)


class FakeChatModel(BaseChatModel):
    """Replays `responses` in order, streaming content word by word and tool calls
    in the final chunk (like Ollama). Records prompts and bound tools."""

    responses: list[AIMessage] = Field(default_factory=list)
    delay_s: float = 0.0
    error: Exception | None = None
    prompts: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tools: list[dict[str, Any]] | None = None

    @property
    def _llm_type(self) -> str:
        return "fake-scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "FakeChatModel":
        self.bound_tools = list(tools)
        return self

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        self.prompts.append(list(messages))
        if self.error is not None:
            raise self.error
        if not self.responses:
            return AIMessage(content="(no scripted response left)")
        return self.responses.pop(0)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def _chunks(self, msg: AIMessage) -> Iterator[ChatGenerationChunk]:
        reasoning = msg.additional_kwargs.get("reasoning_content")
        if reasoning:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="", additional_kwargs={"reasoning_content": reasoning}
                )
            )
        assert isinstance(msg.content, str)
        for piece in re.findall(r"\S+\s*|\s+", msg.content):
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {"name": tc["name"], "args": json.dumps(tc["args"]), "id": tc["id"], "index": i}
                    for i, tc in enumerate(msg.tool_calls)
                ],
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        )

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        for chunk in self._chunks(self._next(messages)):
            yield chunk


class FakeProvider:
    name = "ollama"  # stands in for the default provider

    def __init__(
        self,
        model: FakeChatModel | None = None,
        *,
        no_tool_models: set[str] | None = None,
        missing_models: set[str] | None = None,
        unknown_tool_models: set[str] | None = None,
        available: bool = True,
    ) -> None:
        self.model = model or FakeChatModel()
        self.no_tool_models = no_tool_models or set()
        self.missing_models = missing_models or set()
        self.unknown_tool_models = unknown_tool_models or set()
        self.available = available
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.specs: list[Any] = []  # ProviderSpecs this fake was built from (cloud factory)

    async def is_available(self) -> bool:
        return self.available

    async def get_capabilities(self, model: str) -> ModelCapabilities:
        if model in self.missing_models:
            raise ModelNotFoundError(f"Model '{model}' is not available in Ollama")
        if model in self.unknown_tool_models:  # provider does not report tool support
            return ModelCapabilities(supports_tools=None, supports_thinking=None)
        return ModelCapabilities(
            supports_tools=model not in self.no_tool_models, supports_thinking=False
        )

    async def list_models(self) -> list[ModelInfo]:
        if not self.available:
            raise ProviderError("Ollama is not reachable")
        return [
            ModelInfo(name="fake-tools:1b", size=1, supports_tools=True, supports_thinking=False),
            ModelInfo(name="fake-plain:1b", size=2, supports_tools=False, supports_thinking=True),
            *[
                ModelInfo(name=m, size=None, supports_tools=None, supports_thinking=None)
                for m in sorted(self.unknown_tool_models)
            ],
        ]

    def create_chat_model(self, model: str, params: dict[str, Any]) -> BaseChatModel:
        self.created.append((model, params))
        return self.model

    def is_provider_error(self, exc: BaseException) -> bool:
        return isinstance(exc, ConnectionError)


class FakeEmbedder:
    """Deterministic bag-of-words embeddings (hashed into 64 dims, L2-normalised): texts
    sharing words are similar. Model "broken" fails like an unreachable provider."""

    dims = 64

    def __init__(self, model: str, calls: list[list[str]] | None = None) -> None:
        self.model = model
        self.calls = calls if calls is not None else []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib
        import math

        if self.model == "broken":
            raise ProviderError("The embedding provider is not reachable")
        self.calls.append(list(texts))
        out = []
        for t in texts:
            vec = [0.0] * self.dims
            for word in re.findall(r"[a-z0-9]+", t.lower()):
                h = int(hashlib.sha256(word.encode()).hexdigest(), 16)
                vec[h % self.dims] += 1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out
