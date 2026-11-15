"""Text embeddings through the configured providers (DB-free, like the chat providers).

* ollama                       POST {base}/api/embed {model, input: [...]}
* openai / openai_compatible   POST {base}/embeddings {model, input: [...]}
* gemini                       POST {base}/v1beta/models/{model}:batchEmbedContents
Anthropic offers no embeddings API.
"""

from __future__ import annotations

import math
from typing import Any, Protocol

import httpx

from app.runtime.providers.base import ProviderError
from app.runtime.providers.cloud import DEFAULT_BASE_URLS, ProviderSpec

MAX_BATCH = 32


class Embedder(Protocol):
    model: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class HttpEmbedder:
    """Embeds with one of the supported REST APIs; vectors are L2-normalised so cosine
    similarity is a dot product."""

    def __init__(
        self,
        spec: ProviderSpec,
        model: str,
        *,
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if spec.kind == "anthropic":
            raise ValueError("Anthropic does not provide an embeddings API")
        self.spec = spec
        self.model = model
        self.base_url = (spec.base_url or DEFAULT_BASE_URLS.get(spec.kind, "")).rstrip("/")
        self.timeout_s = timeout_s
        self._transport = transport

    async def _post(self, path: str, body: dict[str, Any], headers: dict[str, str]) -> Any:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_s, transport=self._transport
            ) as client:
                resp = await client.post(path, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise ProviderError("The embedding provider is not reachable") from e
        if resp.status_code == 404:
            raise ProviderError(f"Embedding model '{self.model}' is not available")
        if resp.status_code in (400, 501) and self.spec.kind == "ollama":
            raise ProviderError(
                f"'{self.model}' cannot produce embeddings; use an embedding model such as "
                "nomic-embed-text (ollama pull nomic-embed-text)"
            )
        if resp.status_code >= 400:
            raise ProviderError(f"The embedding provider returned HTTP {resp.status_code}")
        return resp.json()

    async def _batch(self, texts: list[str]) -> list[list[float]]:
        kind = self.spec.kind
        key = self.spec.api_key
        if kind == "ollama":
            data = await self._post("/api/embed", {"model": self.model, "input": texts}, {})
            vectors = data["embeddings"]
        elif kind in ("openai", "openai_compatible"):
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            data = await self._post("/embeddings", {"model": self.model, "input": texts}, headers)
            vectors = [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
        elif kind == "gemini":
            body = {
                "requests": [
                    {"model": f"models/{self.model}", "content": {"parts": [{"text": t}]}}
                    for t in texts
                ]
            }
            data = await self._post(
                f"/v1beta/models/{self.model}:batchEmbedContents",
                body,
                {"x-goog-api-key": key or ""},
            )
            vectors = [e["values"] for e in data["embeddings"]]
        else:  # pragma: no cover - guarded by the service
            raise ProviderError(f"Embeddings are not supported for {kind}")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ProviderError("The embedding provider returned an unexpected response")
        return [normalize([float(x) for x in v]) for v in vectors]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), MAX_BATCH):
            out.extend(await self._batch(texts[i : i + MAX_BATCH]))
        return out
