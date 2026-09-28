# Data

> **Parent**: [README.md](../README.md)

Everything the app searches — product text, 768-dim embeddings, attribute tags,
the seeded color taxonomy, relevance judgments — is a permanent one-time export
committed via Git LFS in `data/precomputed/` and bulk-loaded verbatim by every
`make setup` (`langchain_agent/scripts/load_precomputed_indices.py`). There is
no ingest pipeline, no rebuild path, and no cloud API anywhere.

| File | Contents |
|------|----------|
| `precomputed/products_dump.parquet` | Full `_source` of the 158,637 products (ESCI US `test` + `small_version` judged products; 95.5% carry a SQID image URL), including the `embedding` vector |
| `precomputed/attribute_mappings_dump.parquet` | The `agentic_hybrid_search_attribute_mappings` store — seeded color only, **zero** waterproof rows by design (see CLAUDE.md) |
| `precomputed/judgments_dump.parquet` | The `esci_judgments` index: 65,028 queries, filtered to products present in the corpus |
| `precomputed/dump_metadata.json` | Source commit, `EMBEDDINGS_MODEL`, a hash of `INDEX_MAPPING`, expected doc counts |

The loader refuses to load a dump whose `INDEX_MAPPING` hash doesn't match the
current `retrieval/vector_store.py`, and `make setup` fails with a `git lfs pull`
message if the directory is missing. Changing the embedding model, the mapping,
or attribute detection would mean building a new corpus export with new one-off
tooling — nothing in this repo does that.

## Provenance

The corpus was built once from the Amazon ESCI dataset (US locale, `test` +
`small_version` splits) joined with [SQID](https://github.com/Crossing-Minds/shopping-queries-image-dataset)
image URLs, selecting whole queries and keeping all of their judged products
(~19.8 judged products per test query — a random product sample left about one,
which made NDCG and the ground-truth demo meaningless). Relevance labels map
`E`→4.0, `S`→1.0, `C`→0.1, `I`→0.0. The source parquets and the scripts that
produced them were removed once the export was committed.

## Troubleshooting

**`make setup` fails with "data/precomputed/ is missing":** run `git lfs pull`
(`git lfs install` first on a fresh machine).

**Judgment lookups always miss:** check that `esci_judgments` exists and was
created from `langchain_agent/mapping/judgments_mapping.json` — its
`query.keyword` has a lowercase normalizer that a dynamically-mapped index
lacks, so mixed-case queries miss. Misses are graceful; the observability panel
falls back to the confidence proxy.
