"""Provider adapters against recorded API responses (httpx.MockTransport) — no network."""

import json
from typing import Any

import httpx
import pytest

from app.runtime.providers.base import ModelNotFoundError, ProviderError
from app.runtime.providers.cloud import (
    AnthropicProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
    ProviderSpec,
)

OPENAI_MODELS = {
    "object": "list",
    "data": [
        {"id": "gpt-4.1-mini", "object": "model", "created": 1, "owned_by": "openai"},
        {"id": "gpt-4.1", "object": "model", "created": 1, "owned_by": "openai"},
    ],
}
COMPAT_MODELS = {  # e.g. an OpenRouter/vLLM-style server that reports capabilities
    "data": [
        {"id": "local/llama", "context_length": 8192, "capabilities": {"tools": True}},
        {"id": "local/tiny", "capabilities": {"function_calling": False}},
        {"id": "local/plain"},
    ]
}
ANTHROPIC_MODELS = {
    "data": [
        {
            "type": "model",
            "id": "claude-sonnet-x",
            "display_name": "Claude Sonnet X",
            "created_at": "2026-01-01T00:00:00Z",
        },
    ],
    "has_more": False,
}
GEMINI_MODELS = {
    "models": [
        {
            "name": "models/gemini-x-flash",
            "displayName": "Gemini X Flash",
            "inputTokenLimit": 1048576,
            "supportedGenerationMethods": ["generateContent", "countTokens"],
            "thinking": True,
        },
        {"name": "models/text-embedding-x", "supportedGenerationMethods": ["embedContent"]},
    ]
}


def recorder(status: int, body: Any) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, content=json.dumps(body).encode())

    return httpx.MockTransport(handler), seen


async def test_openai_lists_models_with_unknown_capabilities() -> None:
    transport, seen = recorder(200, OPENAI_MODELS)
    p = OpenAICompatibleProvider(
        ProviderSpec("openai", api_key="sk-test"), "c1", transport=transport
    )
    models = await p.list_models()
    assert [m.name for m in models] == ["gpt-4.1", "gpt-4.1-mini"]
    # The OpenAI listing states no capabilities: never guessed from the name.
    assert all(m.supports_tools is None for m in models)
    assert str(seen[0].url) == "https://api.openai.com/v1/models"
    assert seen[0].headers["authorization"] == "Bearer sk-test"
    caps = await p.get_capabilities("gpt-4.1")
    assert caps.supports_tools is None
    with pytest.raises(ModelNotFoundError):
        await p.get_capabilities("nope")


async def test_openai_compatible_reads_explicit_capabilities() -> None:
    transport, seen = recorder(200, COMPAT_MODELS)
    spec = ProviderSpec("openai_compatible", base_url="http://127.0.0.1:1234/v1/")
    p = OpenAICompatibleProvider(spec, "c2", transport=transport)
    by_name = {m.name: m for m in await p.list_models()}
    assert by_name["local/llama"].supports_tools is True
    assert by_name["local/llama"].context_window == 8192
    assert by_name["local/tiny"].supports_tools is False
    assert by_name["local/plain"].supports_tools is None
    assert str(seen[0].url) == "http://127.0.0.1:1234/v1/models"
    assert "authorization" not in seen[0].headers  # no key configured


async def test_anthropic_listing_and_headers() -> None:
    transport, seen = recorder(200, ANTHROPIC_MODELS)
    p = AnthropicProvider(ProviderSpec("anthropic", api_key="ak"), "c3", transport=transport)
    (model,) = await p.list_models()
    assert (model.name, model.display_name, model.supports_tools) == (
        "claude-sonnet-x",
        "Claude Sonnet X",
        None,
    )
    assert seen[0].headers["x-api-key"] == "ak"
    assert seen[0].headers["anthropic-version"] == "2023-06-01"
    assert seen[0].url.path == "/v1/models"


async def test_gemini_filters_non_chat_models() -> None:
    transport, seen = recorder(200, GEMINI_MODELS)
    p = GeminiProvider(ProviderSpec("gemini", api_key="gk"), "c4", transport=transport)
    (model,) = await p.list_models()
    assert model.name == "gemini-x-flash"  # "models/" prefix stripped, embeddings skipped
    assert model.context_window == 1048576 and model.supports_thinking is True
    assert seen[0].headers["x-goog-api-key"] == "gk"


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "rejected the credentials"), (403, "rejected the credentials"), (500, "HTTP 500")],
)
async def test_http_errors_become_user_safe_provider_errors(status: int, message: str) -> None:
    transport, _ = recorder(status, {"error": "secret internal detail"})
    p = OpenAICompatibleProvider(ProviderSpec("openai", api_key="sk"), "c", transport=transport)
    with pytest.raises(ProviderError, match=message) as exc:
        await p.list_models()
    assert "secret internal detail" not in str(exc.value)
    assert await p.is_available() is False


async def test_unreachable_and_malformed() -> None:
    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    p = OpenAICompatibleProvider(
        ProviderSpec("openai_compatible", base_url="http://127.0.0.1:9"),
        "c",
        transport=httpx.MockTransport(boom),
    )
    with pytest.raises(ProviderError, match="not reachable"):
        await p.list_models()
    transport, _ = recorder(200, {"unexpected": True})
    p2 = OpenAICompatibleProvider(ProviderSpec("openai", api_key="k"), "c", transport=transport)
    with pytest.raises(ProviderError, match="unexpected model list"):
        await p2.list_models()


def test_chat_model_parameter_mapping() -> None:
    params = {"temperature": 0.3, "top_p": 0.9, "max_tokens": 256}
    openai = OpenAICompatibleProvider(ProviderSpec("openai", api_key="sk"), "c").create_chat_model(
        "gpt-x", params
    )
    assert (openai.model_name, openai.temperature, openai.top_p, openai.max_tokens) == (
        "gpt-x",
        0.3,
        0.9,
        256,
    )  # type: ignore[attr-defined]
    assert openai.openai_api_base == "https://api.openai.com/v1"  # type: ignore[attr-defined]

    compat = OpenAICompatibleProvider(
        ProviderSpec("openai_compatible", base_url="http://127.0.0.1:1234/v1"), "c"
    ).create_chat_model("m", {})
    assert compat.openai_api_base == "http://127.0.0.1:1234/v1"  # type: ignore[attr-defined]

    anthropic = AnthropicProvider(ProviderSpec("anthropic", api_key="ak"), "c").create_chat_model(
        "claude-x", {}
    )
    assert anthropic.max_tokens == 4096  # type: ignore[attr-defined]  # required by Anthropic
    anthropic2 = AnthropicProvider(ProviderSpec("anthropic", api_key="ak"), "c").create_chat_model(
        "claude-x", params
    )
    assert (anthropic2.max_tokens, anthropic2.temperature) == (256, 0.3)  # type: ignore[attr-defined]

    gemini = GeminiProvider(ProviderSpec("gemini", api_key="gk"), "c").create_chat_model(
        "gemini-x", params
    )
    assert (gemini.max_output_tokens, gemini.temperature) == (256, 0.3)  # type: ignore[attr-defined]


def test_provider_error_classification() -> None:
    p = OpenAICompatibleProvider(ProviderSpec("openai", api_key="k"), "c")
    import openai

    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    assert p.is_provider_error(openai.APIConnectionError(request=req))
    assert p.is_provider_error(httpx.ReadTimeout("slow"))
    assert not p.is_provider_error(ValueError("bug in our code"))
