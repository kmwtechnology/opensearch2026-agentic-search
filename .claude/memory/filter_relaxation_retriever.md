---
name: filter_relaxation_retriever
description: Attribute filter relaxation in retriever_node — drops multi_match filters and retries when < 3 results returned (PR #71)
metadata:
  type: project
---

When `attribute_filter` or `refinement` intent returns fewer than 3 docs after applying attribute filters, the retriever automatically retries with a relaxed filter set.

**What gets dropped:** `multi_match` filters (material_or_feature, size). Style words like "athletic" in "red shoes athletic" map to `material_or_feature` and can eliminate most of a small corpus.

**What's kept:** `match` filters (color: `product_color`, brand: `product_brand`) — the user explicitly named these, so they're treated as hard constraints.

**Trigger condition:** `len(results) < 3 AND multi_match filters present AND intent in (attribute_filter, refinement)`

**Conservatism:** relaxed results only replace original results if `len(relaxed_results) > len(results)`. If relaxation doesn't help, original (sparse) results are kept.

**Code location:** `main.py` retriever_node, after the ThreadPoolExecutor hybrid/BM25 fetch (~line 2555).

**Why:** Manual observability audit (issue #70) showed "red shoes athletic" → 2 results (track pants, hoodie). Root cause: `athletic` is a style hint, not a material, but `_extract_attributes` maps it to `material_or_feature` as the closest schema match.

**How to apply:** When debugging sparse attribute_filter results, check if material_or_feature extraction is over-constraining. The relaxation fires automatically but only rescues <3-result cases — if 3-5 results look wrong, the root cause may be the filter schema itself (see issue #5 for `product_type` dimension as a future fix).
