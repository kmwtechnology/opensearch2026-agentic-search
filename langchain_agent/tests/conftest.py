"""Shared pytest fixtures."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add langchain_agent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("ENABLE_QUALITY_GATE", "true")
os.environ.setdefault("QUALITY_GATE_THRESHOLD", "0.50")


@pytest.fixture
def bare_agent():
    """An EcommerceSearchAgent with every I/O attribute stubbed to None/mocks.

    Built via ``__new__`` (bypasses ``__init__``, so no real DB/OpenSearch/LLM
    connections happen). Sets the full attribute baseline any pipeline-node or
    helper-method unit test might touch; override individual attributes on the
    returned object (``agent.alpha_estimator_llm = MagicMock(...)``) for what a
    specific test actually exercises.
    """
    from main import EcommerceSearchAgent

    agent = EcommerceSearchAgent.__new__(EcommerceSearchAgent)
    agent.llm = None
    agent.embeddings = None
    agent.vector_store = None
    agent.pool = None
    agent.async_pool = None
    agent.checkpointer = None
    agent.app = None
    agent.thread_id = None
    agent.emit_callback = None
    agent.event_loop = None
    agent.event_queue = []
    agent.retriever = None
    agent.reranker = None
    agent.alpha_estimator_llm = None
    agent.judge = None
    agent.intent_structured = None
    return agent
