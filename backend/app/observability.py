"""Structured logging and OpenTelemetry tracing.

- Logs: `LOG_FORMAT=json` emits one JSON object per line (timestamp, level, logger, message,
  run_id when inside a run, exception). `text` (default) keeps the human format.
- Traces: off unless `OTEL_ENABLED=true`. Spans are exported over OTLP/HTTP when
  `OTEL_EXPORTER_OTLP_ENDPOINT` is set, otherwise to the console. Code always uses the
  OpenTelemetry API, which is a no-op until a provider is installed.
"""

import contextvars
import json
import logging
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

current_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_run_id", default=None
)

tracer = trace.get_tracer("easy-access-agents")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if run_id := current_run_id.get():
            data["run_id"] = run_id
        span = trace.get_current_span().get_span_context()
        if span.is_valid:
            data["trace_id"] = format(span.trace_id, "032x")
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def configure_logging(log_format: str = "text", level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())


_configured = False


def configure_tracing(enabled: bool, endpoint: str = "", service_name: str = "eaa") -> None:
    """Install a tracer provider once per process (idempotent)."""
    global _configured
    if not enabled or _configured:
        return
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SpanExporter,
    )

    exporter: SpanExporter
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")
    else:
        exporter = ConsoleSpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _configured = True
