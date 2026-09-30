"""Unit tests for retrieval/embeddings.py -- the exact text sent to Ollama (#148).

nomic-embed-text is asymmetric, so the prefix on each request is the whole
point. A fake client records what would have gone over the wire; no Ollama
server is needed.
"""

import pytest

from retrieval.embeddings import QUERY_PREFIX, PrefixedOllamaEmbeddings


class _FakeClient:
    def __init__(self):
        self.inputs = []

    def embed(self, model, texts, **kwargs):
        self.inputs.append(list(texts))
        return {"embeddings": [[0.0] * 768 for _ in texts]}


@pytest.fixture
def emb():
    e = PrefixedOllamaEmbeddings(model="nomic-embed-text")
    e._client = _FakeClient()
    return e


def test_query_gets_query_prefix_only(emb):
    emb.embed_query("waterproof boots")
    # Regression: OllamaEmbeddings.embed_query delegates to self.embed_documents,
    # which would stack the document prefix on top of the query prefix.
    assert emb._client.inputs == [[QUERY_PREFIX + "waterproof boots"]]
