"""Regression: category extraction must accept short multi-word category
names ("running shoes", "trail running shoes"), not just single words.

Before this fix, both _extract_product_category_from_documents and
_extract_product_category_from_query rejected any LLM response containing
a space, silently discarding legitimate two/three-word category names to
"". That forced _validate_category_continuity's score to the ambiguous
default (0.5) for entire product lines (anything the LLM naturally
describes as "running shoes" rather than "shoes"), capping intent
confidence at 0.65 and locking alpha to the refinement fast-path (0.35)
even when the turn should have been reclassified as a fresh search with
an LLM-estimated alpha. Live-observed on DEMO.md's Arc 1 turn 3
("what about trail running?") after #126's PR fixed the dead
self.query_eval_llm attribute that had been masking this all along.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from main import EcommerceSearchAgent


class _Resp:
    def __init__(self, content: Any) -> None:
        self.content = content


def _agent_returning(category_text: str) -> EcommerceSearchAgent:
    agent = EcommerceSearchAgent.__new__(EcommerceSearchAgent)
    agent.alpha_estimator_llm = MagicMock()
    agent.alpha_estimator_llm.invoke.return_value = _Resp(category_text)
    return agent


@pytest.mark.unit
@pytest.mark.phase1
class TestExtractProductCategoryFromDocuments:
    def test_single_word_category_accepted(self) -> None:
        agent = _agent_returning("boots")
        docs = [Document(page_content="", metadata={"title": "Sperry Cold Bay Boot"})]
        assert agent._extract_product_category_from_documents(docs) == "boots"

    def test_two_word_category_accepted(self) -> None:
        agent = _agent_returning("running shoes")
        docs = [Document(page_content="", metadata={"title": "Nike Air Zoom Pegasus 36"})]
        assert agent._extract_product_category_from_documents(docs) == "running shoes"

    def test_three_word_category_accepted(self) -> None:
        agent = _agent_returning("trail running shoes")
        docs = [Document(page_content="", metadata={"title": "adidas Supernova Trail Shoe"})]
        assert agent._extract_product_category_from_documents(docs) == "trail running shoes"

    def test_long_explanation_still_rejected(self) -> None:
        agent = _agent_returning("these are all running shoes for men and women in various colors")
        docs = [Document(page_content="", metadata={"title": "Nike Air Zoom Pegasus 36"})]
        assert agent._extract_product_category_from_documents(docs) == ""

    def test_empty_response_returns_empty(self) -> None:
        agent = _agent_returning("")
        docs = [Document(page_content="", metadata={"title": "Nike Air Zoom Pegasus 36"})]
        assert agent._extract_product_category_from_documents(docs) == ""

    def test_no_documents_returns_empty_without_calling_llm(self) -> None:
        agent = _agent_returning("boots")
        assert agent._extract_product_category_from_documents([]) == ""
        agent.alpha_estimator_llm.invoke.assert_not_called()


@pytest.mark.unit
@pytest.mark.phase1
class TestExtractProductCategoryFromQuery:
    def test_keyword_pattern_short_circuits_llm(self) -> None:
        agent = _agent_returning("should not be used")
        assert agent._extract_product_category_from_query("show me blue boots") == "boots"
        agent.alpha_estimator_llm.invoke.assert_not_called()

    def test_two_word_llm_category_accepted(self) -> None:
        # "what about trail running?" has no literal keyword-pattern match
        # (no "shoe"/"boot"/etc. substring), so it falls to the LLM fallback.
        agent = _agent_returning("running shoes")
        assert agent._extract_product_category_from_query("what about trail running?") == (
            "running shoes"
        )

    def test_long_explanation_still_rejected(self) -> None:
        agent = _agent_returning("this query does not mention a specific product category")
        assert agent._extract_product_category_from_query("what about trail running?") == ""
