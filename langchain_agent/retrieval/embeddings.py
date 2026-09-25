"""
Query-side embeddings: local Ollama, with nomic-embed-text's task prefixes (#148).

Documents are embedded at ingest by Lucille's ``OllamaEmbedStage`` with the
``search_document: `` prefix (see ``config_generator.DOCUMENT_PREFIX``). A
query must be embedded by the same model with the matching ``search_query: ``
prefix -- nomic-embed-text is asymmetric, and a bare query lands in a
different part of the space, which quietly weakens kNN recall.
LangChain's ``OllamaEmbeddings`` adds no prefixes, hence this subclass.
"""

from typing import List

from langchain_ollama import OllamaEmbeddings

from core.config import EMBEDDINGS_MODEL, OLLAMA_HOST, OLLAMA_KEEP_ALIVE

QUERY_PREFIX = "search_query: "
# Must match config_generator.DOCUMENT_PREFIX (what Lucille prepends at ingest).
DOCUMENT_PREFIX = "search_document: "


class PrefixedOllamaEmbeddings(OllamaEmbeddings):
    """OllamaEmbeddings that prepends nomic's asymmetric task prefixes.

    The query methods call the *base-class* document methods directly:
    ``OllamaEmbeddings.embed_query`` is implemented as
    ``self.embed_documents([text])``, so going through ``super().embed_query``
    would dispatch back into this class's ``embed_documents`` and embed every
    query as ``"search_document: search_query: ..."`` -- silently wrong.
    """

    def embed_query(self, text: str) -> List[float]:
        return OllamaEmbeddings.embed_documents(self, [QUERY_PREFIX + text])[0]

    async def aembed_query(self, text: str) -> List[float]:
        return (await OllamaEmbeddings.aembed_documents(self, [QUERY_PREFIX + text]))[0]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return super().embed_documents([DOCUMENT_PREFIX + t for t in texts])

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        return await super().aembed_documents([DOCUMENT_PREFIX + t for t in texts])


def build_embeddings() -> PrefixedOllamaEmbeddings:
    """The one embeddings client every query-side caller uses."""
    return PrefixedOllamaEmbeddings(
        model=EMBEDDINGS_MODEL, base_url=OLLAMA_HOST, keep_alive=OLLAMA_KEEP_ALIVE
    )
