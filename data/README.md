# ESCI Data

> **Parent**: [README.md](../README.md)

Product and judgment parquets committed to the repo (Git LFS) and read by
`langchain_agent/scripts/lucille_ingest.sh`. They hold **text only**, with no vectors.
Lucille embeds every product at ingest time with a local Ollama model
(`OllamaEmbedStage`, `nomic-embed-text`, 768-dim; see #148), so no cloud
embedding API is involved anywhere.

## Files

| File | Records | Contents | Origin |
|------|---------|----------|--------|
| `esci_products.parquet` | 158,637 products | `product_id` (ASIN), `product_title`, `product_description`, `product_bullet_point`, `product_brand`, `product_color`, `product_locale`, `product_image_url` | Every judged product of the ESCI US `test` + `small_version` queries, built by `scripts/build_product_sample.py` (#147). 95.5% have a real SQID image URL |
| `esci_judgments_aggregated.parquet` | 97,345 queries | `query_id`, `query`, `locale`, `split`, `small_version`, `judgments_json` (relevance: `E`→4.0, `S`→1.0, `C`→0.1, `I`→0.0) | Amazon ESCI, pre-aggregated by query (`scripts/prepare_judgments_parquet.py`) |
| `esci_products_smoke.parquet` | 1,921 products | same as `esci_products.parquet` | `build_product_sample.py --max-products 2000`: a small sample for fast local ingest tests |

### Why query-first

The corpus used to be a random 10K-product sample. Sampling products at random
leaves about one judged product per query in the index, so NDCG and the
ground-truth demo meant little. Selecting whole queries and keeping *all* of
their judged products leaves ~19.8 judged products per test query in the
corpus. The ESCI test/small subset is also exactly the one
[SQID](https://github.com/Crossing-Minds/shopping-queries-image-dataset)
scraped image URLs for.

## How They're Used

`scripts/lucille_ingest.sh` reads both files:
- **Products**: Lucille builds `chunk_text` (title + description + bullets),
  embeds it through Ollama, runs attribute detection, and indexes into
  `OPENSEARCH_INDEX_NAME`. The full corpus takes ~35-40 min, almost all of it embedding.
- **Judgments**: indexed into `esci_judgments` (created from
  `lucille-esci/mapping/judgments_mapping.json`), filtered to queries with at
  least one product in the products index. `OpenSearchVectorStore.lookup_judgments(query)`
  uses it for ground-truth metrics. After the products index changes, refresh
  only the judgments with `bash scripts/lucille_ingest.sh --skip-products`.

## Regenerating the products parquet

Inputs are external and gitignored under `<repo>/esci/`:

1. The ESCI dataset: `git clone https://github.com/amazon-science/esci-data esci/`
   (the products parquet is 1.1 GB, via LFS).
2. The SQID image URLs: `esci/sqid/product_image_urls.csv` and
   `esci/sqid/supp_product_image_urls.csv`, from
   [Crossing-Minds/shopping-queries-image-dataset](https://github.com/Crossing-Minds/shopping-queries-image-dataset) (`sqid/`).

Then, from `langchain_agent/`:

```bash
PYTHONPATH=. python scripts/build_product_sample.py --dry-run          # counts + demo preconditions only
PYTHONPATH=. python scripts/build_product_sample.py                    # writes data/esci_products.parquet
PYTHONPATH=. python scripts/build_product_sample.py --max-products 2000 --output ../data/esci_products_smoke.parquet
```

Null text fields are written as `""`. When a field is null, Lucille's
`Concatenate` stage leaves a literal `{product_description}` placeholder in
`chunk_text`, which is how the old sample ended up with that string in 45% of
its products.

### Judgments

```bash
PYTHONPATH=. python scripts/prepare_judgments_parquet.py --locale us --force
bash scripts/lucille_ingest.sh --skip-products
```

## Storage Notes

- **Size**: products ~125 MB (text only); judgments ~23 MB.
- **Versioning**: Git LFS tracks `data/*.parquet`; `git lfs install` is required locally.
- **Changing the embedding model** means a full re-ingest. The index mapping
  pins 768 dimensions, and Lucille and the query side must use the same model
  (`EMBEDDINGS_MODEL`).

## Troubleshooting

**Lucille ingest fails with "file not found":** run `git lfs pull`.

**Ingest stops at "Ollama embedding model ... not available":** start Ollama and
`ollama pull nomic-embed-text`. The Docker Lucille path reaches the host's
Ollama via `host.docker.internal` automatically.

**Judgment lookups always miss:** check that `esci_judgments` exists and was
created from `judgments_mapping.json`. Its `query.keyword` has a lowercase
normalizer, and a dynamically-mapped index lacks it, so mixed-case queries miss.
Misses are graceful; the observability panel falls back to the confidence proxy.
