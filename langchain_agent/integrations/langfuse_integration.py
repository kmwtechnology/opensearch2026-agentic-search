"""Langfuse tracing for the LangGraph pipeline — local development only.

Gated by LANGFUSE_ENABLED (default off) and never deployed to GCP: the SDK lives
only in requirements-dev.txt and every langfuse import below is lazy, so a
production image without the package can never fail at import time.
"""

import logging
from typing import Any, Optional

from config import LANGFUSE_BASE_URL, LANGFUSE_ENABLED, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

logger = logging.getLogger(__name__)

# Import + client init happen once per process; the outcome (handler class or
# None) is cached so a misconfiguration logs a single warning, not one per request.
_resolved = False
_handler_cls: Optional[Any] = None


def _resolve_handler_cls() -> Optional[Any]:
    global _resolved, _handler_cls
    if _resolved:
        return _handler_cls
    _resolved = True

    if not (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY):
        logger.warning(
            "LANGFUSE_ENABLED=true but LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY are unset; "
            "tracing disabled"
        )
        return None

    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler

        # Registers the process-wide client that CallbackHandler instances look up by public key.
        Langfuse(
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
            base_url=LANGFUSE_BASE_URL,
        )
    except ImportError as e:
        logger.warning(
            "LANGFUSE_ENABLED=true but the Langfuse SDK is unavailable (%s); "
            "run `pip install -r requirements-dev.txt`. Tracing disabled",
            e,
        )
        return None
    except Exception:
        logger.warning("Langfuse client init failed; tracing disabled", exc_info=True)
        return None

    _handler_cls = CallbackHandler
    logger.info("Langfuse tracing enabled -> %s", LANGFUSE_BASE_URL)
    return _handler_cls


def new_trace_id(seed: Optional[str] = None) -> Optional[str]:
    """A trace id to pass to both get_callbacks() and record_metrics() for one invocation.

    Generating this ourselves (rather than letting the handler pick one implicitly) is
    what lets pipeline nodes attach metrics to the right trace without needing an active
    OTel span context, which LangGraph's astream_events dispatch does not reliably provide
    inside plain node functions. Returns None when tracing is off/unavailable.
    """
    if not LANGFUSE_ENABLED or _resolve_handler_cls() is None:
        return None
    try:
        from langfuse import Langfuse

        return Langfuse.create_trace_id(seed=seed)
    except Exception:
        logger.warning("Langfuse create_trace_id failed", exc_info=True)
        return None


def get_callbacks(trace_id: Optional[str] = None) -> list:
    """LangChain callbacks to attach to a graph invocation: [CallbackHandler] or [].

    Pass the same trace_id returned by new_trace_id() so the handler's root span uses it.
    """
    if not LANGFUSE_ENABLED:
        return []
    handler_cls = _resolve_handler_cls()
    if handler_cls is None:
        return []
    try:
        trace_context = {"trace_id": trace_id} if trace_id else None
        return [handler_cls(public_key=LANGFUSE_PUBLIC_KEY, trace_context=trace_context)]
    except Exception:
        logger.warning(
            "Langfuse CallbackHandler creation failed; continuing without tracing", exc_info=True
        )
        return []


def record_metrics(trace_id: Optional[str], **metrics: Any) -> None:
    """Record metrics (e.g. per-node latency, LLM-judge scores/verdicts) as Langfuse
    scores on a trace. Numeric values (int/float) score as NUMERIC; strings (e.g. a
    pairwise verdict or hallucination category) score as CATEGORICAL.

    Safe to call unconditionally from pipeline nodes: no-op when tracing is disabled,
    unresolved, or trace_id is None (e.g. this node ran outside a traced invocation).
    Uses explicit trace_id + create_score() rather than "current span" mutation: LangGraph's
    astream_events dispatch does not reliably leave an OTel span active inside a plain node
    function's own call stack, so ambient-context APIs (update_current_span) silently no-op
    there even though they work fine for a directly-invoked chain.
    """
    if not LANGFUSE_ENABLED or trace_id is None or _handler_cls is None:
        return
    try:
        from langfuse import get_client

        client = get_client(public_key=LANGFUSE_PUBLIC_KEY)
        for name, value in metrics.items():
            if isinstance(value, str):
                client.create_score(
                    trace_id=trace_id, name=name, value=value, data_type="CATEGORICAL"
                )
            else:
                client.create_score(trace_id=trace_id, name=name, value=value, data_type="NUMERIC")
    except Exception:
        logger.debug("Langfuse record_metrics failed; continuing", exc_info=True)


def shutdown_tracing() -> None:
    """Flush pending spans. Call once at process exit (CLI) or app shutdown (API)."""
    if _handler_cls is None:
        return
    try:
        from langfuse import get_client

        get_client(public_key=LANGFUSE_PUBLIC_KEY).shutdown()
    except Exception:
        logger.warning("Langfuse shutdown/flush failed", exc_info=True)
