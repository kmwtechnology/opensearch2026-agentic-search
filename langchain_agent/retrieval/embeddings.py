"""
Query-side embeddings: local Ollama, with nomic-embed-text's task prefixes (#148).

Every document in the committed precomputed corpus (data/precomputed/) was
embedded with the ``search_document: `` prefix at the time it was built. A query must be embedded by the same model with the
matching ``search_query: `` prefix -- nomic-embed-text is asymmetric, and a
bare query lands in a different part of the space, which quietly weakens kNN
recall. LangChain's ``OllamaEmbeddings`` adds no prefixes, hence this
subclass.
"""

from typing import List

from langchain_ollama import OllamaEmbeddings

from core.config import EMBEDDINGS_MODEL, OLLAMA_HOST, OLLAMA_KEEP_ALIVE

QUERY_PREFIX = "search_query: "


class PrefixedOllamaEmbeddings(OllamaEmbeddings):
    """OllamaEmbeddings that prepends nomic's query task prefix. Query-side only: nothing
    in this repo embeds documents (the corpus ships precomputed)."""

    def embed_query(self, text: str) -> List[float]:
        return OllamaEmbeddings.embed_documents(self, [QUERY_PREFIX + text])[0]


def build_embeddings() -> PrefixedOllamaEmbeddings:
    """The one embeddings client every query-side caller uses."""
    return PrefixedOllamaEmbeddings(
        model=EMBEDDINGS_MODEL, base_url=OLLAMA_HOST, keep_alive=OLLAMA_KEEP_ALIVE
    )
