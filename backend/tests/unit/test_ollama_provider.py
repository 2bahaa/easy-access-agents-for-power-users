"""OllamaProvider against a mocked HTTP transport (no real Ollama)."""

import json

import httpx
import pytest
from langchain_ollama import ChatOllama

from app.runtime.providers.base import ModelNotFoundError, ProviderError
from app.runtime.providers.ollama import OllamaProvider

SHOW = {
    "llama3.2:1b": ["completion", "tools"],
    "qwen3:4b": ["completion", "tools", "thinking"],
    "gemma:2b": ["completion"],
}


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/version":
        return httpx.Response(200, json={"version": "0.40.16"})
    if request.url.path == "/api/tags":
        return httpx.Response(
            200, json={"models": [{"name": n, "size": i} for i, n in enumerate(SHOW)]}
        )
    if request.url.path == "/api/show":
        model = json.loads(request.content)["model"]
        if model not in SHOW:
            return httpx.Response(404, json={"error": f"model '{model}' not found"})
        return httpx.Response(200, json={"capabilities": SHOW[model]})
    return httpx.Response(404)


def refuse(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def provider(fn: object = handler) -> OllamaProvider:
    return OllamaProvider("http://ollama.test/", transport=httpx.MockTransport(fn))  # type: ignore[arg-type]


async def test_capabilities() -> None:
    caps = await provider().get_capabilities("qwen3:4b")
    assert caps.supports_tools and caps.supports_thinking
    caps = await provider().get_capabilities("gemma:2b")
    assert not caps.supports_tools and not caps.supports_thinking


async def test_missing_model() -> None:
    with pytest.raises(ModelNotFoundError, match="not available"):
        await provider().get_capabilities("nope:1b")


async def test_list_models() -> None:
    models = {m.name: m for m in await provider().list_models()}
    assert set(models) == set(SHOW)
    assert models["llama3.2:1b"].supports_tools
    assert not models["gemma:2b"].supports_tools
    assert models["qwen3:4b"].supports_thinking


async def test_unreachable() -> None:
    p = provider(refuse)
    assert await p.is_available() is False
    with pytest.raises(ProviderError, match="not reachable"):
        await p.get_capabilities("llama3.2:1b")
    with pytest.raises(ProviderError):
        await p.list_models()
    assert await provider().is_available() is True


def test_create_chat_model_maps_params() -> None:
    model = provider().create_chat_model(
        "qwen3:4b", {"temperature": 0.3, "num_ctx": 4096, "think": True}
    )
    assert isinstance(model, ChatOllama)
    assert (model.model, model.temperature, model.num_ctx, model.reasoning) == (
        "qwen3:4b",
        0.3,
        4096,
        True,
    )
    assert model.base_url == "http://ollama.test"


def test_is_provider_error() -> None:
    p = provider()
    assert p.is_provider_error(httpx.ConnectError("x"))
    assert p.is_provider_error(ConnectionError())
    assert not p.is_provider_error(ValueError())
