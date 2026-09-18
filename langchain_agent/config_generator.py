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
# Reads the precomputed 10k parquet sample (embeddings already baked in as 768-dim doubles).
# No embedding API calls are made during this ingest.
#
# Required env vars (set from langchain_agent/.env by lucille_ingest.sh):
#   OPENSEARCH_URL   e.g. http://localhost:9200
#   OPENSEARCH_INDEX e.g. agentic_hybrid_search_docs
#   PARQUET_PATH     absolute path to esci_products_sample_10000.parquet

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
      # Copy product_title → title (used by the search pipeline).
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

worker {
  threads: 2
}

log {
  seconds: 15
}
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


def generate_products_conf(attribute_types: Optional[List[str]] = None) -> str:
    """
    Render the full products.conf HOCON text.

    Args:
        attribute_types: attribute types to generate a detector stage for.
            Queried live from the OS-backed mapping store if None.

    Returns:
        Full HOCON config text.
    """
    if attribute_types is None:
        attribute_types = AttributeMappingStore().get_all_attribute_types()

    middle = "".join(_render_attribute_stage(t) for t in attribute_types)
    return _PRELUDE + middle + _EPILOGUE


def write_generated_conf(attribute_types: Optional[List[str]] = None) -> Path:
    """Generate and write products.generated.conf. Returns the path written."""
    content = generate_products_conf(attribute_types)
    GENERATED_CONF_PATH.write_text(content)
    return GENERATED_CONF_PATH


if __name__ == "__main__":
    path = write_generated_conf()
    types = AttributeMappingStore().get_all_attribute_types()
    print(f"Generated {path} with stages for: {types}")
