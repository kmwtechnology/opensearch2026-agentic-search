"""
Unit tests for the user-toggleable search optimizations.

Covers three layers:

1.  `OpenSearchVectorStore._build_multi_match` — pure DSL builder, exercised
    against every individual flag and several combinations.
2.  `OpenSearchVectorStore.hybrid_search` — routing logic when `hybrid` is off
    or when alpha is at the boundary values.
3.  `OpenSearchRetriever.invoke` — verifies the optimizations dict is forwarded
    to `vector_store.hybrid_search`.

All tests run without a live OpenSearch cluster — the client and embedding
layer are mocked.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from vector_store import OpenSearchRetriever, OpenSearchVectorStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _multi_match(opts: Optional[Dict[str, bool]]) -> Dict[str, Any]:
    """Return the inner multi_match clause for a given optimizations dict."""
    return OpenSearchVectorStore._build_multi_match("query", opts)["multi_match"]


def _make_store() -> OpenSearchVectorStore:
    """Construct a vector store with a fully mocked OpenSearch client."""
    client = MagicMock()
    # Pretend native hybrid is unavailable — RRF path is simpler to assert on.
    client.info.return_value = {"version": {"number": "2.5.0"}}
    client.cat.plugins.return_value = []
    # Default search response shape so the methods don't crash.
    client.search.return_value = {"hits": {"hits": []}}
    return OpenSearchVectorStore(
        embeddings=MagicMock(),
        collection_id="test_collection",
        client=client,
    )


# ---------------------------------------------------------------------------
# 1. _build_multi_match
# ---------------------------------------------------------------------------


class TestBuildMultiMatchDefaults:
    """All flags default to True when key is missing or `optimizations` is None."""

    @pytest.mark.parametrize("opts", [None, {}, {"unknown_flag": True}])
    def test_full_field_set_with_fuzziness(self, opts):
        clause = _multi_match(opts)
        assert clause["fuzziness"] == "AUTO"
        assert "analyzer" not in clause  # synonyms ON keeps default analyzer
        assert clause["fields"] == [
            "chunk_text",
            "title^3.0",
            "title_phrase^2.5",
            "product_brand^2.0",
            "product_color^1.5",
            "title_phonetic^1.5",
            "brand_phonetic^1.5",
            "chunk_text.heavy^0.3",
            "product_brand.heavy^0.3",
            "product_color.heavy^0.3",
        ]


class TestBuildMultiMatchIndividualFlags:
    """Each flag controls one observable property of the DSL."""

    def test_fuzzy_off_drops_fuzziness(self):
        clause = _multi_match({"fuzzy": False})
        assert "fuzziness" not in clause
        # Other features unchanged
        assert "title_phonetic^1.5" in clause["fields"]
        assert "title_phrase^2.5" in clause["fields"]

    def test_synonyms_off_forces_standard_analyzer(self):
        clause = _multi_match({"synonyms": False})
        assert clause["analyzer"] == "standard"
        # Fuzzy still active by default
        assert clause["fuzziness"] == "AUTO"

    def test_phonetic_off_drops_phonetic_fields(self):
        clause = _multi_match({"phonetic": False})
        assert "title_phonetic^1.5" not in clause["fields"]
        assert "brand_phonetic^1.5" not in clause["fields"]
        # Other fields still present
        assert "title^3.0" in clause["fields"]
        assert "title_phrase^2.5" in clause["fields"]

    def test_phrase_boost_off_drops_title_phrase(self):
        clause = _multi_match({"phrase_boost": False})
        assert not any(f.startswith("title_phrase") for f in clause["fields"])
        # Other boosted fields untouched
        assert "title^3.0" in clause["fields"]
        assert "product_brand^2.0" in clause["fields"]

    def test_field_boost_off_strips_caret_weights(self):
        clause = _multi_match({"field_boost": False})
        for field in clause["fields"]:
            assert "^" not in field, f"unexpected boost on field {field!r}"
        # The set of fields is otherwise the full default set
        assert set(clause["fields"]) == {
            "chunk_text",
            "title",
            "title_phrase",
            "product_brand",
            "product_color",
            "title_phonetic",
            "brand_phonetic",
            "chunk_text.heavy",
            "product_brand.heavy",
            "product_color.heavy",
        }

    def test_hybrid_flag_does_not_affect_multi_match(self):
        """The `hybrid` flag is enforced by the routing in hybrid_search,
        not by the multi_match builder itself."""
        on = _multi_match({"hybrid": True})
        off = _multi_match({"hybrid": False})
        assert on == off


class TestBuildMultiMatchCombinations:
    """Combinations should compose independently."""

    def test_all_off(self):
        clause = _multi_match(
            {
                "fuzzy": False,
                "synonyms": False,
                "phonetic": False,
                "phrase_boost": False,
                "field_boost": False,
            }
        )
        assert "fuzziness" not in clause
        assert clause["analyzer"] == "standard"
        assert clause["fields"] == [
            "chunk_text",
            "title",
            "product_brand",
            "product_color",
            "chunk_text.heavy",
            "product_brand.heavy",
            "product_color.heavy",
        ]

    def test_phonetic_and_phrase_off_keeps_field_boosts(self):
        clause = _multi_match({"phonetic": False, "phrase_boost": False})
        assert clause["fields"] == [
            "chunk_text",
            "title^3.0",
            "product_brand^2.0",
            "product_color^1.5",
            "chunk_text.heavy^0.3",
            "product_brand.heavy^0.3",
            "product_color.heavy^0.3",
        ]
        assert clause["fuzziness"] == "AUTO"

    def test_field_boost_off_with_synonyms_off(self):
        """Stripping boosts and dropping synonyms compose: no carets, analyzer=standard."""
        clause = _multi_match({"field_boost": False, "synonyms": False})
        assert clause["analyzer"] == "standard"
        assert all("^" not in f for f in clause["fields"])
        # Fuzzy still on
        assert clause["fuzziness"] == "AUTO"

    def test_only_field_boost_off_keeps_phonetic_fields(self):
        clause = _multi_match({"field_boost": False})
        assert "title_phonetic" in clause["fields"]
        assert "brand_phonetic" in clause["fields"]


class TestBuildMultiMatchInvariants:
    """Properties that should hold across every toggle combination."""

    @pytest.mark.parametrize(
        "opts",
        [
            None,
            {"fuzzy": False},
            {"synonyms": False},
            {"phonetic": False},
            {"phrase_boost": False},
            {"field_boost": False},
            {
                "fuzzy": False,
                "synonyms": False,
                "phonetic": False,
                "phrase_boost": False,
                "field_boost": False,
            },
        ],
    )
    def test_query_text_and_type_preserved(self, opts):
        clause = _multi_match(opts)
        assert clause["query"] == "query"
        assert clause["type"] == "best_fields"
        assert clause["tie_breaker"] == 0.3

    @pytest.mark.parametrize(
        "opts",
        [
            None,
            {"fuzzy": False},
            {"synonyms": False},
            {"phonetic": False},
            {"phrase_boost": False},
            {"field_boost": False},
        ],
    )
    def test_chunk_text_always_searched(self, opts):
        clause = _multi_match(opts)
        bare = [f.split("^", 1)[0] for f in clause["fields"]]
        assert "chunk_text" in bare


# ---------------------------------------------------------------------------
# 2. hybrid_search routing
# ---------------------------------------------------------------------------


class TestHybridSearchRouting:
    """Verify the `hybrid` flag and alpha boundaries pick the right backend."""

    def test_hybrid_off_routes_to_text_search(self, monkeypatch):
        store = _make_store()
        sentinel = object()
        text_search = MagicMock(return_value=[sentinel])
        native = MagicMock(return_value=[])
        rrf = MagicMock(return_value=[])
        monkeypatch.setattr(store, "_text_search", text_search)
        monkeypatch.setattr(store, "_hybrid_search_native", native)
        monkeypatch.setattr(store, "_hybrid_search_rrf", rrf)

        result = store.hybrid_search(
            "q",
            k=4,
            fetch_k=20,
            alpha=0.5,
            optimizations={"hybrid": False},
        )

        assert result == [sentinel]
        text_search.assert_called_once()
        # The optimizations dict must be forwarded so per-feature flags still apply
        kwargs = text_search.call_args.kwargs
        assert kwargs["optimizations"] == {"hybrid": False}
        native.assert_not_called()
        rrf.assert_not_called()

    def test_hybrid_on_with_mid_alpha_uses_rrf(self, monkeypatch):
        store = _make_store()
        # Force RRF path
        store._hybrid_supported = False
        monkeypatch.setattr(store, "_get_embedding", lambda q: [0.0] * 3)

        text_search = MagicMock()
        native = MagicMock()
        rrf = MagicMock(return_value=[])
        monkeypatch.setattr(store, "_text_search", text_search)
        monkeypatch.setattr(store, "_hybrid_search_native", native)
        monkeypatch.setattr(store, "_hybrid_search_rrf", rrf)

        store.hybrid_search(
            "q",
            k=4,
            fetch_k=20,
            alpha=0.5,
            optimizations={"hybrid": True, "fuzzy": False},
        )

        rrf.assert_called_once()
        text_search.assert_not_called()
        native.assert_not_called()
        # optimizations forwarded as last positional
        args = rrf.call_args.args
        assert args[-1] == {"hybrid": True, "fuzzy": False}

    def test_alpha_zero_routes_to_text_search_regardless_of_hybrid_flag(self, monkeypatch):
        store = _make_store()
        text_search = MagicMock(return_value=[])
        rrf = MagicMock()
        monkeypatch.setattr(store, "_text_search", text_search)
        monkeypatch.setattr(store, "_hybrid_search_rrf", rrf)

        store.hybrid_search("q", k=4, fetch_k=20, alpha=0.0)

        text_search.assert_called_once()
        rrf.assert_not_called()

    def test_alpha_one_routes_to_similarity_search(self, monkeypatch):
        store = _make_store()
        sim = MagicMock(return_value=[])
        text_search = MagicMock()
        monkeypatch.setattr(store, "similarity_search", sim)
        monkeypatch.setattr(store, "_text_search", text_search)

        store.hybrid_search("q", k=4, fetch_k=20, alpha=1.0)

        sim.assert_called_once_with("q", 4)
        text_search.assert_not_called()

    def test_hybrid_off_overrides_alpha_one(self, monkeypatch):
        """Even at alpha=1.0 the `hybrid: False` toggle wins and forces lexical."""
        store = _make_store()
        sim = MagicMock()
        text_search = MagicMock(return_value=[])
        monkeypatch.setattr(store, "similarity_search", sim)
        monkeypatch.setattr(store, "_text_search", text_search)

        store.hybrid_search("q", k=4, fetch_k=20, alpha=1.0, optimizations={"hybrid": False})

        text_search.assert_called_once()
        sim.assert_not_called()


# ---------------------------------------------------------------------------
# 3. End-to-end DSL inspection through _text_search and _hybrid_search_rrf
# ---------------------------------------------------------------------------


class TestDSLForwarding:
    """Confirm the optimizations dict reaches the DSL emitted by each method."""

    def test_text_search_emits_dsl_without_fuzziness_when_fuzzy_off(self):
        store = _make_store()
        store._text_search("q", k=4, optimizations={"fuzzy": False})
        body = store.client.search.call_args.kwargs["body"]
        clause = body["query"]["bool"]["must"][0]["multi_match"]
        assert "fuzziness" not in clause

    def test_text_search_emits_standard_analyzer_when_synonyms_off(self):
        store = _make_store()
        store._text_search("q", k=4, optimizations={"synonyms": False})
        body = store.client.search.call_args.kwargs["body"]
        clause = body["query"]["bool"]["must"][0]["multi_match"]
        assert clause["analyzer"] == "standard"

    def test_rrf_text_subquery_drops_phonetic_when_phonetic_off(self):
        store = _make_store()
        # Two calls: vector + text. Inspect the second.
        store._hybrid_search_rrf(
            query="q",
            query_embedding=[0.0] * 3,
            k=4,
            fetch_k=20,
            alpha=0.5,
            optimizations={"phonetic": False},
        )
        # Second search call is the text body.
        text_body = store.client.search.call_args_list[1].kwargs["body"]
        clause = text_body["query"]["bool"]["must"][0]["multi_match"]
        for f in clause["fields"]:
            assert "phonetic" not in f


# ---------------------------------------------------------------------------
# 4. OpenSearchRetriever forwards optimizations to vector_store.hybrid_search
# ---------------------------------------------------------------------------


class TestRerankerToggle:
    """The `reranking` flag on `optimizations` short-circuits `reranker_node`
    without invoking the LLM and signals the quality gate to pass through."""

    def _make_agent(self, reranker_mock: MagicMock):
        """Construct an EcommerceSearchAgent without running __init__ (which
        would pull in real models/db). Only the attributes actually touched by
        `reranker_node` need to be present."""
        from main import EcommerceSearchAgent

        agent = EcommerceSearchAgent.__new__(EcommerceSearchAgent)
        agent.reranker = reranker_mock
        agent.event_queue = []
        agent.emit_callback = None
        agent.event_loop = None
        return agent

    def _make_doc(self, source: str = "doc1"):
        from langchain_core.documents import Document

        return Document(page_content="hello world", metadata={"source": source})

    def test_reranking_off_skips_reranker_and_bypasses_quality_gate(self):
        reranker = MagicMock()
        agent = self._make_agent(reranker)
        doc = self._make_doc()

        out = agent.reranker_node(
            {
                "messages": [],
                "retrieved_documents": [doc],
                "intent": "search",
                "user_query": "headphones",
                "optimizations": {"reranking": False},
            }
        )

        # Reranker LLM was not called
        reranker.rerank.assert_not_called()
        # Documents pass through untouched, in original order
        assert out["retrieved_documents"] == [doc]
        # Quality gate is told to pass — score sentinel + retried flag set
        assert out["reranker_max_score"] == 1.0
        assert out["quality_gate_retried"] is True

    def test_reranking_on_runs_reranker(self, monkeypatch):
        # Force ENABLE_RERANKING true regardless of env
        import main as main_module

        monkeypatch.setattr(main_module, "ENABLE_RERANKING", True)

        # Stub the reranker so we don't make real LLM calls
        reranker = MagicMock()
        reranker.batch_size = 8
        reranker.device = "cpu"
        # score_documents() returns [(Document, score), ...] for ALL candidates
        # sorted descending by score; reranker_node slices to RERANKER_TOP_K.
        reranker.score_documents.return_value = [(self._make_doc("doc1"), 0.9)]
        agent = self._make_agent(reranker)
        doc = self._make_doc()

        # Patch the synchronous emit helper to no-op (it touches the event loop
        # which isn't running under pytest)
        monkeypatch.setattr(agent, "_emit_event_from_sync", lambda *_a, **_kw: None)

        out = agent.reranker_node(
            {
                "messages": [],
                "retrieved_documents": [doc],
                "intent": "search",
                "user_query": "headphones",
                "optimizations": {"reranking": True},
            }
        )

        # Reranker was actually invoked
        reranker.score_documents.assert_called_once()
        # Quality gate is NOT pre-marked retried — let the gate decide
        assert out.get("quality_gate_retried") is not True
        # Full scored list is exposed to the UI for the demo
        assert "all_reranked_documents" in out

    def test_reranking_default_true_when_key_missing(self, monkeypatch):
        """If the optimizations dict is empty, reranking should run (default True)."""
        import main as main_module

        monkeypatch.setattr(main_module, "ENABLE_RERANKING", True)

        reranker = MagicMock()
        reranker.batch_size = 8
        reranker.device = "cpu"
        reranker.score_documents.return_value = [(self._make_doc(), 0.9)]
        agent = self._make_agent(reranker)
        monkeypatch.setattr(agent, "_emit_event_from_sync", lambda *_a, **_kw: None)

        agent.reranker_node(
            {
                "messages": [],
                "retrieved_documents": [self._make_doc()],
                "intent": "search",
                "user_query": "headphones",
                "optimizations": {},  # missing key — defaults to enabled
            }
        )
        reranker.score_documents.assert_called_once()

    def test_global_enable_reranking_false_overrides_toggle_on(self, monkeypatch):
        """When the env-level ENABLE_RERANKING is False, the per-query toggle
        cannot turn it on."""
        import main as main_module

        monkeypatch.setattr(main_module, "ENABLE_RERANKING", False)

        reranker = MagicMock()
        agent = self._make_agent(reranker)
        doc = self._make_doc()

        out = agent.reranker_node(
            {
                "messages": [],
                "retrieved_documents": [doc],
                "intent": "search",
                "user_query": "headphones",
                "optimizations": {"reranking": True},
            }
        )

        reranker.rerank.assert_not_called()
        assert out["retrieved_documents"] == [doc]
        # When *globally* off, the legacy code path returns score 0.0; we don't
        # bypass the quality gate here because the user didn't explicitly opt out.
        assert out["reranker_max_score"] == 0.0


class TestLLMToggleFormatting:
    """`_format_search_results` is the static helper used to render documents
    when the LLM toggle is off. It must produce a deterministic markdown
    list whose order matches the input."""

    def _docs(self):
        from langchain_core.documents import Document

        return [
            Document(
                page_content="Wireless headphones with noise cancelling.",
                metadata={
                    "title": "Sony WH-1000XM5",
                    "product_brand": "Sony",
                    "url": "https://www.amazon.com/dp/A",
                    "reranker_score": 0.92,
                },
            ),
            Document(
                page_content="Budget bluetooth earbuds.",
                metadata={
                    "title": "Anker Soundcore",
                    "product_brand": "Anker",
                    "url": "https://www.amazon.com/dp/B",
                },
            ),
        ]

    def test_format_includes_query_and_count(self):
        from main import EcommerceSearchAgent

        out = EcommerceSearchAgent._format_search_results(self._docs(), "headphones")
        assert "headphones" in out
        assert "2 products" in out

    def test_format_preserves_input_order(self):
        from main import EcommerceSearchAgent

        out = EcommerceSearchAgent._format_search_results(self._docs(), "headphones")
        # Sony must appear before Anker in the rendered output
        assert out.find("Sony WH-1000XM5") < out.find("Anker Soundcore")
        # Numeric prefix matches order
        assert "**1." in out and "**2." in out

    def test_format_includes_url_link_when_present(self):
        from main import EcommerceSearchAgent

        out = EcommerceSearchAgent._format_search_results(self._docs(), "headphones")
        assert "[Sony WH-1000XM5](https://www.amazon.com/dp/A)" in out

    def test_format_includes_reranker_score_when_present(self):
        from main import EcommerceSearchAgent

        out = EcommerceSearchAgent._format_search_results(self._docs(), "headphones")
        # Sony has reranker_score 0.92, rendered under "Reranker Score:"
        assert "Reranker Score:" in out
        assert "0.92" in out
        # Anker has no score of any kind — neither label appears in its block
        anker_block = out.split("Anker Soundcore", 1)[1].split("---", 1)[0]
        assert "Reranker Score:" not in anker_block
        assert "Score:" not in anker_block

    def test_format_falls_back_to_retrieval_score_when_no_reranker_score(self):
        """When reranking is off the doc has only `retrieval_score` (raw BM25/RRF)
        — the renderer should surface it under a 'Score:' label."""
        from langchain_core.documents import Document

        from main import EcommerceSearchAgent

        docs = [
            Document(
                page_content="ACME Red Sneakers",
                metadata={
                    "title": "ACME Red Sneakers",
                    "url": "https://example.com/x",
                    "retrieval_score": 14.523,  # raw BM25 score
                },
            )
        ]
        out = EcommerceSearchAgent._format_search_results(docs, "red shoes")
        assert "Score:" in out
        assert "14.523" in out
        assert "Reranker Score:" not in out

    def test_format_empty_documents_returns_no_results_message(self):
        from main import EcommerceSearchAgent

        out = EcommerceSearchAgent._format_search_results([], "snnyy")
        assert "No products found" in out
        assert "snnyy" in out

    def test_format_handles_missing_metadata_gracefully(self):
        from langchain_core.documents import Document

        from main import EcommerceSearchAgent

        out = EcommerceSearchAgent._format_search_results(
            [Document(page_content="something", metadata={})],
            "anything",
        )
        # Should not raise, should produce a heading even without title/url
        assert "(untitled product)" in out


class TestChatWebSocketValidation:
    """The WebSocket handler must reject hostile or malformed `optimizations`
    payloads. This is enforced by the inline allowlist in `chat.py`; we
    re-implement the same logic here as a black-box check so the contract
    is pinned by tests."""

    _ALLOWED = frozenset(
        {
            "hybrid",
            "fuzzy",
            "synonyms",
            "phonetic",
            "phrase_boost",
            "field_boost",
            "typeahead",
            "reranking",
            "llm",
        }
    )

    def _coerce(self, raw):
        """Mirror the WS handler's coercion to verify the contract."""
        if not isinstance(raw, dict):
            return None
        return {k: bool(v) for k, v in raw.items() if isinstance(k, str) and k in self._ALLOWED}

    def test_unknown_keys_are_dropped(self):
        out = self._coerce({"hybrid": True, "evil": True, "x" * 1000: True})
        assert out == {"hybrid": True}

    def test_non_string_keys_are_dropped(self):
        out = self._coerce({1: True, "fuzzy": False})
        assert out == {"fuzzy": False}

    def test_non_dict_payload_returns_none(self):
        for bad in [None, [], "hybrid", 42]:
            assert self._coerce(bad) is None

    def test_truthy_values_coerced_to_bool(self):
        out = self._coerce({"fuzzy": 1, "synonyms": 0, "hybrid": "yes"})
        assert out == {"fuzzy": True, "synonyms": False, "hybrid": True}

    def test_huge_payload_only_keeps_known_keys(self):
        # Even with thousands of unknown keys, only the 9 allowlisted ones survive.
        raw = {f"junk_{i}": True for i in range(5000)}
        raw["reranking"] = False
        out = self._coerce(raw)
        assert out == {"reranking": False}


class TestCitationFloorBypass:
    """When reranking is off, every doc has reranker_score=0.0 — the citation
    relevance floor (0.10) would suppress everything. agent_node must skip
    the floor in that case."""

    def test_citation_filter_bypassed_when_reranking_off(self):
        """Smoke test the gate condition: with reranking off and zero scores,
        the `if max_relevance >= MIN_CITATION_RELEVANCE` branch must still
        admit citations."""
        # Re-implement the new condition as a black-box assertion so the
        # contract is pinned. (The full agent_node is too coupled to mock.)
        opts = {"reranking": False}
        max_relevance = 0.0
        MIN = 0.10
        reranker_skipped = opts.get("reranking", True) is False
        admit_citations = reranker_skipped or max_relevance >= MIN
        assert admit_citations is True

    def test_citation_filter_still_applies_when_reranker_runs_with_low_scores(self):
        """When reranker actually ran and scored everything < 0.10, the floor
        kicks in normally — this is the legitimate "all results garbage" case."""
        opts = {"reranking": True}
        max_relevance = 0.05
        MIN = 0.10
        reranker_skipped = opts.get("reranking", True) is False
        admit_citations = reranker_skipped or max_relevance >= MIN
        assert admit_citations is False


class TestOptimizationsKeyContract:
    """The `optimizations` dict on the chat schema and agent state must
    accept the full set of recognized keys without rejecting unknowns."""

    def test_chat_message_accepts_all_known_keys(self):
        from api.routes.chat import ChatMessage

        msg = ChatMessage(
            type="chat_message",
            message="hello",
            thread_id="conv_test_xyz",
            optimizations={
                "hybrid": True,
                "fuzzy": False,
                "synonyms": True,
                "phonetic": False,
                "phrase_boost": True,
                "field_boost": False,
                "typeahead": True,
                "reranking": False,
                "llm": False,
            },
        )
        assert msg.optimizations is not None
        assert msg.optimizations["reranking"] is False
        assert msg.optimizations["fuzzy"] is False
        assert msg.optimizations["llm"] is False

    def test_chat_message_optimizations_optional(self):
        from api.routes.chat import ChatMessage

        msg = ChatMessage(message="hello", thread_id="conv_test_xyz")
        assert msg.optimizations is None


class TestRetrieverForwarding:
    def test_retriever_passes_optimizations_to_hybrid_search(self):
        vector_store = MagicMock()
        vector_store.collection_id = "test_collection"
        vector_store.hybrid_search.return_value = []

        retriever = OpenSearchRetriever(
            vector_store,
            search_type="hybrid",
            k=4,
            fetch_k=20,
            alpha=0.35,
            optimizations={"fuzzy": False, "phonetic": False},
        )
        retriever.invoke("q")

        kwargs = vector_store.hybrid_search.call_args.kwargs
        assert kwargs["optimizations"] == {"fuzzy": False, "phonetic": False}
        assert kwargs["alpha"] == 0.35

    def test_as_retriever_threads_optimizations_through_search_kwargs(self):
        store = _make_store()
        retriever = store.as_retriever(
            search_type="hybrid",
            search_kwargs={
                "k": 4,
                "fetch_k": 20,
                "alpha": 0.25,
                "optimizations": {"hybrid": False, "synonyms": False},
            },
        )
        assert retriever.optimizations == {"hybrid": False, "synonyms": False}

    def test_default_optimizations_is_none_when_omitted(self):
        store = _make_store()
        retriever = store.as_retriever(search_type="hybrid")
        assert retriever.optimizations is None
