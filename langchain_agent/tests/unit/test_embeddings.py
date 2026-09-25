"""Unit tests for retrieval/embeddings.py -- the exact text sent to Ollama (#148).

nomic-embed-text is asymmetric, so the prefix on each request is the whole
point. A fake client records what would have gone over the wire; no Ollama
server is needed.
"""

import asyncio

import pytest

from retrieval.embeddings import DOCUMENT_PREFIX, QUERY_PREFIX, PrefixedOllamaEmbeddings


class _FakeClient:
    def __init__(self):
        self.inputs = []

    def embed(self, model, texts, **kwargs):
        self.inputs.append(list(texts))
        return {"embeddings": [[0.0] * 768 for _ in texts]}


class _FakeAsyncClient(_FakeClient):
    async def embed(self, model, texts, **kwargs):  # type: ignore[override]
        return _FakeClient.embed(self, model, texts, **kwargs)


@pytest.fixture
def emb():
    e = PrefixedOllamaEmbeddings(model="nomic-embed-text")
    e._client = _FakeClient()
    e._async_client = _FakeAsyncClient()
    return e


def test_query_gets_query_prefix_only(emb):
    emb.embed_query("waterproof boots")
    # Regression: OllamaEmbeddings.embed_query delegates to self.embed_documents,
    # which would stack the document prefix on top of the query prefix.
    assert emb._client.inputs == [[QUERY_PREFIX + "waterproof boots"]]


def test_documents_get_document_prefix(emb):
    emb.embed_documents(["tan boots", "sewing machine"])
    assert emb._client.inputs == [
        [DOCUMENT_PREFIX + "tan boots", DOCUMENT_PREFIX + "sewing machine"]
    ]


def test_async_query_gets_query_prefix_only(emb):
    asyncio.run(emb.aembed_query("running shoes"))
    assert emb._async_client.inputs == [[QUERY_PREFIX + "running shoes"]]


def test_async_documents_get_document_prefix(emb):
    asyncio.run(emb.aembed_documents(["boots"]))
    assert emb._async_client.inputs == [[DOCUMENT_PREFIX + "boots"]]


def test_document_prefix_matches_lucille_ingest():
    """The ingest-side prefix (Lucille conf) and the query side must agree."""
    from config_generator import DOCUMENT_PREFIX as INGEST_PREFIX

    assert DOCUMENT_PREFIX == INGEST_PREFIX
