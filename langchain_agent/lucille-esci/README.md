# Lucille ESCI Configuration

> **Parent**: [langchain_agent/README.md](../README.md)

Maven module that configures the [Lucille](https://github.com/kmwtechnology/lucille) ETL framework
for ingesting Amazon ESCI products and relevance judgments into OpenSearch.

**This is not the Lucille source code.** It's a configuration package that wraps Lucille's Java
libraries with ESCI-specific field mappings, analyzers, and ingest pipelines.

## Directory Structure

```text
lucille-esci/
├── conf/              # HOCON pipeline configurations
│   ├── products.conf  # Product ingest: field mappings, chunking, embedding, collection_id
│   └── judgments.conf # Judgment ingest: relevance label mapping (E/S/C/I → 4.0/1.0/0.1/0.0)
├── mapping/           # OpenSearch field mappings and analyzers
│   ├── products.json  # Index template: knn_vector, text, keyword fields
│   └── judgments.json # Judgment index template
├── pom.xml            # Maven coordinates; references external Lucille version
└── target/            # Compiled artifacts (auto-generated)
```

## How It Works

1. **Lucille source** — external checkout at `LUCILLE_DIR` (default `~/github/kmwtechnology/lucille`)
2. **lucille-esci config** — this directory specifies field mappings and ETL rules
3. **lucille_ingest.sh** — orchestration script that:
   - Checks/builds `lucille-esci` + `lucille-bom` + `lucille-parquet` from the source tree
   - Reads `data/*.parquet` (precomputed embeddings, no API calls)
   - Applies `conf/*.conf` to transform records
   - Bulk-indexes into OpenSearch

## Configuration Files

### `conf/products.conf` (HOCON)

```hocon
ingestConf {
  processor {
    lucene {
      indexName = "agentic_hybrid_search_docs"
      analyzerName = "multilingual_analyzer"
    }
  }
  
  globalFieldConfig {
    knn_vector.dimension = 768
  }
  
  documentFields {
    product_id     { type = "text" }
    product_title  { type = "text"; copy_to = ["title_suggest"] }
    knn_vector     { type = "knn_vector"; dimension = 768 }
  }
  
  # CRITICAL: collection_id is required on EVERY product doc
  # See main.py for collection_id-based filtering
  defaultFields {
    collection_id = "esci_products"
  }
}
```

**Key points:**

- `title_suggest` and `brand_suggest` are **edge-ngram** fields required by `/api/suggest` typeahead
- `collection_id=esci_products` is set on every document (checked by all retrieval queries)
- `knn_vector.dimension = 768` matches `VECTOR_DIMENSION` in `.env`

### `conf/judgments.conf` (HOCON)

Maps ESCI relevance labels to numeric scores:

- `E` (Exact) → `4.0`
- `S` (Substitute) → `1.0`
- `C` (Complement) → `0.1`
- `I` (Irrelevant) → `0.0`

Lookups via `OpenSearchVectorStore.lookup_judgments(query)` — exact keyword match on `query.keyword`.

### `mapping/products.json` (OpenSearch mappings)

Field definitions for the product index:

- `knn_vector` — HNSW index, 768-dim
- `product_title`, `product_brand`, `product_color` — text + keyword dual mapping (faceting)
- `title_suggest`, `brand_suggest` — edge-ngram analyzers for prefix matching
- `product_color_primary`, `product_color_secondary` — normalized color fields (keyword, added post-ingest)
- `product_brand_normalized` — normalized brand field (keyword, added post-ingest)

## Versioning

The pinned Lucille version has a single source of truth: `LUCILLE_VERSION` in `langchain_agent/.env.example` (and your local `.env`). Everything else derives from it:

- `scripts/lucille_ingest.sh` reads `LUCILLE_VERSION` from the environment (falling back to a default if unset) and exports it before invoking Maven.
- `lucille-esci/pom.xml`'s `<lucille.version>` resolves via `${env.LUCILLE_VERSION}` — running `mvn` here directly (outside `lucille_ingest.sh`) requires `export LUCILLE_VERSION=...` first.
- `.github/workflows/reindex.yml` reads the same value out of `.env.example` and clones Lucille pinned to that tag.

To bump the version: update `LUCILLE_VERSION` in `.env.example` (and your `.env`) — no other file needs a matching literal.

## Running Lucille Ingest

### Standard (default 10 k sample)

```bash
# From langchain_agent/:
bash scripts/lucille_ingest.sh
```

**What it does** (Docker path — default, `LUCILLE_USE_DOCKER=true`):

1. Builds a derived `lucille` Docker image via `docker/lucille/Dockerfile`:
   - Layers only our custom ESCI stages (AttributeNormalizerStage) onto the published `kmwtechnology/lucille:${LUCILLE_VERSION}` image
   - Resolves `lucille-parquet` + dependencies from Maven Central via this module's `pom.xml` (no Lucille source checkout needed)
   - Cache-efficient: only compiles our code (~1-2 GB disk), not the full Lucille framework (6-7 GB)
   - Build time: ~2-3 min (first run); ~10 s (cached)
2. Runs Lucille products ingest via `docker compose run --rm lucille`: `data/esci_products_sample_10000.parquet` → OpenSearch
   - Applies `conf/products.conf` transformations: title/brand/color copy, chunk_text build, collection_id set
   - Runs `normalizeAttributes` stage (custom Java stage) for color/brand normalization during ingest
   - ~10 s
3. Runs Lucille judgments ingest: `data/esci_judgments_aggregated.parquet` → OpenSearch
   - ~5 s

**Total:** ~30–40 s (including Docker build on first run)

**Details:**

- Reads `data/esci_products_sample_10000.parquet` (9,618 docs + embeddings)
- Reads `data/esci_judgments_aggregated.parquet` (97,345 queries)
- No embedding API calls needed (embeddings precomputed in parquet)
- Attribute normalization happens during Lucille ingest via `AttributeNormalizerStage` (deterministic, reproducible, rules-only)

### With reset (atomically recreates index)

```bash
bash scripts/lucille_ingest.sh --reset-index
```

Deletes the index via Python's `setup.py --reset-index` first, preventing a race where Lucille
auto-creates a broken default-mapped index between a curl DELETE and the ingest's first write.

### Skip judgments

```bash
bash scripts/lucille_ingest.sh --skip-judgments
```

Ingests products only.

## Environment Setup

**Default (Docker path):** `lucille_ingest.sh` runs Lucille via Docker. Only Docker Desktop is required:

```bash
docker --version       # Docker 20.10+
```

**Optional native path:** Set `LUCILLE_USE_DOCKER=false` to use the native Java/Maven path instead. This is not recommended for local dev and only exists as a fallback for environments without Docker:

```bash
java -version          # Java 21+
mvn -version           # Maven 3.8+
ls ~/github/kmwtechnology/lucille  # Lucille source (or set LUCILLE_DIR)
```

The Docker path is production-safe (CI/CD, GCP deployments) and is the only path used by `.github/workflows/reindex.yml`.

## Troubleshooting

**Docker path — image build fails:**

```bash
docker compose build lucille --no-cache
```

**Native path (`LUCILLE_USE_DOCKER=false`) — Java not found:**

```bash
brew install openjdk@21
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
```

**Native path — Maven build fails:**

```bash
mvn clean install -DskipTests
```

**OpenSearch DSN wrong:**

```bash
# lucille_ingest.sh loads .env; check:
grep OPENSEARCH_HOST .env
grep OPENSEARCH_PORT .env
```

**Collection_id missing:**

Check `conf/products.conf` — every product doc must have `collection_id=esci_products` set
in `defaultFields`. If products are indexed without it, retrieval queries won't find them.

## Attribute Normalization

**What:** Attribute normalization happens during Lucille ingest via the `AttributeNormalizerStage` custom Java stage.
It normalizes product colors and brands, improving filter recall without needing a separate post-processing step.

**Fields added:**

- `product_color_primary` — canonical primary color ("black", "white", "blue", etc.)
- `product_color_secondary` — canonical secondary color if compound entry (e.g., "Black & Purple" → secondary: "purple")
- `product_brand_normalized` — case-folded brand (e.g., "Sony" → "sony")

**Why:** Raw color/brand fields have high variance ("grey" vs "gray", "Light Grey", "Black Mesh").
Filter queries like "blue wireless headphones" now match all blue variants including "Navy", "Cyan", "Teal", etc.

**How it works:**

1. `AttributeNormalizerStage` is compiled into the Lucille Docker image via `docker/lucille/Dockerfile`
2. Called by `conf/products.conf` as the `normalizeAttributes` stage during ingest
3. Reads `conf/color_mappings.json` (16 canonical colors, synonym expansion, compound extraction)
4. Adds the three normalized fields to every product in a single pass through the ingest pipeline

**Configuration:**

- Color mappings: `conf/color_mappings.json` (deterministic rules)
- Normalizer stage: `src/main/java/com/kmwllc/esci/AttributeNormalizerStage.java` (Java stage implementation)
- Pipeline config: `conf/products.conf` calls the stage as part of the ingest flow

**Reproducibility:**

- Deterministic: rules-only, no AI calls
- Auditable: color mappings committed to git
- Single-pass: normalization happens during ingest, not as a separate post-processing step

## References

- [Lucille Framework](https://github.com/kmwtechnology/lucille)
- [OpenSearch field mappings](https://opensearch.org/docs/latest/im-plugin/index-templates/)
- [HNSW KNN](https://opensearch.org/docs/latest/search-plugins/knn/knn-index/)
- [Attribute Normalization (ARCHITECTURE.md)](../ARCHITECTURE.md#attribute-normalization-color--brand)
