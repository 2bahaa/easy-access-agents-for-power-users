"""HTTP hardening: request size limit, security headers and the per-user run rate limit."""

from typing import Annotated

from fastapi import Depends, Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.deps import PrincipalDep
from app.api.ratelimit import SlidingWindowLimiter

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
]


class BodySizeLimitMiddleware:
    """Rejects bodies above a limit, by Content-Length and while streaming (chunked bodies).
    Paths in `overrides` (prefix, limit) get their own limit, e.g. document uploads."""

    def __init__(self, app: ASGIApp, max_bytes: int, overrides: list[tuple[str, int]]) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.overrides = overrides

    def _limit(self, path: str) -> int:
        for prefix, limit in self.overrides:
            if path.startswith(prefix):
                return limit
        return self.max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self._limit(scope["path"])
        for name, value in scope["headers"]:
            if name == b"content-length" and value.isdigit() and int(value) > limit:
                await _reject(send, limit)
                return
        if any(name == b"content-length" for name, _ in scope["headers"]):
            await self.app(scope, receive, send)  # declared size already checked
            return
        # No Content-Length (chunked): buffer up to the limit before the app sees the body.
        messages: list[Message] = []
        received = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            received += len(message.get("body", b""))
            if received > limit:
                await _reject(send, limit)
                return
            if not message.get("more_body", False):
                break

        async def replay() -> Message:
            return messages.pop(0) if messages else await receive()

        await self.app(scope, replay, send)


async def _reject(send: Send, limit: int) -> None:
    body = (
        b'{"type":"about:blank","title":"Request too large","status":413,'
        b'"detail":"The request body exceeds ' + str(limit).encode() + b' bytes"}'
    )
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/problem+json")],
        }
    )
    await send({"type": "http.response.body", "body": body})


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + SECURITY_HEADERS
            await send(message)

        await self.app(scope, receive, with_headers)


async def limit_runs(request: Request, principal: PrincipalDep) -> None:
    """Per-user budget for starting runs (protects the model backend and the queue)."""
    limiter: SlidingWindowLimiter = request.app.state.run_limiter
    limiter.hit(f"user:{principal.user_id}")


RunRateLimit = Annotated[None, Depends(limit_runs)]
