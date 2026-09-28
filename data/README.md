# ESCI Data

> **Parent**: [README.md](../README.md)

This repo has no local ingest pipeline any more. Everything the app reads —
embeddings, attribute tags, the seeded color taxonomy, judgments — is a
permanent, one-time export already committed via Git LFS in
`data/precomputed/`, bulk-loaded verbatim by every `make setup`. There is no
`--from-scratch` flag, no rebuild path, and no cloud embedding API involved
anywhere.

## `precomputed/` — the only index source

`data/precomputed/` holds a full `_source` export (embeddings, `product_*_primary`/
`_secondary` attribute tags, seeded color taxonomy) of the products, judgments, and
attribute-mapping indices as they existed after the corpus's original ingest and
taxonomy seeding:

| File | Contents |
|------|----------|
| `products_dump.parquet` | Full `_source` of every doc in the products index, including the 768-dim `embedding` vector |
| `attribute_mappings_dump.parquet` | The `agentic_hybrid_search_attribute_mappings` store (seeded color; **zero** waterproof entries — see CLAUDE.md) |
| `judgments_dump.parquet` | The `esci_judgments` index (already filtered to products present in the corpus) |
| `dump_metadata.json` | Source commit, `EMBEDDINGS_MODEL`, a hash of `INDEX_MAPPING`, and expected doc counts — the loader refuses to load a dump whose mapping hash doesn't match the current `INDEX_MAPPING` |

`setup.py` always uses this (`scripts/load_precomputed_indices.py`, a plain bulk load —
no Ollama, no embedding, no ingest pipeline of any kind). If this directory is missing
(Git LFS objects not pulled), setup fails immediately with a `git lfs pull` message —
there is no fallback.

**This was a one-time export**, run once and committed. The corpus is static and isn't
expected to change, so this isn't meant to run again — the export/verify tooling that
produced it (`scripts/export_precomputed_indices.py`, `scripts/verify_precomputed_load.py`)
was retired after use, and the ingest pipeline that originally built the source index
(a Java/Lucille ETL) was removed from this repo entirely once its one-time job was done.
If the embedding model, `INDEX_MAPPING`, or attribute detection logic ever changes for
real, `load_precomputed_indices.py` will refuse to load the now-mismatched dump (it checks
a hash of `INDEX_MAPPING`) — at that point, new one-off tooling would need to be written
fresh to rebuild the corpus; there is nothing to fall back to.

## Files

| File | Records | Contents | Origin |
|------|---------|----------|--------|
| `esci_products.parquet` | 158,637 products | `product_id` (ASIN), `product_title`, `product_description`, `product_bullet_point`, `product_brand`, `product_color`, `product_locale`, `product_image_url` | Every judged product of the ESCI US `test` + `small_version` queries, built by `scripts/build_product_sample.py` (#147). 95.5% have a real SQID image URL |
| `esci_judgments_aggregated.parquet` | 97,345 queries | `query_id`, `query`, `locale`, `split`, `small_version`, `judgments_json` (relevance: `E`→4.0, `S`→1.0, `C`→0.1, `I`→0.0) | Amazon ESCI, pre-aggregated by query (`scripts/prepare_judgments_parquet.py`) |

These two are the **historical source inputs** that were fed to the (now-removed) ingest
pipeline to build the index that `data/precomputed/` is exported from. Nothing in this repo
reads them any more — they're kept only as provenance / for the unlikely case that new
ingest tooling ever needs to be written from scratch. `scripts/build_product_sample.py` and
`scripts/prepare_judgments_parquet.py` (which produce them) are likewise kept only as
reference for how the corpus was originally built, not as part of any live workflow.

### Why query-first

The corpus used to be a random 10K-product sample. Sampling products at random
leaves about one judged product per query in the index, so NDCG and the
ground-truth demo meant little. Selecting whole queries and keeping *all* of
their judged products leaves ~19.8 judged products per test query in the
corpus. The ESCI test/small subset is also exactly the one
[SQID](https://github.com/Crossing-Minds/shopping-queries-image-dataset)
scraped image URLs for.

## How They Were Used (historical)

The now-removed ingest pipeline read both files:
- **Products**: built `chunk_text` (title + description + bullets), embedded it through
  Ollama, ran attribute detection, and indexed into `OPENSEARCH_INDEX_NAME`.
- **Judgments**: indexed into `esci_judgments` (created from
  `langchain_agent/mapping/judgments_mapping.json`), filtered to queries with at
  least one product in the products index. `OpenSearchVectorStore.lookup_judgments(query)`
  uses that index for ground-truth metrics today — that part is still live, it's just
  loaded from `data/precomputed/judgments_dump.parquet` now, not built from this file.

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
```

Null text fields are written as `""`. A naive `chunk_text` build leaves a literal
`{product_description}` placeholder when a field is null, which is how the old
sample ended up with that string in 45% of its products.

### Judgments

```bash
PYTHONPATH=. python scripts/prepare_judgments_parquet.py --locale us --force
```

## Storage Notes

- **Size**: products ~125 MB (text only); judgments ~23 MB.
- **Versioning**: Git LFS tracks `data/*.parquet`; `git lfs install` is required locally.
- **Changing the embedding model** would require rebuilding the corpus from scratch with
  new tooling — there is no ingest path in this repo any more. The index mapping pins
  768 dimensions, and the query side (`EMBEDDINGS_MODEL`) must match whatever the corpus
  was actually embedded with.

## Troubleshooting

**`make setup` fails with "data/precomputed/ is missing":** run `git lfs pull`.

**Judgment lookups always miss:** check that `esci_judgments` exists and was
created from `langchain_agent/mapping/judgments_mapping.json`. Its `query.keyword`
has a lowercase normalizer, and a dynamically-mapped index lacks it, so mixed-case
queries miss. Misses are graceful; the observability panel falls back to the
confidence proxy.
