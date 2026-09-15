# CLAUDE.md

Guidance to Claude Code (claude.ai/code) when working with this repository.

## New Session Checklist

When a new work session begins (especially when picking up an issue, feature, or non-trivial fix), **suggest creating a feature branch before writing code**. Confirm `git status` is clean and `main` is up to date, then propose a branch name (e.g. `feat/issue-6-judge-categories`, `fix/citation-urls`). Do not start editing on `main`. Skip only for one-line typos or doc tweaks the user explicitly says to commit straight to `main`.

## Working Session Skills (`/workflow-start`, `/workflow-check`, `/workflow-deploy`)

**Project-level versions of these three skills live in `.claude/skills/` in this repo (added 2026-09-11) and take precedence over the global ones (`~/.claude/skills/`) when working here.** The global skills default to Nasuni/Hyrule's Jira/Slack world, which doesn't apply — the project skills are GitHub-native and verified against this repo's actual CI/deploy setup. Key facts they encode (verified against the live repo, not assumed):

| Fact | Reality |
|---|---|
| Ticket tracking | GitHub Issues (`kmwtechnology/opensearch2026-agentic-search`); `gh issue view <N>`; "done" = `state == CLOSED` |
| Branch name | `feat/issue-N-slug` / `fix/issue-N-slug` |
| Commit / PR | Reference issue in PR body (`Closes #N`); no commit prefix needed |
| **Local git hooks** | **`.git/hooks/pre-commit`** (installed by `scripts/setup.sh` from `scripts/pre-commit.sh`, added issue #99) runs black/isort/flake8 on staged `.py` files — blocks a badly-formatted commit before it happens. **`.git/hooks/pre-push` is still Git LFS's own hook only — no test/smoke gate exists there.** Run `make ci` / `make smoke-local-quick` by hand before pushing; nothing stops a push with failing tests except CI. |
| Local tests | `PYTHONPATH=. pytest tests/unit/`, `make ci`, `make smoke-local-quick` / `make smoke-local` |
| Deploy mechanism | **None — local-only as of issue #110 (2026-09-15).** The conference demo runs entirely from local Docker + `make dev`; there is no Cloud Run deploy anymore. `build-deploy.yml` (renamed from `build-deploy.yml`'s old `Build & Deploy` to `CI`) now runs only `unit-tests` + `integration-tests` + `lint-backend` + `frontend-tests` + `shellcheck` + a `notify` summary — the `build-docker`/`deploy-cloud-run` jobs were removed, and `.github/workflows/reindex.yml` / `smoke-tests.yml` were deleted outright (both existed only to act on the hosted Cloud Run/OpenSearch instance). The GCP resources themselves (Cloud Run service, Artifact Registry, WIF, Secret Manager) were **not** torn down — see issue #110 for what's explicitly out of scope. `langchain_agent/scripts/deploy.sh` / `gcp-init.sh` / `docs/operations/gcp-quickstart.md` are left in place as manual/reference tooling if GCP deploy is revisited, but are unused day-to-day now. |
| Merge | `gh pr merge --squash --delete-branch` — repo has `deleteBranchOnMerge: false`, so `--delete-branch` must be passed explicitly. No branch protection configured (private repo, requires GitHub Pro) — CI must be checked manually (`gh pr checks`) before merging, not assumed via `--auto` |
| Ready-for-review / deploy announcement | **Skip entirely** — no Slack channel configured for this project |
| Deploy-outcome close-out | `gh issue close <N> --comment "..."`; Obsidian tag `#opensearch2026-agentic-search` not `#nasuni` |

When skills say "load `mcp__atlassian-nasuni__*`" or "post to `#nasuni-int`," treat as inapplicable. Use GitHub equivalents instead.

## Project Overview

**Agentic Hybrid Search** — production-grade LangGraph RAG agent for Amazon ESCI e-commerce product search. Hybrid BM25 + vector retrieval with dynamic alpha per intent, reranking with quality gate, real-time WebSocket streaming. Deployed on GCP Cloud Run with Google Gemini.

## Pipeline

```text
Intent Classifier → Query Rewriter → Query Evaluator → Retriever → Reranker → Quality Gate → Agent
```

Six intent classes: `search`, `comparison`, `attribute_filter`, `refinement`, `follow_up`, `summary`. See `ARCHITECTURE.md` for node-by-node detail.

**Key nodes:**

- **Intent Classifier** — single structured-output LLM call (no keyword fast-path, despite older docs/comments — see #26). Confidence < 0.7 triggers clarification.
- **Query Rewriter** — resolves follow-up references using conversation history.
- **Query Evaluator** — sets `dynamic alpha` (0.0 for lexical exact matches, 1.0 for semantic/exploration).
- **Retriever** — hybrid vector + BM25 via RRF fusion (k=60); applies attribute filters for `attribute_filter` intent; filter relaxation if <3 results.
- **Reranker** — local cross-encoder by default (`RERANKER_TYPE=cross-encoder`), scores 0.0–1.0; sets `reranker_max_score`. An LLM-based reranker (`RERANKER_TYPE=gemini`) exists but isn't the shipped default.
- **Quality Gate** — intent-specific thresholds (comparison=0.55, search/follow_up=0.50, attribute_filter/refinement=0.45). Retries with adjusted alpha if below threshold.
- **Agent** — conversational response with citations. ESCI products cite via `https://www.amazon.com/s?k={title}` (robust against delisted ASINs).
- **LLM Judge** (post-agent, optional) — flags hallucinations; auto-correction retry for `fabrication` and `cross_product_bleed` categories only. **Reset `hallucination_retry_used=False` at top of every new user turn** (issue #83).

## Tech Stack

| Layer | Tech |
|-------|------|
| LLM (generation) | Gemini 3 Flash (preview) |
| LLM (classify/eval) | Gemini 3.1 Flash Lite (preview) |
| Reranker | Local cross-encoder (`ms-marco-MiniLM-L-12-v2`), not an LLM call |
| Embeddings | `models/gemini-embedding-001` (768-dim) |
| Agent framework | LangGraph + LangChain |
| Vector DB | OpenSearch 3.8.0 (HNSW knn + BM25) |
| Checkpoints | PostgreSQL 16 |
| API | FastAPI + WebSocket |
| Frontend | React 19 + TypeScript + Tailwind + Zustand |
| Deployment | GCP Cloud Run |

## Key Patterns

- **Bare imports & PYTHONPATH** — modules use `from config import ...`. All Python invocations from `langchain_agent/` need `PYTHONPATH=.` (pytest, main, custom scripts). Omitting causes `ModuleNotFoundError`.

- **Frontend origin detection** — Components with iframes/cross-domain requests should detect environment at runtime, not hardcode defaults. Pattern: (1) try `/api/config`, (2) if it returns `apiUrl`, use it, (3) else smart detection: localhost → `http://localhost:8000`, non-localhost → `window.location.origin`. See `SwaggerPage.tsx` (issue #28).

- **State access** — `CustomAgentState` is `total=False`; only `messages` guaranteed. Always `state.get("field", default)`. Each node adds specific fields: Classifier → `intent`, `confidence`, `user_query`; Query Evaluator → `alpha`, `intent_description`; Retriever → `retrieved_documents`, `pre_rerank_documents`, `bm25_documents`, `judgments`, `bm25_latency_ms`, `retriever_latency_ms`; Reranker → `reranker_max_score`, `reranked_documents`, `reranker_latency_ms`; Quality Gate → `quality_gate_retried`, `alpha_adjusted_value`, `quality_gate_threshold_used`.

- **Dual-analyzer BM25** (issue #69) — Dense vectors handle morphological recall ("running/runs/ran"). BM25 focuses precision. Primary fields use `light_english_analyzer` (kstem). Sub-fields (`.heavy`) use `heavy_english_analyzer` (snowball) at ^0.3 boost for recall fallback. Balances precision (Beats ≠ beat) with recall via .heavy + embeddings.

- **Hybrid search** — RRF fusion (k=60); `alpha` ∈ [0,1] weights lexical→semantic.

- **Attribute detection** — integrated into Lucille ETL via `AttributeDetectorStage`, one generic Java stage (`langchain_agent/lucille-esci/src/main/java`) parameterized per attribute type (color, material). Outputs `product_<type>_primary`/`_secondary` keyword fields. Taxonomy lives in OpenSearch, not a committed file — rules-based detection, auditable, no AI at ingest time. **A fresh cluster's taxonomy store is empty and nothing seeds it implicitly.** `./scripts/setup.sh` (via `setup.py`, PR #102, 2026-09-14) now runs `--seed-taxonomy` unconditionally on every first-time setup — this used to be a manual step nothing enforced, which meant a freshly set-up local environment had zero color/material coverage until someone happened to run `make seed-taxonomy` by hand (found live while running `DEMO.md`: every color/material `attribute_filter` query returned zero results). To manually re-seed later (e.g. after the store has drifted from rehearsals), use `make seed-taxonomy` locally or `seed_taxonomy=true` on `reindex.yml` (`lucille_ingest.sh --seed-taxonomy` — discovery between two products passes; destructive to agent-learned mappings). The stage uses Lucille's `OpenSearchUtils` client via the indexer's `opensearch` block and hard-fails the ingest if the lookup can't load — never soft-fail a store lookup in a custom stage (#72). `BrandNormalizerStage` handles brand separately (fixed transform).

- **Agentic taxonomy growth & correction** — the agent can grow *or fix* the live color/material taxonomy itself via one tool, `trigger_enrichment(attribute_type, variant, canonical)` (gated by `ENABLE_ENRICHMENT_TOOL`, default off), which writes the mapping to OpenSearch and triggers a real Lucille reindex through `pipeline/reindex_trigger.py` — `REINDEX_TRIGGER=local` (default) runs `scripts/lucille_ingest.sh` as a subprocess (~19–20s); `REINDEX_TRIGGER=github` (Cloud Run, which has no Docker) dispatches `reindex.yml` via a fine-grained PAT in `GITHUB_REINDEX_TOKEN`, fire-and-forget (~8 min) with the run URL in the tool reply. `make reindex[-products]` is the manual local entry point. Gap case: color's unresolved-term filter is hard (reliably triggers the gap signal live through chat); material's is soft + subject to filter relaxation (won't trigger via chat, only via `/api/admin/enrich`). Correction case (the live demo's centerpiece): a shopper disputes an existing wrong tag (e.g. shipped taxonomy bug `tan → yellow`, should be `brown`, affects 29 products) — `agent_node`'s `_detect_correction_signal` + `_try_correction_tool` catch dispute language on `refinement`/`follow_up` turns and call the same tool with the corrected canonical; `enrich_attribute` tracks this via `EnrichmentResult.corrected_from`. This case matters because the wrong result still **passes** the quality gate — invisible to any automated check. See `langchain_agent/ARCHITECTURE.md`'s "Taxonomy Growth & Correction" section and `langchain_agent/DEMO.md`.

- **Auth** — two layers:
  1. **Same-origin** (`origin_auth.py`) — allow-list of localhost ports + Cloud Run `*.run.app`. Disallowed Origin always 403s.
  2. **Shared-password session + admin token** (`session_auth.py`):
     - **Session**: `LOGIN_PASSWORD` env var. `POST /api/auth/login` sets HttpOnly + SameSite=Lax cookie (`ahs_session`). WS rejects with code **4401** on failure.
     - **Admin token** (automation): `ADMIN_TOKEN` env var (32+ chars). Use `X-Admin-Token` header. Constant-time comparison via `hmac.compare_digest`.
  - **Do NOT wire new routes through `verify_api_key`** — it doesn't exist (`api/middleware/auth.py` only holds `AuthConfigurationError`; importing it raises `ImportError`). Use `verify_same_origin` + `verify_session` (or `verify_admin_token` for automation).

- **Event sync** — `api/schemas/events.py` must stay in sync with `web/src/types/events.ts`. Each event's `node` field pins it to pipeline step. All return paths in `agent_node` must include `"citations"` key (empty list if no citations).

- **Langfuse tracing (LOCAL DEV ONLY, issue #18 Phase 1; made mandatory in local dev by issue #99/#100)** — a self-hosted Langfuse v4 stack (`docker compose --profile observability`) is now started automatically and unconditionally by `scripts/setup.sh`/`start.sh` (and their Makefile equivalents `make setup`/`make dev`) alongside PostgreSQL/OpenSearch — no manual step, no opt-in flag. `LANGFUSE_ENABLED=true` is likewise the default in `.env.example`/generated `.env`, and attaches a `langfuse.langchain.CallbackHandler` to every graph invocation via `integrations.get_callbacks()` (wired in `cli.py` and `api/services/observable_agent.py`). Zero GCP footprint by construction: the flag is never set in `build-deploy.yml`, and the SDK (plus the `langchain` meta-package it imports) lives only in `requirements-dev.txt` with lazy imports, so the prod image can't even fail on import — `tests/unit/test_langfuse_integration.py` asserts both. UI at `http://localhost:3000` (login `dev@example.com` / `localdev123`); API keys are pre-provisioned via `LANGFUSE_INIT_*` in `docker-compose.yml` and match the `core/config.py` defaults. `make langfuse-up`/`langfuse-down` still exist for managing just the Langfuse containers in isolation. Note: `.git/hooks/pre-commit` only runs black/isort/flake8 (see above) — it does not run `make smoke-local-quick`, so run that by hand when touching backend pipeline logic.
  - **Cost/latency dashboard (issue #56 Phase A)** — every trace now carries an `intent` CATEGORICAL score (`pipeline_nodes.intent_classifier_node`, alongside the existing `judge_verdict`/`*_latency_ms` scores). In the Langfuse UI, build a cost/latency-by-model/node/intent view under **Scores** (or **Traces → filter by score name**): filter/group by `intent`, cross-reference with the per-node `*_latency_ms` scores and the automatic per-generation cost/token columns (no custom code needed — these come free from the `CallbackHandler`). Save the filtered view for reuse.
  - **Eval/annotation workflows (issue #56 Phase B)** — `integrations/langfuse_eval.py` links the app's existing ESCI ground-truth judgments (`agent_state.judgments`, from `VectorStore.lookup_judgments`) into Langfuse's own primitives, not ad-hoc score calls: `sync_dataset_item` idempotently upserts each query's judgments as a **Dataset** item (`esci-ground-truth`, keyed by lowercased query); `record_citation_eval` scores `eval_citation_precision` opportunistically on every live traced request with ground truth for its query, and pushes it to the `low-confidence-citations` **Annotation Queue** (`queue_for_human_review`) when precision is below `LOW_PRECISION_THRESHOLD`. `make langfuse-eval` (`scripts/run_langfuse_eval.py`) runs a proper **Experiment** via `client.run_experiment()`, populating Datasets > Runs with a real, comparable-over-time run.
  - **Evaluators (`/evals`, issue #56 Phase B continued)** — `make register-langfuse-evaluators` (`scripts/register_langfuse_evaluator.py`) registers three real Langfuse Evaluators, each with an Evaluation Rule firing on both a standalone live trace (root span `LangGraph`) and an Experiment item (root span `experiment-item-run` — Langfuse only populates `experiment.itemExpectedOutput` on that top-level dataset-run-linked span, not on nested descendants, confirmed empirically): (1) `citation-precision-ts` — a genuine Code Evaluator, TypeScript source at `web/src/langfuse-evaluators/citationPrecision.ts` (type-checked + unit-tested via the web project's own `npm test`, then read verbatim and submitted as `source_code`), executed locally via the `insecure-local` dispatcher (`docker-compose.yml`'s `langfuse-worker` — local-only, no AWS Lambda, TypeScript/JavaScript only, "not a sandbox boundary for untrusted code" per Langfuse's own docs, acceptable here since every evaluator submitted is our own reviewed source, never third-party); (2)+(3) `answer-groundedness` and `context-precision` — Langfuse's own built-in LLM-as-judge templates (Retrieval category), prompt text captured verbatim from the template gallery UI (not reauthored), using the existing `google-ai-studio` LLM connection. These are independent, Langfuse-native cross-checks on exactly what `quality/judge.py` and `citation_precision()` already try to measure.
  - **Quality-gate threshold calibration (issue #56 Phase C)** — `make analyze-quality-gate` (`scripts/analyze_quality_gate_thresholds.py`) joins `reranker_max_score`, `intent`, and `eval_citation_precision` scores from Langfuse by trace_id and reports, per intent, whether the current `intent_thresholds` in `quality_gate_node` actually separate high- from low-precision responses. Read-only/informational by design — local dev trace volume is too small to safely auto-retune production thresholds; use its output as evidence for a manual threshold change, not an automated one.
- **Error hierarchy** — all custom exceptions inherit from `AgenticHybridSearchError`.

## Common Commands

All backend commands run from `langchain_agent/`. Bare imports require `PYTHONPATH=.`.

```bash
# LOCAL DEVELOPMENT STARTUP — Full Stack (Langchain + Langfuse) ⭐ STANDARD
# Langfuse is a mandatory, non-optional part of the local stack (issue #99/#100)
# — every entry point below (scripts/setup.sh, scripts/start.sh, make setup,
# make dev) brings up PostgreSQL + OpenSearch + Dashboards + the full Langfuse
# stack together automatically. There is no "minimal, Langfuse-off" variant
# and no manual `docker compose ... up -d` step needed first.
cd /path/to/opensearch2026-agentic-search/langchain_agent
./scripts/setup.sh                                            # First time: Docker+Langfuse, venv, DB/index init, ESCI ingest
./scripts/start.sh                                            # Every session: Docker+Langfuse (if not already up) + backend + frontend
# Equivalent Makefile path: `make setup` (first time) / `make dev` (every session)

# Access Points
#   Web UI: http://localhost:5173 (backend API at http://localhost:8000)
#   Langfuse: http://localhost:3000 (login: dev@example.com / localdev123)
#   OpenSearch Dashboards: http://localhost:5601
#   Backend API only: http://localhost:8000/api/*

# Stop (processes + Docker/Langfuse containers persist for a fast restart)
./scripts/stop.sh                                             # or: make stop

# Teardown (destructive — removes .venv, node_modules, ALL Docker volumes incl. Langfuse)
./scripts/teardown.sh                                         # or: make teardown

# ESCI ingestion via Lucille ETL
bash scripts/lucille_ingest.sh            # products + judgments, no API calls (default: Docker-based)
make seed-taxonomy                        # rediscover color/material taxonomy + products pass (DESTRUCTIVE; needed once per fresh cluster)

# Benchmarks (requires docker compose up -d)
make benchmark-esci-fast                  # ~5 min, deterministic (no LLM)
make benchmark-esci                       # ~10 min, full adaptive (requires GOOGLE_API_KEY)

# Tests (PYTHONPATH=. required)
PYTHONPATH=. pytest tests/unit/                      # ~0.5s, no services
PYTHONPATH=. pytest tests/integration/               # needs PostgreSQL + OpenSearch
PYTHONPATH=. pytest tests/e2e/                       # full system
PYTHONPATH=. pytest tests/ -m phase1                 # by marker
make ci                                  # black + isort + flake8 + mypy + unit + frontend

# Pre-commit/push gates (local-only, in .git/hooks/)
make smoke-local-quick                    # ~13s, search-intent smoke (run by hand — no hook triggers this)
make smoke-local                          # ~90s, full 20-test suite (run by hand — no hook triggers this)

# Frontend (from langchain_agent/web/)
npm install && npm run dev                # :5173, proxies API to :8000
npm run lint && npm run test              # Vitest, 101+ tests

# Deployment — no manual script; push to main triggers build-deploy.yml's
# deploy-cloud-run job automatically (gated on build-docker + all test/lint jobs)
git push origin main
gh workflow run smoke-tests.yml -f service_url=<CLOUD_RUN_URL>   # post-deploy verification
```

## Repository Maintenance (2026-09-11)

**Cruft audit completed.** The repository was audited and cleaned:

| Removed | Reason |
|---------|--------|
| `.github/modernize/` (13 MB) | AWS assessment artifacts; one-time run, zero references |
| `.vscode/` | IDE config, gitignored, no shared value |
| `scripts/` (root) | Empty directory after deprecated script removal |
| `scripts/analyze_color_attributes.py` | Retired (attribute detection moved to Lucille ETL) |
| `langchain_agent/lucille-esci/conf/color_mappings.json` | Generated by retired script, no references |
| `.markdownlint.json`, `.markdownlintignore` | Unused configuration; never wired into CI or package.json |
| `.dockerignore` entries (3 lines) | `.vscode/`, `scripts/`, `tests/` — now nonexistent or local-only |
| `.gitignore` entries (29 lines) | Framework templates for unused tools (tox, nox, Django, Flask, Scrapy, Celery, SageMath, Sphinx, mkdocs) |

**Docs fixed:**
- `docs/operations/deployment.md` — removed false reference to non-existent `./scripts/deploy.sh`
- `docs/contributing/pr-process.md` — added deprecation notice, directed to CLAUDE.md for authoritative workflow
- `CLAUDE.md` — corrected false claim that deploy scripts don't exist; clarified automated vs. manual deployment

**Result:** Repository is clean, accurate, and free of dead code. Future sessions can assume no stale cruft.

## Reference Docs

Detailed information is stored in home directory memory. To view current notes on recent fixes, architecture decisions, or troubleshooting, check the memory index at:

```
~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md
```

CLAUDE.md stays concise; memory files capture ongoing decisions, known gotchas, and project context that would otherwise rot in a checked-in document.
