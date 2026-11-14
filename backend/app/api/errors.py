"""Map exceptions to RFC 7807-style problem JSON responses."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.services.errors import DomainError


def problem(status: int, title: str, detail: str, **extra: Any) -> JSONResponse:
    body = {"type": "about:blank", "title": title, "status": status, "detail": detail, **extra}
    return JSONResponse(
        jsonable_encoder(body), status_code=status, media_type="application/problem+json"
    )


async def _domain_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return problem(exc.status_code, exc.title, exc.detail)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [{k: e[k] for k in ("loc", "msg", "type") if k in e} for e in exc.errors()]
    return problem(422, "Validation error", "Request validation failed", errors=errors)


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return problem(exc.status_code, "HTTP error", str(exc.detail))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
