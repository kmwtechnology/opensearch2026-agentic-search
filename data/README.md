# ESCI Data

> **Parent**: [README.md](../README.md)

Precomputed ESCI product and judgment parquets committed to the repo. Read directly by
`scripts/lucille_ingest.sh` — no Google API embedding calls needed for the default 10k ingest.

## Files

| File | Records | Schema | Origin |
|------|---------|--------|--------|
| `esci_products_sample_10000.parquet` | 9,618 products | `product_id`, `product_title`, `product_brand`, `product_color`, `knn_vector` (768-dim Gemini embeddings), `collection_id` | Amazon ESCI dataset, sampled with `random_state=42`, pre-embedded |
| `esci_judgments_aggregated.parquet` | 97,345 queries | `query`, `judgments` (list of `[product_id, relevance_label]`), relevance ∈ {`E`→4.0, `S`→1.0, `C`→0.1, `I`→0.0} | Amazon ESCI dataset, pre-aggregated by query |

## How They're Used

`scripts/lucille_ingest.sh` reads both files:
- **Products** — bulk-indexed into OpenSearch via Lucille ETL; embeddings are copied directly (no re-embedding)
- **Judgments** — indexed as a separate `esci_judgments` index; lookups via `OpenSearchVectorStore.lookup_judgments(query)` for ground-truth evaluation

## Regenerating Data

### Products

To create a new product sample (different size or seed):

```bash
cd langchain_agent
PYTHONPATH=. python ingest_esci_products.py --limit 50000 --resample
# Outputs: esci/shopping_queries_dataset/esci_products_sample_50000.parquet
# Requires re-embedding (calls GOOGLE_API_KEY for each product)
```

Then move it to `data/` and update `scripts/lucille_ingest.sh`:
```bash
cp esci/shopping_queries_dataset/esci_products_sample_50000.parquet data/
# Edit lucille_ingest.sh to reference the new sample
```

For massive samples (1.2M+ products), use `bigquery_batch_embeddings.py`:
```bash
PYTHONPATH=. python bigquery_batch_embeddings.py --help
# Parallelizes embedding across BigQuery ML
```

### Judgments

To re-aggregate (e.g., after updating locale or label mapping):

```bash
cd langchain_agent
PYTHONPATH=. python scripts/prepare_judgments_parquet.py --locale us --force
# Outputs: data/esci_judgments_aggregated.parquet (overwrites existing)
```

Then re-ingest:
```bash
bash scripts/lucille_ingest.sh --skip-products
```

## Storage Notes

- **Size** — products: ~200 MB (9k docs × 768-dim vectors); judgments: ~50 MB (97k queries)
- **Compression** — parquet format with Snappy codec (default)
- **Versioning** — Git LFS tracks these files; `git lfs install` required locally
- **Idempotency** — Lucille ingest is idempotent; re-running `lucille_ingest.sh` is safe

## Sources

- **ESCI Dataset** — [Amazon Science ESCI Data](https://github.com/amazon-science/esci-data)
- **Embeddings** — `models/gemini-embedding-001` (768-dim), generated with `output_dimensionality=768`
- **Relevance labels** — Amazon e-commerce relevance judgments (5-point scale mapped to 4 numeric levels)

## GCP Cloud Run

When deploying to Cloud Run, `gcp-init.sh` re-ingests ESCI data by running `lucille_ingest.sh`
on the GitHub Actions runner (Java 17+, Maven, Lucille checkout present). The runner reads
`data/*.parquet` committed here and indexes into the hosted OpenSearch cluster.

## Troubleshooting

**Lucille ingest fails with "file not found":**
```bash
ls -lh data/esci_*.parquet
# If missing, commit them:
git lfs pull
```

**Re-embedding is slow:**
```bash
# For large samples, use BigQuery:
PYTHONPATH=. python bigquery_batch_embeddings.py \
  --project <GCP_PROJECT> \
  --parquet-input esci/shopping_queries_dataset/esci_products_sample_100000.parquet \
  --parquet-output data/esci_products_sample_100000.parquet
# ~15–30 min for 1.2M products vs ~4.5 h serially
```

**Judgment lookups always miss:**
Check that `esci_judgments_aggregated.parquet` is indexed and that queries match exactly
(case-sensitive, whitespace-sensitive). Misses are graceful — the observability panel
falls back to the confidence proxy.
