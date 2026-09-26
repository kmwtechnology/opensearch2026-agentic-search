# ESCI Relevancy Benchmark Results

## Purpose

This document describes how to reproduce the hard-query relevancy measurements used in the slide deck (Slide 21). The results table below comes from running `benchmarks/benchmark_esci.py` on the Amazon ESCI dataset with three retrieval configurations measured against ground-truth relevance judgments.

The benchmark focuses on **hard queries** (bottom-quartile by standard-hybrid NDCG@10) because that's where adaptive retrieval strategies provide the most value. For completeness, full-set results are also reported in the appendix.

## ESCI Dataset

**Source:** [amazon-science/esci-data](https://github.com/amazon-science/esci-data) (public repository)

**Size:**

- ~1.8M products (Amazon catalog)
- ~2.6M judgments globally (~1.8M US)
- ~97K queries (US locale)

**Directory structure** (after cloning):

```text
../esci/shopping_queries_dataset/
├── shopping_queries_dataset_products.parquet
├── shopping_queries_dataset_examples.parquet
└── README.md
```

The dataset is **expected at `../esci/` relative to `langchain_agent/`** (i.e., at the repo root level alongside `langchain_agent/`).

## Prerequisites

### 1. Clone the ESCI dataset

```bash
cd /path/to/opensearch2026-agentic-search
git clone https://github.com/amazon-science/esci-data.git ../esci
```

Expected: ~1GB of parquet files will be downloaded.

### 2. Start services

```bash
docker compose up -d     # PostgreSQL + OpenSearch (from repo root)
```

Verify OpenSearch is ready:

```bash
curl -s http://localhost:9200/_cluster/health | python -m json.tool
# Should return "status": "yellow" or "green"
```

### 3. Ingest products and judgments (one-time via Lucille ETL)

```bash
cd langchain_agent
bash scripts/lucille_ingest.sh
```

Expected: ~35-40 minutes, almost all of it Lucille embedding every product through local Ollama (`nomic-embed-text`). Reads `data/esci_products.parquet` (text only) and `data/esci_judgments_aggregated.parquet`. Produces:
- 158,637 products indexed to `agentic_hybrid_search_docs`: every judged product of the ESCI US test/small queries
- 65,028 queries in `esci_judgments` (queries with no product in the index are dropped)

**Note:** The older Python scripts (`ingest_esci_products.py`, `ingest_esci_judgments.py`) were removed in PR #48. Lucille ETL is now the only supported ingest path.

Verify:

```bash
curl -s http://localhost:9200/esci_judgments/_count | python -m json.tool
# Should show 65,028 queries
```

## How to Run

### Fast reproducible benchmark (no LLM)

```bash
cd langchain_agent
make benchmark-esci-fast
```

**Runtime:** ~35 minutes for 5000 queries (each query is embedded through local Ollama; M4 Max).  
**What it does:** Lexical + hybrid + adaptive (with intent fast-path alpha table, no LLM calls).  
**Query set:** ESCI `split=test` + `small_version` queries by default, the ones the corpus is built from, so every query has its full judgment set. `--all-splits` adds train queries, which are only partially judged in this corpus.  
**Reproducibility:** Deterministic and repeatable (no randomness, no LLM).

### Full adaptive benchmark (with LLM intent classification)

```bash
cd langchain_agent
make benchmark-esci
```

**What it does:** Same three configs, but intent classification uses the local LLM (`LLM_MODEL` via Ollama). Slower than `--fast` by one LLM call per query (not re-measured since #148).

### Dry-run (2 queries, sanity check)

```bash
cd langchain_agent
PYTHONPATH=. python benchmarks/benchmark_esci.py --limit 2 --fast
```

**Runtime:** ~10 seconds.

### Save results to JSON

```bash
cd langchain_agent
PYTHONPATH=. python benchmarks/benchmark_esci.py --limit 5000 --hard-only --fast \
  --output benchmark_results_$(date +%Y%m%d_%H%M%S).json
```

Output JSON structure:

```json
{
  "timestamp": "2026-04-30T14:30:00",
  "config": {
    "limit": 5000,
    "alpha_hybrid": 0.25,
    "fetch_k": 40,
    "rerank_top_k": 20,
    "qg_threshold": 0.45,
    "fast_mode": true
  },
  "hard_queries_count": 1250,
  "all_queries_count": 5000,
  "results": {
    "lexical": {
      "ndcg10_mean": 0.XXX,
      "ndcg10_stdev": 0.XXX,
      "mrr_mean": 0.XXX,
      "mrr_stdev": 0.XXX,
      "recall20_mean": 0.XXX,
      "recall20_stdev": 0.XXX,
      "count": 1250
    },
    "hybrid": {...},
    "adaptive": {...}
  }
}
```

## Hyperparameters

All benchmarks use these fixed values (defined in `benchmarks/benchmark_esci.py` and Makefile targets):

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `fetch_k` | 40 | Retrieval candidate pool size (standard for ESCI benchmarks) |
| `alpha_hybrid` | 0.25 | Industry-standard BM25-dominant weighting (reference point) |
| `rerank_top_k` | 20 | Post-reranker list size (covers Recall@20 measurement) |
| `qg_threshold` | 0.45 | Quality gate max_score threshold (conservative, triggers retry ~20% of queries) |
| `alpha_shift` | ±0.3 | Quality gate retry magnitude (e.g., 0.25 → 0.55 or 0.25 → 0.0 when α > 0.5) |
| `locale` | "us" | US English queries only (test/small queries by default; see How to Run) |
| `hard_query_percentile` | 25th | Bottom-quartile NDCG@10 from standard-hybrid baseline |

## Results

### Last Run

**Date:** 2026-09-25 19:23 (local)  
**Stack:** 158,637-product corpus, `nomic-embed-text` via Ollama, cross-encoder reranker (#147/#148)  
**Mode:** `--fast` (deterministic, no LLM)  
**Query sample:** 5000 ESCI US test/small queries (fully judged in the corpus)  
**Retrieval failures:** 0  
**Hard-query count:** 1251 / 5000 (bottom-quartile NDCG@10 <= 0.1785)

```text
======================================================================
HARD-QUERY RESULTS (primary focus):
System                    NDCG@10         MRR             Recall@20
----------------------------------------------------------------------
Lexical (BM25)            0.0557 ±0.0949  0.2140 ±0.3185  0.1282 ±0.1769
Standard Hybrid           0.0456 ±0.0583  0.2222 ±0.3013  0.1504 ±0.1817  ← reference
Adaptive                  0.1011 ±0.1438  0.3307 ±0.3839  0.1504 ±0.1817

Δ vs Standard Hybrid (hard queries):
Lexical:                  NDCG@10 +22.1%  MRR -3.7%   Recall@20 -14.8%
Adaptive:                 NDCG@10 +121.6% MRR +48.8%  Recall@20 +0.0%
======================================================================
```

### Full-Set Results (Appendix)

```text
System                    NDCG@10  MRR     Recall@20  n
-------------------------------------------------------
Lexical (BM25)            0.3924   0.6483  0.3856     4993
Standard Hybrid           0.4506   0.7099  0.4431     5000
Adaptive                  0.4798   0.7432  0.4431     5000
```

**Not comparable to the pre-#147 run** (2026-04-30: 9,618-product random sample,
Gemini embeddings, first 5000 judged queries of any split; full-set adaptive
NDCG@10 0.3897). Different corpus, embedding model and query set.

## Methodology

### What Each System Does

#### Lexical floor (α=0.0)

- Pure BM25 retrieval (no semantic/vector component)
- k=20 candidates fetched and ranked by BM25 score
- No reranking
- Baseline for understanding lexical-only quality

#### Standard Hybrid (α=0.25)

- Hybrid search: 40% vector + 60% BM25 (RRF fusion with k=60)
- k=20 candidates ranked by hybrid score
- No reranking
- Reference point (standard production setting)

#### Adaptive (intent-driven α + reranker + quality gate)

- Intent → alpha mapping (fast-path table, deterministic)
- Hybrid search with intent-specific alpha
- Cross-encoder reranking: top-20 by model score
- Quality gate: if max_score < 0.45, retry with α ± 0.3 once
- Production configuration (all components active)

### Why This Comparison Is Fair

- All three use the same retrieval candidates (fetch_k=40)
- All three measure on the same metrics (NDCG@10, MRR, Recall@20)
- All three evaluated on the same 5000 queries with ground truth
- Lexical + Hybrid show the retrieval baseline
- Adaptive adds reranking and quality gate → shows cumulative improvement from each component

### Known Sources of Variance

1. **Query/product overlap:**  Query strings in `esci_judgments` are exact matches only (no fuzzy fallback). A small % of queries in the sampling may not have judgments; these are skipped.

2. **Native hybrid vs RRF fallback:** If the OpenSearch neural-search plugin is enabled, native hybrid uses static `[0.5, 0.5]` weights (alpha has no effect). The benchmark logs which path is active at startup.

3. **Intent classification mode:**
   - `--fast` mode: skips LLM intent classification, uses `alpha=0.65` for all `search`/`follow_up` queries (deterministic)
   - Full mode: calls the local LLM intent classifier (`LLM_MODEL` via Ollama; results vary by model version)

4. **Cross-encoder model:** Currently `cross-encoder/ms-marco-MiniLM-L-12-v2` (deterministic, cached locally after first load).

5. **ESCI data version:** Results depend on which parquet snapshot is used. If you re-clone the ESCI repo, ensure the `shopping_queries_dataset_*` files haven't changed significantly.

## Reproduction Checklist

- [ ] ESCI dataset cloned to `../esci/`
- [ ] Services running: `docker compose up -d`
- [ ] Products + judgments ingested: `bash scripts/lucille_ingest.sh` (Lucille ETL; the older standalone `ingest_esci_*.py` scripts were removed in PR #48)
- [ ] Verify OpenSearch: `curl http://localhost:9200/esci_judgments/_count`
- [ ] Dry-run: `python benchmarks/benchmark_esci.py --limit 2 --fast`
- [ ] Full run: `make benchmark-esci-fast` (~35 min)
- [ ] Results printed to stdout
- [ ] (Optional) Save JSON: `python benchmarks/benchmark_esci.py --limit 5000 --hard-only --fast --output results.json`

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError: No module named 'config'` | Missing PYTHONPATH | Run with `PYTHONPATH=.` prefix |
| `ConnectionError: Error connecting to OpenSearch` | Services not running | `docker compose up -d` from repo root |
| `lookup_judgments returned None (X queries skipped)` | Query not in esci_judgments index | Normal — exact-match only, some queries have no judgments |
| `CrossEncoderReranker warmup failed` | Model not downloaded | Model auto-downloads from HuggingFace on first run (~100MB) |
| `Cannot reach Ollama` / embed errors | Ollama not running or `nomic-embed-text` not pulled | Start Ollama; `ollama pull nomic-embed-text` (and `LLM_MODEL` for non-`--fast` mode) |
| Benchmark takes >30 min | Running on slow machine or full-set | Use `--limit 1000` to sample fewer queries |

## Sliding Scale: Query Count vs Runtime

- `--limit 5000`: ~35 minutes (Makefile default; measured 2026-09-25, M4 Max)
- Smaller limits scale roughly linearly (not individually re-measured since #148)
- No limit: all ~8,900 test/small queries

For development/testing, use `--limit 500`. For final slide deck numbers, use `--limit 5000` or higher.

## Contact

If results differ significantly from expected or you suspect the ESCI dataset has changed:

1. Confirm ESCI parquet files match amazon-science/esci-data main branch
2. Run with `--output results.json` and check the `timestamp` and commit hash
3. Document the variance (e.g., "run on commit XYZ vs YZX showed 1.2% NDCG@10 difference")
