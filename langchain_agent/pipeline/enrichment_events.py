"""
Emit bridge for taxonomy-enrichment lifecycle events (#103).

Why this exists
---------------
The enrichment lifecycle is the only part of the pipeline whose interesting
moments happen *inside* a single node rather than between nodes. A taxonomy
correction runs a real Lucille re-index that takes ~20s, and the observability
layer's normal mechanism — reading a node's completed output state in
``observable_agent`` — can only ever describe that after it is over. That is
why the re-index window used to be entirely silent in the UI.

So ``_try_enrichment_tool`` publishes its own lifecycle events as they happen,
through this module. It is deliberately tiny and deliberately optional:

* ``agent_node`` runs in a worker thread (see ``aagent_node``), so the
  publisher must be callable from a non-loop thread. ``observable_agent``
  installs one that hops back onto the event loop with
  ``run_coroutine_threadsafe``.
* Nothing else installs a publisher. Under ``cli.py``, the unit tests, or
  ``/api/admin/enrich`` there is no subscriber and ``publish`` is a no-op —
  the enrichment itself must never fail because nobody was listening.

A ContextVar (not a module global) keeps concurrent WebSocket turns from
emitting into each other's sockets; ``asyncio.to_thread`` copies the context
into the worker, so the correct publisher is visible from inside the node.
"""

import contextvars
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Set by observable_agent for the duration of one streamed turn. None means
# "no observer attached" — the overwhelmingly common case outside the API.
_publisher: contextvars.ContextVar[Optional[Callable[..., Any]]] = contextvars.ContextVar(
    "enrichment_event_publisher", default=None
)


def set_publisher(publisher: Optional[Callable[..., Any]]) -> contextvars.Token:
    """Install the publisher for this turn. Returns a token for reset()."""
    return _publisher.set(publisher)


def reset_publisher(token: contextvars.Token) -> None:
    """Restore whatever publisher was installed before set_publisher()."""
    _publisher.reset(token)


def publish(**fields: Any) -> None:
    """
    Publish one enrichment lifecycle event.

    Called from inside the agent node, usually on a worker thread. Never
    raises: a broken or absent observer must not take down a real taxonomy
    write that has already happened.
    """
    publisher = _publisher.get()
    if publisher is None:
        return
    try:
        publisher(**fields)
    except Exception:  # pragma: no cover - defensive, observability only
        logger.warning("Enrichment event publish failed (continuing)", exc_info=True)
