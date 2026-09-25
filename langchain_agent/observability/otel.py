"""
OpenTelemetry GenAI tracing, exported over OTLP (to Oodle in this repo's setup).

Opt-in: nothing is installed unless OTEL_EXPORTER_OTLP_ENDPOINT is set.
The exporter reads its endpoint, headers and compression from the standard
OTEL_EXPORTER_OTLP_* variables, which core.config's load_dotenv() pulls in
from .env.

LangchainInstrumentor hooks the LangChain callback system, so every graph
node and every ChatOllama call becomes a span carrying the
gen_ai.* attributes (model, token usage, prompt and response content).
Set TRACELOOP_TRACE_CONTENT=false to drop the prompt/response text.

Provides:
- setup_tracing(): install the tracer provider and instrumentor (idempotent)
- shutdown_tracing(): flush pending spans and shut the exporter down
"""

import logging
import os
from typing import Optional

from opentelemetry.sdk.trace import TracerProvider

logger = logging.getLogger(__name__)

DEFAULT_SERVICE_NAME = "agentic-hybrid-search"

_provider: Optional[TracerProvider] = None


def setup_tracing() -> Optional[TracerProvider]:
    """
    Install the OTLP tracer provider and the LangChain instrumentor.

    Must run before the agent builds its LLM clients. Safe to call more than
    once; later calls return the provider from the first.

    Returns:
        The tracer provider, or None when tracing is not configured.
    """
    global _provider
    if _provider is not None:
        return _provider
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return None

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.langchain import LangchainInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace import set_tracer_provider

    service_name = os.getenv("OTEL_SERVICE_NAME", DEFAULT_SERVICE_NAME)
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    set_tracer_provider(provider)
    LangchainInstrumentor().instrument()

    _provider = provider
    logger.info(
        "OTel tracing enabled: service=%s endpoint=%s",
        service_name,
        os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
    )
    return provider


def shutdown_tracing() -> None:
    """Flush pending spans and shut the exporter down. No-op if tracing is off."""
    global _provider
    if _provider is None:
        return
    try:
        _provider.shutdown()
    except Exception as e:
        logger.warning(f"OTel tracing shutdown failed: {e}")
    _provider = None
