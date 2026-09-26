"""
Generates lucille-esci/conf/products.generated.conf fresh before every
Lucille run, from whatever attribute types are currently registered in the
OpenSearch-backed attribute mapping store.

Replaces the old static products.conf's dedicated normalizeAttributes/
normalizeMaterial stage blocks with one generated AttributeDetectorStage
entry per registered attribute type (color, waterproof, and any future type
the live agent registers) — each a distinct, independently-named pipeline
stage instance sharing the one generic Java class. A brand-new attribute
type needs zero hand-edited config: the next call to generate_products_conf()
picks it up automatically.

Usage:
    PYTHONPATH=. python3 config_generator.py
    # or import and call generate_products_conf() / write_generated_conf()
"""

from pathlib import Path
from typing import List, Optional

from retrieval.attribute_mapping_store import INDEX_NAME as MAPPING_INDEX_NAME
from retrieval.attribute_mapping_store import AttributeMappingStore

CONF_DIR = Path(__file__).parent / "lucille-esci" / "conf"
GENERATED_CONF_PATH = CONF_DIR / "products.generated.conf"

_PRELUDE = """# Lucille ETL: ESCI Products → OpenSearch
#
# GENERATED FILE — do not hand-edit. Produced by config_generator.py
# immediately before every Lucille run, from whatever attribute types are
# currently registered in the OpenSearch-backed attribute mapping store
# (agentic_hybrid_search_attribute_mappings). See that module and
# AttributeDetectorStage.java for the mechanism.
#
# Reads the text-only products parquet (data/esci_products.parquet) and embeds
# chunk_text in-pipeline with a local Ollama model (OllamaEmbedStage, #148) --
# no vectors are committed, no cloud embedding API is called.
#
# Required env vars (set from langchain_agent/.env by lucille_ingest.sh):
#   OPENSEARCH_URL   e.g. http://localhost:9200
#   OPENSEARCH_INDEX e.g. agentic_hybrid_search_docs
#   PARQUET_PATH     absolute path to esci_products.parquet
#   OLLAMA_HOST      e.g. http://host.docker.internal:11434 (embed stage only)
#   EMBEDDINGS_MODEL e.g. nomic-embed-text (embed stage only)

connectors: [
  {
    name: "esciProductsConnector"
    class: "com.kmwllc.lucille.parquet.connector.ParquetConnector"
    pipeline: "productsPipeline"

    pathToStorage: ${PARQUET_PATH}
    fsUri: "file:///"
    idField: "product_id"
  }
]

pipelines: [
  {
    name: "productsPipeline"
    stages: [
      # Build chunk_text: concatenate title + description + bullet_point (mirrors ingest_esci_products.py)
      {
        name: "buildChunkText"
        class: "com.kmwllc.lucille.stage.Concatenate"
        dest: "chunk_text"
        formatString: "{product_title} {product_description} {product_bullet_point}"
        updateMode: "overwrite"
      }
{embed_stage}      # Copy product_title → title (used by the search pipeline).
      {
        name: "copyTitle"
        class: "com.kmwllc.lucille.stage.CopyFields"
        fieldMapping: {
          "product_title": "title"
        }
        updateMode: "overwrite"
      }
      # Copy product_title → title_suggest and product_brand → brand_suggest.
      # These fields use the edge-ngram autocomplete_analyzer and are queried
      # exclusively by /api/suggest. Without them the typeahead returns zero results.
      {
        name: "copySuggestFields"
        class: "com.kmwllc.lucille.stage.CopyFields"
        fieldMapping: {
          "product_title": "title_suggest"
          "product_brand": "brand_suggest"
        }
        updateMode: "overwrite"
      }
      # Drop internal pandas index and raw text fields that are already captured in chunk_text
      {
        name: "dropInternalFields"
        class: "com.kmwllc.lucille.stage.DeleteFields"
        fields: ["__index_level_0__"]
      }
      # Normalize product brand: fixed deterministic transform (lowercase +
      # generic-placeholder consolidation), not a discovered taxonomy — no
      # OpenSearch dependency, always present regardless of registered
      # attribute types.
      {
        name: "normalizeBrand"
        class: "com.kmwllc.esci.BrandNormalizerStage"
      }
"""

_EPILOGUE = """      # Set collection_id required by the search API and health check
      # (mirrors the value written by OpenSearchVectorStore in ingest_esci_products.py)
      {
        name: "setCollectionId"
        class: "com.kmwllc.lucille.stage.SetStaticValues"
        staticValues: {
          "collection_id": "esci_products"
        }
        updateMode: "overwrite"
      }
      # Remove empty/null fields to avoid mapping conflicts
      {
        name: "removeEmptyFields"
        class: "com.kmwllc.lucille.stage.RemoveEmptyFields"
      }
    ]
  }
]

indexer {
  type: "OpenSearch"
  batchSize: 250
  batchTimeout: 5000
  sendEnabled: true
}

opensearch {
  url: ${OPENSEARCH_URL}
  index: ${OPENSEARCH_INDEX}
  acceptInvalidCert: true
}

# Embedding is GPU-bound on the Ollama host: ~100 docs/s at 4 concurrent
# requests, no faster at 8 (measured, nomic-embed-text on an M4 Max).
worker {
  threads: 4
}

log {
  seconds: 15
}
"""


# nomic-embed-text is asymmetric: documents and queries carry different task
# prefixes. The query side (retrieval/embeddings.py) must prepend the matching
# QUERY prefix or kNN recall drops.
DOCUMENT_PREFIX = "search_document: "
VECTOR_DIMENSION = 768  # must equal the index mapping's knn_vector dimension

_EMBED_STAGE = f"""      # Embed chunk_text with a local Ollama model (#148). Hard-fails at
      # start-up if Ollama is unreachable or the model isn't pulled -- an index
      # without vectors would silently make every hybrid query BM25-only.
      {{
        name: "embedChunkText"
        class: "com.kmwllc.esci.OllamaEmbedStage"
        source: "chunk_text"
        dest: "embedding"
        hostURL: ${{OLLAMA_HOST}}
        modelName: ${{EMBEDDINGS_MODEL}}
        prefix: "{DOCUMENT_PREFIX}"
        dimensions: {VECTOR_DIMENSION}
      }}
"""


def _stage_name(attribute_type: str) -> str:
    """'waterproof' -> 'detectWaterproof'; 'glass_ceramic' -> 'detectGlassCeramic'."""
    parts = attribute_type.replace("-", "_").split("_")
    camel = "".join(p.capitalize() for p in parts)
    return f"detect{camel}"


def _render_attribute_stage(attribute_type: str) -> str:
    return f"""      # Detect and normalize product {attribute_type} from unstructured text
      # (chunk_text, built above). Generated stage entry — one independent
      # instance of the generic AttributeDetectorStage class per attribute
      # type currently registered in the OS-backed mapping store.
      # Outputs: product_{attribute_type}, product_{attribute_type}_primary,
      # product_{attribute_type}_secondary.
      # Same client + TLS/auth settings as the indexer's root `opensearch`
      # block (HOCON merge), pointed at the mapping store index.
      {{
        name: "{_stage_name(attribute_type)}"
        class: "com.kmwllc.esci.AttributeDetectorStage"
        attributeType: "{attribute_type}"
        opensearch: ${{opensearch}} {{ index: "{MAPPING_INDEX_NAME}" }}
      }}
"""


def generate_products_conf(attribute_types: Optional[List[str]] = None, embed: bool = True) -> str:
    """
    Render the full products.conf HOCON text.

    Args:
        attribute_types: attribute types to generate a detector stage for.
            Queried live from the OS-backed mapping store if None.
        embed: include the Ollama embed stage. False only for the throwaway
            first pass of ``lucille_ingest.sh --seed-taxonomy``, which exists
            just to put chunk_text in the index for taxonomy discovery; the
            second pass re-indexes every product with vectors anyway, so
            embedding twice would add ~26 min to setup for nothing.

    Returns:
        Full HOCON config text.
    """
    if attribute_types is None:
        attribute_types = AttributeMappingStore().get_all_attribute_types()

    middle = "".join(_render_attribute_stage(t) for t in attribute_types)
    prelude = _PRELUDE.replace("{embed_stage}", _EMBED_STAGE if embed else "")
    return prelude + middle + _EPILOGUE


def write_generated_conf(attribute_types: Optional[List[str]] = None, embed: bool = True) -> Path:
    """Generate and write products.generated.conf. Returns the path written."""
    content = generate_products_conf(attribute_types, embed=embed)
    GENERATED_CONF_PATH.write_text(content)
    return GENERATED_CONF_PATH


if __name__ == "__main__":
    import sys

    embed = "--no-embed" not in sys.argv[1:]
    path = write_generated_conf(embed=embed)
    types = AttributeMappingStore().get_all_attribute_types()
    # lucille_ingest.sh matches "stages for: []" in this line -- keep the format.
    print(f"Generated {path} (embed={embed}) with stages for: {types}")
