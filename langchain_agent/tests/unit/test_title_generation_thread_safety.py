"""Tests for the shared-agent thread_id race fixed in issue #23.

`ObservableAgentService` wraps a single, shared `EcommerceSearchAgent`
instance. Background title generation previously called
`update_conversation_title()` with no argument, relying on the shared
agent's `self.thread_id` -- which a concurrent request can reassign before
the background task runs. These tests pin the fix: `update_conversation_title`
must use an explicitly passed `thread_id` rather than the instance attribute,
and `ObservableAgentService` must serialize the per-request critical section
that mutates the shared agent's state.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def test_update_conversation_title_uses_passed_thread_id_not_self(bare_agent):
    """Passing thread_id must override self.thread_id, not merely default to it.

    Regression test for the race: a background title-generation task can run
    after a concurrent request has already reassigned the shared agent's
    self.thread_id to a different conversation.
    """
    agent = bare_agent
    agent.thread_id = "stale-thread-from-another-request"
    agent.checkpointer = MagicMock()
    agent.checkpointer.get.return_value = {
        "channel_values": {"messages": [SimpleNamespace(type="human", content="hi")]}
    }
    agent.generate_conversation_title = MagicMock(return_value="A Title")

    with patch("conversation_management.psycopg.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        agent.update_conversation_title(thread_id="the-actual-request-thread")

    # The checkpoint lookup and the DB write must both use the passed thread_id.
    agent.checkpointer.get.assert_called_once_with(
        {"configurable": {"thread_id": "the-actual-request-thread"}}
    )
    write_args = mock_cursor.execute.call_args[0][1]
    assert write_args[0] == "the-actual-request-thread"


def test_update_conversation_title_defaults_to_self_thread_id(bare_agent):
    """CLI path (main.py) calls update_conversation_title() with no args."""
    agent = bare_agent
    agent.thread_id = "cli-thread"
    agent.checkpointer = MagicMock()
    agent.checkpointer.get.return_value = None  # no checkpoint -> early return

    agent.update_conversation_title()

    agent.checkpointer.get.assert_called_once_with({"configurable": {"thread_id": "cli-thread"}})


def test_observable_agent_service_serializes_shared_agent_access():
    """ObservableAgentService must hold a request lock guarding shared agent state.

    Two concurrent process_message() calls against the single shared
    EcommerceSearchAgent must not interleave their emit_callback/thread_id
    mutations (see #23) -- verified here by asserting the lock exists and
    that acquiring it from two coroutines serializes as expected.
    """
    from api.services.observable_agent import ObservableAgentService

    service = ObservableAgentService()
    assert isinstance(service._request_lock, asyncio.Lock)

    order = []

    async def hold_lock(name, hold_s):
        async with service._request_lock:
            order.append(f"{name}-start")
            await asyncio.sleep(hold_s)
            order.append(f"{name}-end")

    async def run():
        await asyncio.gather(hold_lock("A", 0.05), hold_lock("B", 0.0))

    asyncio.run(run())

    # B must not start until A has fully released the lock.
    assert order == ["A-start", "A-end", "B-start", "B-end"]
