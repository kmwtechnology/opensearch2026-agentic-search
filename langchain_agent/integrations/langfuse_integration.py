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


def get_callbacks() -> list:
    """LangChain callbacks to attach to a graph invocation: [CallbackHandler] or []."""
    if not LANGFUSE_ENABLED:
        return []
    handler_cls = _resolve_handler_cls()
    if handler_cls is None:
        return []
    try:
        return [handler_cls(public_key=LANGFUSE_PUBLIC_KEY)]
    except Exception:
        logger.warning(
            "Langfuse CallbackHandler creation failed; continuing without tracing", exc_info=True
        )
        return []


def shutdown_tracing() -> None:
    """Flush pending spans. Call once at process exit (CLI) or app shutdown (API)."""
    if _handler_cls is None:
        return
    try:
        from langfuse import get_client

        get_client(public_key=LANGFUSE_PUBLIC_KEY).shutdown()
    except Exception:
        logger.warning("Langfuse shutdown/flush failed", exc_info=True)
