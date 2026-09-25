# Agentic Hybrid Search — Application Manual

*A local-only conversational RAG agent for Amazon ESCI e-commerce product search.*

This manual was compiled from the project's README, ARCHITECTURE, DEMO, CONTRIBUTING, and integration docs. Where source documents disagreed with each other or with the project's current state, the discrepancy is called out inline with a **⚠️ DRIFT** note, and all of them are also summarized in [Appendix A](#appendix-a-known-documentation-drift) so you can find them at a glance.

## Table of Contents

1. [Overview & What This Is](#overview--what-this-is)
2. [Installation & Setup](#installation--setup)
3. [Using the App: Demo Walkthrough](#using-the-app-demo-walkthrough)
4. [Architecture Deep Dive](#architecture-deep-dive)
5. [API & WebSocket Reference](#api--websocket-reference)
6. [Frontend / Web UI](#frontend--web-ui)
7. [Testing & Benchmarks](#testing--benchmarks)
8. [Contributing & Dev Workflow](#contributing--dev-workflow)
9. [Data & ESCI Ingestion](#data--esci-ingestion)
10. [Appendix A: Known Documentation Drift](#appendix-a-known-documentation-drift)

---

## Overview & What This Is

Agentic Hybrid Search is a production-grade conversational RAG agent for e-commerce product discovery. It connects shoppers to the right products through multi-turn dialogue, built on the Amazon ESCI (Shopping Queries Dataset) with 1.8M+ real products and relevance judgments from actual search sessions.

The core problem it solves: finding products when a shopper's intent is clear but their query isn't. A shopper might say "blue running shoes, size 10, under $100" — this involves both precise product attributes and semantic understanding of category and use case. Agentic Hybrid Search handles both by combining lexical and semantic search, reranking results, and maintaining conversation context across turns (so "make them waterproof" narrows the prior results rather than starting over).

### How It Works (The Pipeline, in Plain Terms)

When you ask a question, the pipeline routes your intent (is this a search, a comparison, filtering for attributes, refining a prior result?) and then runs these stages in sequence:

1. **Hybrid search** — simultaneously queries via BM25 (exact keyword matching) and 768-dimensional vector embeddings (semantic meaning). Results are fused via Reciprocal Rank Fusion to balance lexical precision with semantic understanding.

2. **Reranking** — takes the top candidates and scores them with a cross-encoder model to measure query-product relevance on a 0.0–1.0 scale. This stage is fast (runs locally, no API calls) and cuts the results down to the most relevant.

3. **Quality gate** — if the top-scored result is too low-confidence, the pipeline adjusts its lexical/semantic balance and retries once, widening the search pool to prevent empty results.

4. **Real-time streaming** — your response appears token-by-token over WebSocket, not all at once.

5. **Agentic taxonomy self-correction** — the agent can learn new product attributes (colors, waterproofing requirements) on the fly when shoppers teach it. If the taxonomy has the wrong mapping (e.g., "tan" incorrectly tagged as "yellow"), a shopper can dispute it in chat and trigger a live fix.

### Tech Stack

| Layer | Technology |
| --- | --- |
| **LLM (all chat calls)** | `qwen3.6:35b-a3b-q4_K_M` via local Ollama |
| **Embeddings** | `nomic-embed-text` via local Ollama (768-dim) |
| **Document Reranking** | `ms-marco-MiniLM-L-12-v2` (cross-encoder, local, ~2s/40-doc batch) |
| **Vector Database** | OpenSearch 3.8.0 (HNSW + BM25) |
| **Checkpoints** | PostgreSQL 18 (LangGraph state persistence) |
| **Agent Framework** | LangGraph + LangChain |
| **Backend API** | FastAPI + WebSocket |
| **Frontend** | React 19 + TypeScript + Tailwind + Zustand |
| **Deployment** | Local only (Docker Compose) |

### Running It: Local Demo Tool

This app is a **local-only demo**, not a cloud service. You run it entirely on your machine via Docker and shell scripts.

**Prerequisites:**

- [Ollama](https://ollama.com/) installed and running locally — no cloud API key
- Docker Desktop
- Python 3.14+
- Node.js 24+
- Disk space for the ESCI corpus, Docker volumes, and Ollama models (~23 GB)

**Setup and run:**

```bash
cd langchain_agent
cp .env.example .env
./scripts/setup.sh    # One-time: pulls Ollama models, sets up Docker, database, and the full ESCI corpus (~35-40 min on an M4 Max)
./scripts/start.sh    # Starts backend (:8000) and frontend (:5173)
```

Open <http://localhost:5173> and start chatting. The backend runs locally; there is no network request to a remote server — the LLM and embeddings run through a local Ollama server.

Stop or clean up with:

```bash
./scripts/stop.sh           # Stop services, keep data
./scripts/teardown.sh       # Full cleanup: removes volumes, .venv, node_modules
```

### What This Is Not

There is **no CI pipeline and no deploy mechanism** (GitHub Actions were removed; see issue #113). There is **no cloud deployment path** (issue #110). The app exists to demonstrate the architecture and provide a hands-on testbed for intent routing, hybrid search, and agentic taxonomy correction — not as a production service.

The only gate before pushing code to `main` is running `make check` locally on your machine. Every developer commits directly to `main` in "cowboy mode" (no feature branches or pull requests required by default).

---

## Installation & Setup

This chapter walks you through getting Agentic Hybrid Search running on your machine for the first time, and the daily lifecycle commands you'll use every session thereafter.

### Prerequisites

You'll need several tools installed before setup begins. Here's what each does and how to verify you have it:

| Tool | Min Version | Purpose | Verify |
| ------ | ------------- | --------- | -------- |
| **Docker Desktop** | 4.x | Runs PostgreSQL + OpenSearch containers locally | `docker --version` |
| **Python** | 3.14+ | Backend virtual environment | `python3 --version` |
| **Node.js** | 24+ | React frontend and Vite dev server | `node --version` |
| **Java** | 21+ | Lucille ETL for product ingestion (only needed if `LUCILLE_USE_DOCKER=false`) | `java -version` |
| **Maven** | 3.8+ | Build tool for Lucille ETL (only needed if `LUCILLE_USE_DOCKER=false`) | `mvn --version` |
| **Ollama** | — | Local LLM (`qwen3.6:35b-a3b-q4_K_M`) and embeddings (`nomic-embed-text`); no cloud API key | Get from [ollama.com](https://ollama.com/) |

#### Installing Prerequisites on macOS

Using Homebrew:

```bash
brew install docker
brew install python@3.14
brew install node
brew install ollama
brew install openjdk@21  # only needed for LUCILLE_USE_DOCKER=false
brew install maven       # only needed for LUCILLE_USE_DOCKER=false
```

#### Installing Prerequisites on Ubuntu/Debian

```bash
# Docker: https://docs.docker.com/engine/install/ubuntu/
sudo apt-get install docker.io
sudo usermod -aG docker $USER

# Python 3.14+ (may need deadsnakes PPA)
python3 --version

# Node 24+ (may require NodeSource repo)
sudo apt-get install npm nodejs

# Java
sudo apt-get install openjdk-21-jdk

# Maven
sudo apt-get install maven
```

#### Installing Prerequisites on Windows

- **Docker Desktop**: <https://www.docker.com/products/docker-desktop>
- **Python 3.14+**: <https://www.python.org/downloads/>
- **Node.js 24+**: <https://nodejs.org/> (use LTS)
- **Java 21+**: <https://www.oracle.com/java/technologies/downloads/>
- **Maven**: <https://maven.apache.org/download.cgi>

### One-Time Setup (~35-40 minutes plus the Ollama model download)

#### Step 1: Clone the Repository

```bash
git clone https://github.com/kmwtechnology/opensearch2026-agentic-search.git
cd opensearch2026-agentic-search/langchain_agent
```

All commands in this chapter run from the `langchain_agent/` directory.

#### Step 2: Configure Your Environment

No cloud API key is needed — everything runs against a local Ollama server:

```bash
cp .env.example .env
```

`./scripts/setup.sh` (below) checks that Ollama is installed and running,
and pulls any missing models automatically.

#### Step 3: Run One-Time Setup

From `langchain_agent/`:

```bash
./scripts/setup.sh
```

This script initializes everything in six phases:

| Phase | What Happens | Time |
| ------- | -------------- | ------ |
| 1: Prereq Checks | Verifies Docker, Python, Node, Ollama (installed + running) | instant |
| 2: Ollama models | Pulls any missing Ollama models (~23 GB) | varies |
| 3: Python venv | Creates `.venv` and installs backend dependencies | 3–5 min |
| 4: Node deps | Installs frontend packages (npm install) | 1–2 min |
| 5: Docker up | Starts PostgreSQL and OpenSearch containers | ~30 sec |
| 6: Ingest | Initializes the database and indexes the full ESCI product corpus (158,637 products) via Lucille + Ollama embedding | ~35-40 min |

When setup completes, it prints the app URLs. There is no login gate — the app is immediately accessible.

#### Step 4: Verify the Setup

```bash
make doctor
```

This checks that Docker, services, and dependencies are healthy. You should see "All checks passed ✓".

### Your First Run

After setup completes, start the development servers:

```bash
./scripts/start.sh
```

This command blocks in the foreground (both backend and frontend run in the foreground). Watch for these readiness signals in the terminal output:

- **Backend ready**: `Uvicorn running on http://127.0.0.1:8000` (port is bound), then `Application startup complete` (LLM, embeddings, reranker, and vector store are initialized — this is the real "ready for requests" signal)
- **Frontend ready**: `VITE vX ready in Yms`

Once you see both signals, open <http://localhost:5173> in your browser. Try a search like "Find wireless headphones under $100" — you'll go straight to the app with no login step.

### The Every-Session Lifecycle

#### Starting Local Development

You have three ways to start the servers, depending on your situation:

**Most common — start everything fresh:**

```bash
./scripts/start.sh
```

This starts Docker containers (PostgreSQL and OpenSearch), the backend server (:8000), and the frontend dev server (:5173), all in one command. It blocks in the foreground — you can watch the logs to see startup progress, or open another terminal tab for coding. Both backend and frontend reload on file changes (uvicorn --reload and Vite HMR).

**If Docker is already running:**

```bash
make dev
```

This is faster — it skips Docker startup and launches just the backend and frontend servers.

**Running servers independently (in separate terminals):**

```bash
make dev-api     # Backend only (:8000)
make dev-web     # Frontend only (:5173, from langchain_agent/web/)
```

#### Stopping Local Development

**Pause development (data stays):**

```bash
./scripts/stop.sh
```

This kills the backend and frontend processes. Docker containers stay running, so your PostgreSQL database and OpenSearch index persist. Use this when you're done for the day but want to resume tomorrow — you can run `./scripts/start.sh` again to pick up where you left off.

**Full teardown (DESTRUCTIVE):**

```bash
./scripts/teardown.sh
```

⚠️ **This is destructive and runs without prompting.** It removes:

- Docker containers and all volumes (PostgreSQL database and OpenSearch index are permanently deleted)
- `.venv` directory
- `web/node_modules` directory
- All logs

Use this only if you want a completely clean slate. You'll need to run `./scripts/setup.sh` again (~35-40 minutes) to rebuild everything.

**Critical distinction:**

- `stop.sh` = pause (kill processes only; data survives; resumable with `start.sh`)
- `teardown.sh` = destroy (delete everything; requires full `setup.sh` to rebuild)

#### Understanding Service States

This table shows what's running at each point:

| State | Services | Docker | PostgreSQL | OpenSearch | What to Do Next |
| ------- | ---------- | -------- | ------------ | ----------- | ----------------- |
| **Fresh clone** | None | Off | ❌ None | ❌ None | Run `./scripts/setup.sh` |
| **Dev session running** | Backend + Frontend | On | ✅ Active | ✅ Active | Edit code, run tests |
| **Paused** | None | On | ✅ Data kept | ✅ Index kept | Run `./scripts/start.sh` to resume |
| **Torn down** | None | Off | ❌ Deleted | ❌ Deleted | Run `./scripts/setup.sh` to rebuild |

### Important Gotcha: PYTHONPATH

All backend Python commands from the `langchain_agent/` directory require the `PYTHONPATH=.` environment variable:

**Correct:**

```bash
PYTHONPATH=. pytest tests/unit/
PYTHONPATH=. python main.py
```

**Wrong (causes ModuleNotFoundError: No module named 'config'):**

```bash
pytest tests/unit/
python main.py
```

**Why?** The backend imports relative to `langchain_agent/` (e.g., `from config import ...`). Without `PYTHONPATH=.`, Python doesn't know where to find the config module.

**Good news:** The Makefile handles this automatically, so these commands work without the prefix:

```bash
make lint
make ci
make test
make check
make smoke
```

For ad-hoc Python commands, remember to set `PYTHONPATH=.`.

### Re-ingesting ESCI Data

If you need to refresh the product index (after downloading a new data sample, or as part of troubleshooting), from `langchain_agent/`:

```bash
bash scripts/lucille_ingest.sh
```

To rebuild the color attribute taxonomy from scratch (one-time per fresh cluster, or to reset color to seed state) — this deliberately does NOT touch "waterproof", which starts with zero seed variants and is grown entirely by the live enrichment flywheel:

```bash
make seed-taxonomy
```

⚠️ **This is destructive** — it deletes any agent-learned attribute mappings. The `scripts/setup.sh` runs this automatically on first-time setup.

### Common Issues & Troubleshooting

#### "ModuleNotFoundError: No module named 'config'"

You're running a Python command without `PYTHONPATH=.`.

**Fix:**

```bash
export PYTHONPATH=.
# Or prefix each command:
PYTHONPATH=. pytest tests/unit/
```

#### "Docker daemon is not running"

Docker is installed but not started.

**Fix:** Open Docker Desktop and wait for the whale icon to appear in your menu bar. Then retry `./scripts/start.sh`.

#### "Address already in use" or "Port 8000 already in use"

A leftover backend process from a previous run is still listening on port 8000.

**Fix:**

```bash
./scripts/stop.sh
./scripts/start.sh
```

Or manually kill the process:

```bash
lsof -i :8000
kill -9 <PID>
```

#### "Port 5432 already in use" (PostgreSQL)

You have a local PostgreSQL running outside of Docker.

**Fix:** Either stop the local Postgres or change the port in `.env`:

```bash
# Stop local Postgres (macOS)
brew services stop postgresql

# Or use a different port in .env
POSTGRES_PORT=5433
```

#### "Port 5173 already in use" (frontend)

A leftover frontend dev server from a previous run.

**Fix:**

```bash
./scripts/stop.sh
./scripts/start.sh
```

#### "setup.sh fails at Lucille ETL step"

Java or Maven is not installed or not in your PATH.

**Fix:**

```bash
brew install openjdk@21
brew install maven
# Then re-run:
./scripts/setup.sh
```

#### "OpenSearch returns 0 results"

The Lucille ETL ingest failed or was skipped.

**Fix:** Re-run the ingest:

```bash
cd langchain_agent
bash scripts/lucille_ingest.sh --reset-index
```

Wait 5–10 seconds, then try a search again.

#### "Frontend can't reach the backend"

The backend isn't running or didn't finish initializing.

**Fix:** Check the backend logs:

```bash
curl http://localhost:8000/api/health
./scripts/logs.sh backend
```

Look for `Application startup complete` in the logs. If you don't see it, the backend is still initializing or failed to start.

#### ".venv is broken (pip errors)"

Sometimes the virtual environment gets corrupted.

**Fix:**

```bash
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

Then run `make dev` to start the servers.

---

## Using the App: Demo Walkthrough

The app runs as a scripted demo, not as a free-form search tool. Four demos (selectable from a dropdown) walk you through the agent's core capabilities: two main story arcs (search refinement, then data-error correction), plus two optional bonus scenes (real relevance judgments, and schema evolution — growing an attribute that never existed rather than fixing a wrong one). Everything is driven by the **Next** button in the header—you never type a query by hand. ⚠️ **DRIFT NOTE**: an earlier revision of this chapter covered only three of the four demos and omitted "Schema Evolution" entirely; see that new section below.

### Before You Start

Open the app at `http://localhost:5173`. There is no login screen.

Verify the three services are healthy:

```bash
curl -sf localhost:9200 >/dev/null && echo "opensearch ok"
curl -sf localhost:8000/api/config >/dev/null && echo "backend ok"
curl -sf localhost:5173 >/dev/null && echo "frontend ok"
```

Display the app at 1920x1080 or larger, fullscreen. The browser chrome takes roughly 180px of height.

### Understanding the Interface

The header reads **"Next up · Turn N of M"** and names the query the button will send. On the right side, a narration panel shows one line per pipeline stage—intent classification, query rewriting, OpenSearch retrieval, reranking, quality assessment, and final response. Two gauges appear below:

- **alpha**: positioned between "exact words" (left) and "meaning" (right). Shows how literally the system is interpreting your question.
- **quality bar**: the best match's relevance score against the threshold it had to clear. Filled green when it passed, red when the gate had to retry with adjusted settings.

Wait for each turn to finish before clicking **Next**. Clicking ahead queues the message and its reply will land after the following question, which looks like an answer attached to the wrong query.

### Arc 1 — The Shopper (Three Turns)

One person, one conversation, narrowing the way people actually shop. Alpha moves from lexical-heavy (0.25) through balanced (0.35) to semantic-heavy (0.70) as the questions become less literal. Nothing contradicts an earlier turn.

#### Turn 1: Show me blue running shoes

Two words are real indexed attributes. The filter line shows `color: blue, feature: running` and alpha sits left of center—there is something concrete to match, so exact words carry more weight. Score: 0.97 against a threshold of 0.45 (passes cleanly).

Watch the query rewriter line: it pulls indexed field names directly from the question, not from fuzzy keyword matching. The result list pins to products with both attributes.

#### Turn 2: only size 10

A third filter appears (`+ feature: 10`) and the results stay pinned to the products from turn 1. The reply says so itself: *"From the 10 products I showed you earlier."* The system narrowed rather than searched again. Alpha is now 0.35—still concrete enough that exact words matter, but slightly more semantic weight than before. Score: 0.95.

#### Turn 3: what about trail running?

Four words with no subject, colour, or size. Watch the **Query Rewriter** line: it turns this vague question into *"Show me blue trail running shoes in size 10,"* carrying both earlier constraints forward automatically. Alpha jumps to 0.70 because this question is about purpose (trail running) rather than literal attributes—the system is now reading for intent, not keywords. Score: 0.998.

The question itself contains none of the earlier constraints. The conversation supplied them.

### Arc 2 — The Developer (Three Turns)

A different person: the developer who owns this catalog. Arc 1 showed the agent improving how it *searches*. Arc 2 shows it repairing the *data*.

#### Turn 1: show me tan boots

The filter resolves `tan` to **`color: yellow`**. This is a real shipped mis-mapping affecting every product the catalog lists as Tan.

Pause here. The result *passes* the quality gate—0.56 against a bar of 0.45. Nothing is broken by any metric the system tracks. The boots really are relevant to "tan boots" in every respect except the colour bucket they are filed under. No automated check catches a wrong-but-confident result.

The agent flags it anyway in prose: *"listed as Tan but indexed as yellow, which looks like a tagging error."*

#### Turn 2: that's not tan, that's tagged yellow which is wrong

Use this phrasing. `"that's not"` is what trips the correction detector.

The system detects a correction, a second model approves the change, and a *scoped re-tag* runs live — `pipeline/scoped_retag.py` re-checks only the products whose text mentions "tan" and re-detects their color, rather than reindexing the whole catalog. The elapsed counter ticks briefly; measured live, it re-checks 905 products and re-tags 679 in under a second.

It ends on **"Correction applied"** with the proof:

```text
✗ WAS   tan → yellow
✓ NOW   tan → brown
```

#### Turn 3: show me tan boots (new conversation)

Same question. The filter now reads **`color: brown`**.

The field changing is the proof—not the product list, which looks much the same. The fix is in the data, permanent, for every future shopper. The closing beat is what the agent *stops* saying: in turn 1 it volunteered a tagging error; here it says nothing, because there is nothing left to flag.

### Bonus — Real Relevance Judgments (Optional)

If there is time, select **"Bonus: Proving It With Real Judgments"** from the demo dropdown and run the single turn:

**Query: `sewing machine`**

This query exists in Amazon's ESCI benchmark with actual human relevance judgments. Watch the Pipeline Quality Summary switch from the system's internal confidence proxy to real numbers:

**stock BM25 NDCG@10 0.81 → BM25 0.91 → hybrid 0.95 → reranked 0.92**, against 3 human judgments from Amazon's ESCI dataset—not this system's own scoring.

This is the concrete version of the claim both arcs make in passing: hybrid retrieval plus reranking beat plain lexical search. Here it is measured against external, academic ground truth instead of the system grading its own homework. Note that only 3 products are judged for this query—the demo corpus has sparse judgments (~1 judged product per query on average). The point is that the number is real, not that it is large.

### Bonus — Data Enrichment: Schema Evolution (Optional)

Select **"Data Enrichment: Schema Evolution"** from the demo dropdown to see the taxonomy-growth machinery's other shape: not correcting a wrong mapping (that's Arc 2), but growing a filter dimension — `waterproof` — that doesn't exist in the catalog at all yet. Unlike Arc 2, no shopper has to dispute anything; the fix fires automatically the moment a hard attribute filter returns zero results.

**Turn 1: `Show me waterproof boots`** — On a freshly-armed cluster this returns zero results: `product_waterproof_primary` is genuinely unindexed (the `WATERPROOF_CANONICALS` taxonomy ships with a registered bucket but zero seed variants, on purpose). Watch the agent notice the gap and propose growing the taxonomy itself, unprompted — `trigger_enrichment` fires, a second model approves it, and a scoped re-tag runs live, the same elapsed-counter card as Arc 2's correction — measured live, it tagged 7,441 products in about 8 seconds.

**Turn 2: `Show me waterproof boots` (new conversation)** — Same query, new session. The filter now reads `product_waterproof_primary: "waterproof"` across the full catalog — that field existing at all is the proof, permanent for every future shopper.

This demo needs re-arming before it can run again (like Arc 2, it consumes a data gap) — the UI re-arms it automatically when selected. It also requires `ENABLE_ENRICHMENT_TOOL=true`, which is already set in this repo's local `.env`.

### What the System Is Doing

These turns across all four demos (nine total: three + one + three + two) are fully scripted and reproducible. The agent is not exploring novel queries; it is demonstrating its internal mechanics:

- **Intent classification** (one LLM call) picks between six classes: `search`, `comparison`, `attribute_filter`, `refinement`, `follow_up`, or `summary`.
- **Dynamic alpha** adjusts the hybrid retrieval balance between keyword (BM25) and semantic (vector) based on intent—lexical when the question names specific attributes, semantic when it names purposes or abstract qualities.
- **Query rewriting** resolves pronouns and comparatives against conversation history (`"what about trail running?"` → `"Show me blue trail running shoes in size 10"`).
- **Hybrid retrieval** fuses BM25 and vector search via reciprocal rank fusion; no manual tuning per query.
- **Cross-encoder reranking** rescores the top 40 candidates; a local model, not an LLM call.
- **Quality gate** checks if the best result exceeds a threshold; if not, the system adjusts alpha wider and retrieves 4x more candidates, then retries reranking.
- **Correction detection** catches phrases like `"that's not"` and routes them to a model-approved enrichment tool that rewrites the taxonomy and triggers a real re-ingest.
- **Taxonomy growth** (unprompted, unlike correction) fires automatically when a hard attribute filter returns zero results — the agent proposes growing the taxonomy itself via the same `trigger_enrichment` tool, a second model approves it, and a real re-ingest runs live.

### Models and Performance

**Generation, classification, evaluation, judging:** `qwen3.6:35b-a3b-q4_K_M` via a local Ollama server — no cloud API key. **Embeddings:** `nomic-embed-text` via Ollama (768-dim). **Reranking:** local cross-encoder (`ms-marco-MiniLM-L-12-v2`), no LLM call.

Typical latency: intent classification 10–500ms, query evaluation 10–500ms, retrieval 200–500ms, reranking 1–2s, agent response 3–8s. Roughly 6–15s per turn; the agent generation step dominates.

### What Not to Claim

- **Never mention price, cost, or budget.** The catalog has no price field. The agent is instructed to refuse and redirect. An invented dollar figure is the worst thing this demo could show.
- **Do not say dynamic alpha makes results better.** It provably changes the ranking, but it changes how the system reads the question, not the quality of the results. At α 0.25, a pure-semantic run of "blue running shoes" includes blue jeans; the reranker removes them. **The reranker** is what improves quality, not alpha.
- **Do not promise the quality gate recovers after failure.** Arc 2 turn 2 does fire the gate and retry, and the retry fails—the narrator reads "Still under the bar after retrying—0.30 against 0.45." The shopper's complaint is not a product query, so there is nothing in the catalog that scores well against it. The agent answers by fixing the data instead of by searching harder. That 0.30 is the ceiling for a uniformly irrelevant batch, not a coincidence. No turn in either arc recovers after a failed gate.
- **Do not promise a reshuffled product list in Arc 2 turn 3.** The honest proof is the filter value changing from yellow to brown.

### If Something Goes Wrong

| Symptom | Fix |
| --- | --- |
| Arc 2 turn 1 shows no mismatch | The index is already corrected. Click **Restart**, or run `make demo-reset` from `langchain_agent/`. |
| Schema Evolution turn 1 already shows results | The taxonomy is already grown from a prior run. Re-arm it (the UI does this automatically on selecting the demo) or run `make demo-reset`. |
| Schema Evolution turn 1 doesn't call `trigger_enrichment` | The model declined the tool call this run (a single-shot LLM decision). Re-run the turn or the whole demo. |
| Next is disabled, reads "Connecting…" | The socket is not open yet. It enables itself; do not click through. |
| A reply looks attached to the wrong question | You clicked ahead. Click **Restart** and let each turn finish before clicking Next. |
| Backend slow or timing out | The first query after a cold start pays model warm-up overhead. Send one throwaway query before the audience arrives. |

---

## Architecture Deep Dive

The Agentic Hybrid Search system is built as a LangGraph state machine that orchestrates an eight-node retrieval and generation pipeline. This chapter walks you through how the agent classifies queries, retrieves products, detects hallucinations, and even grows its own taxonomy at runtime.

### The Pipeline Graph

The core logic runs as a `StateGraph(CustomAgentState)` — a directed acyclic graph (DAG) of nodes and edges that processes one user query through eight nodes: `intent_classifier`, `query_evaluator`, `summary`, `retriever`, `reranker`, `quality_gate`, `agent`, and `llm_judge`. Each node is an async function that reads state, performs its task, and returns updated state fields. ⚠️ **DRIFT NOTE**: an earlier revision of this diagram omitted the `summary` node's branch entirely and miscounted the pipeline as seven stages — corrected below.

Routing out of the Intent Classifier is by **intent class**, not a raw confidence cutoff: a `summary` intent routes to the dedicated `summary` node; a low-confidence classification of any other intent routes to the Agent for clarification; everything else proceeds to the Query Evaluator.

```text
Intent Classifier ──┬──(summary)───► Summary ──┬──(done)─────► Agent (Generate Response)
                    │                          └──(continue)─► Retriever (Hybrid)
                    ├──(clarify, low confidence)──────────────► Agent (clarify)
                    └──(other)───────────────────────────────► Query Evaluator
                                                                        │
                                                                        ▼
                                                                Retriever (Hybrid)
                                                                        │
                                                    ┌───────────────────┼───────────────────┐
                                                    ▼                   ▼                   ▼
                                            Vector Search        BM25 Lexical         RRF Fusion
                                                    │                   │                   │
                                                    └───────────────────┼───────────────────┘
                                                                        ▼
                                                                Reranker (Cross-Encoder)
                                                                        │
                                                                        ▼
                                                                Quality Gate
                                                                /               \
                                                        (continue)          (retry)
                                                            │                   │
                                                            │                   └──► back to Retriever
                                                            ▼
                                                    Agent (Generate Response)
                                                            │
                                                            ▼
                                                    LLM Judge (optional)
                                                            │
                                                            ▼
                                                    Checkpoint & Emit
```

Each stage is independent and testable. The graph reads from PostgreSQL checkpoints to resume long conversations, and writes back after every turn.

### Intent Classifier: Routing the Conversation

The first node classifies every user message into one of six intents via a single structured-output LLM call. There is no keyword-based fast-path; every query pays this round-trip. Confidence scores below 0.7 are downgraded to clarification requests instead of proceeding to retrieval.

The six intents are:

- **search** — Open-ended product discovery ("find me wireless headphones under $200")
- **comparison** — Direct product comparison ("Sony vs Bose noise canceling")
- **attribute_filter** — Filtered search with explicit constraints ("blue running shoes size 10")
- **refinement** — Narrowing prior results ("make them waterproof")
- **follow_up** — Vague continuation or request for more ("the next one?", "how much does it cost?")
- **summary** — Retrospective or conversational recap ("what did we look at?")

**Output state fields:**

- `intent` — detected intent class
- `intent_confidence` — 0.0–1.0 score
- `user_query` — cleaned query text
- `reasoning` — brief explanation of the classification

The node also emits an `IntentClassificationEvent` for real-time UI visualization.

### Summary Node: Conversation Recaps

When intent is `summary`, the graph routes straight here, skipping the Query Evaluator entirely. The node generates a plain-language recap of the conversation so far (`summary_text`) and short-circuits to the Agent — no retrieval runs for a summary turn, since there's nothing new to search for. For any other intent this node is a pass-through the graph never actually reaches (routing sends non-summary intents to the Query Evaluator instead).

### Query Evaluator: Tuning the Retrieval Alpha

The Query Evaluator assigns an alpha (α) value that controls how much the retriever weights semantic (vector) versus lexical (BM25) search. α ranges from 0.0 (pure BM25) to 1.0 (pure vector).

**Fast-path assignment** for intent-specific categories:

- `comparison` → α = 0.60 (semantically heavy; needs conceptual matching like "best value" vs "premium sound")
- `attribute_filter` → α = 0.25 (lexically heavy; exact attributes like "blue" need exact matching)
- `refinement` → α = 0.35 (lexically heavy; constraining prior results favors exact term matching)

**LLM-path assignment** for `search` and `follow_up`, where a single LLM call evaluates the query type and assigns α dynamically. This allows the system to handle ambiguous queries like "budget runner shoes" (could be semantic or lexical) by asking the model itself.

**Query expansion** resolves pronouns ("does it fit?"), comparatives ("which is cheaper?"), and short questions ("how much?") using conversation history, but skips expansion for queries with specific brand or product names to avoid over-expansion.

**Output state fields:**

- `alpha` — 0.0–1.0 weighting for hybrid search
- `query_analysis` — explanation of the choice

The node emits `QueryEvaluationEvent` with the assigned α and expanded query if applicable.

### Retriever: Hybrid Search with Vector + BM25

The Retriever is the workhorse of retrieval. It fetches candidates using two parallel search methods and fuses them with Reciprocal Rank Fusion (RRF).

**Attribute extraction and filtering** (for `attribute_filter` intent):

- Extracts brand, color, waterproof, a generic feature term, and size constraints from the user query using an LLM — waterproof gets its own dedicated extraction field rather than being folded into the generic feature bucket
- Classifies color and waterproof terms against the OpenSearch-backed taxonomy
- Applies exact-match filters on `product_color_primary`, `product_waterproof_primary`, and `product_brand_normalized`
- Both color's and waterproof's fallback for unresolved terms is a **hard exact-match filter**, reliably producing zero-result scenarios that trigger the taxonomy growth path
- The generic feature field (anything that isn't a color or a waterproofing requirement, e.g. "breathable", "noise canceling") is a **soft lexical filter**, intentionally loose to avoid over-filtering legitimate feature words
- If results drop below 3 products, the retriever relaxes `multi_match` filters (feature, size) but preserves exact-match filters for color, waterproof, and brand (the user named them explicitly)

**Dual-path search:**

1. **Vector Search (HNSW)**: `nomic-embed-text` 768-dimensional embeddings via Ollama with cosine similarity, k=20 candidates
2. **Lexical Search (BM25)**: Full-text analysis using:
   - Primary fields (`chunk_text`, `product_brand`, `product_color`) with `light_english_analyzer` (kstem, light stemming) for precision ("Beats" ≠ "beat")
   - Heavy sub-fields with `heavy_english_analyzer` (snowball, aggressive stemming) at 0.3 boost for morphological recall fallback (matching "running/runs/ran")

**RRF Fusion** normalizes ranks from both methods without probability calibration:

```text
score = Σ 1/(rank + 60)  [k=60 is the RRF constant]
```

The retriever fetches 40 candidates before deduplication and reranking, deduplicates by product (ESCI products may have multiple chunks), and emits `RetrievalProgressEvent` with candidate counts and previews.

### Reranker: Cross-Encoder Scoring

The Reranker re-scores all 40 candidates using a local cross-encoder model (`sentence-transformers/cross-encoder/ms-marco-MiniLM-L-12-v2`) in a single batch call. No API round-trip.

**Process:**

- Scores all candidates with raw logits
- Maps logits to [0.0, 1.0] via sigmoid normalization
- Sorts by score (highest first)
- Returns top 10 for downstream processing
- Emits `RerankerProgressEvent` with per-document scores

**Score interpretation:**

- 0.0–0.2: Off-topic, unrelated
- 0.2–0.5: Partial match, weak relevance
- 0.5–0.7: Good match, clearly relevant
- 0.7–1.0: Excellent match, high confidence

The reranker also sets `reranker_max_score` (the highest score across all candidates), which feeds the Quality Gate decision.

The local cross-encoder is the only reranker; the earlier LLM-based reranker (`GeminiReranker`) has been removed.

### Quality Gate: Retry Logic with Alpha Adjustment

If the reranker's maximum score falls below an intent-specific threshold, the Quality Gate may trigger a retry loop. This catches cases where the initial α was poorly calibrated.

**Intent-specific thresholds:**

- `comparison` → 0.55 (stricter; needs a clear winner)
- `search` and `follow_up` → 0.50 (standard)
- `attribute_filter` and `refinement` → 0.45 (looser; exact attribute matching is straightforward)

**Retry logic:**

1. If `max_score >= threshold` → **PASS**: Continue to the Agent
2. If `max_score < threshold` and not yet retried → **RETRY**: Adjust α by ±0.3 (opposite direction from original), loop back to the Retriever, re-fetch with new α
3. If already retried or other condition → **ACCEPT**: Continue to the Agent (avoid endless loops)

**Alpha adjustment examples:**

- Original α was 0.7 (semantic-heavy), results scored 0.35 → retry with α = 0.4 (favor lexical)
- Original α was 0.2 (lexical-heavy), results scored 0.40 → retry with α = 0.5 (favor semantic)

The Quality Gate emits `QualityGateEvent` with the decision and reasoning, and sets `quality_gate_retried` (boolean flag) for observable state.

### Agent: Response Generation with Citations

The Agent formats the retrieved documents into a prompt context, calls the LLM to generate a conversational response, builds citations, and streams the result token-by-token back to the user.

**Document formatting:** Creates a structured context window with product titles, descriptions, and key attributes.

**LLM generation:** `qwen3.6:35b-a3b-q4_K_M` (local Ollama) generates the conversational response. The prompt is carefully crafted to avoid hallucination and to ground all claims in the provided context.

**Citation building:**

- Extracts product titles from document metadata
- Constructs Amazon search URLs: `https://www.amazon.com/s?k={title}` (search by title rather than ASIN, since ESCI products use title-based search for robustness)
- Filters citations by minimum reranker score (0.10 threshold)
- Deduplicates by URL
- Post-processes to strip any inline URLs the LLM might have emitted (the prompt forbids them; this is belt-and-suspenders defense)

**Token-by-token streaming:** Emits `LLMResponseChunkEvent` with each token as it arrives, allowing the UI to display the response in real-time without waiting for the full completion.

**Link verification** (optional): Validates URLs before inclusion to filter out broken links. Cache TTL is 60 minutes.

The node appends an `AIMessage` to the conversation history and updates the PostgreSQL checkpoint. It emits `AgentCompleteEvent` when done.

### LLM Judge: Hallucination Detection and Auto-Correction

The LLM Judge is an optional layer that runs **after the Agent** to detect and auto-correct hallucinations in the generated response.

**Trigger:** Runs only when both `optimizations.llm` and `optimizations.llm_judge` are enabled in configuration.

**Process:**

- Blind A/B evaluation: A second call to the local LLM (`JUDGE_MODEL`) scores the response against the query and retrieved context, unaware of the original generation process (reduces bias)
- Positional-bias randomization: Shuffles document order when presenting context to avoid ranking artifacts
- Produces a `JudgmentResult` with:
  - `pairwise_verdict` — boolean (is this response accurate?)
  - Absolute scores (0.0–1.0):
    - `faithfulness` — claims grounded in context
    - `answer_relevance` — does it answer the query?
    - `citation_accuracy` — do cited products actually match claims?
    - `context_utilization` — uses context, doesn't fabricate?
  - List of flagged claims, each tagged with a `HallucinationCategory`:
    - `fabrication` — claim unsupported by any document (ELIGIBLE FOR AUTO-RETRY)
    - `cross_product_bleed` — claim from one product mistakenly attributed to another (ELIGIBLE FOR AUTO-RETRY)
    - `inference` — plausible inference not explicitly stated (warning-only, no retry)
    - `overreach` — overgeneralization or scope creep (warning-only, no retry)

**Auto-correction retry:** If any flag has `category in {fabrication, cross_product_bleed}` **and** this is the first retry this turn, the judge regenerates only the problematic claims. The new response replaces the original in the conversation history and UI (via `LLMResponseCorrectedEvent`). Inference and overreach flags surface in the observability panel but skip the retry cost (~20–30s for regeneration).

**Critical behaviors:**

- `hallucination_retry_used` flag is **reset to `False` at the start of every new user turn** in `intent_classifier_node` — without this reset, PostgreSQL checkpoint persistence would permanently disable retry for all subsequent turns after the first hallucination
- All return paths in `agent_node` **must include a `"citations"` key** (populated list or empty list) — the observable_agent depends on consistent state shape for WebSocket emission
- The faithfulness score is NOT the gate for retry — categorical classification (fabrication/cross_product_bleed) is authoritative

### State Management: CustomAgentState

The pipeline shares state via a TypedDict named `CustomAgentState`. It is defined with `total=False`, meaning **only `messages` is guaranteed**. Every other field is optional and may not exist until its node populates it.

**Safe access pattern:**

```python
alpha = state.get("alpha", 0.25)  # ✓ Safe default if not set
alpha = state["alpha"]             # ✗ KeyError if query_evaluator hasn't run yet
```

**Field lifetime table:**

| Field | Source Node | Used By | Guaranteed |
| ------- | ------------- | --------- | ----------- |
| `messages` | Built-in reducer | All nodes | ✓ Yes |
| `intent` | Intent Classifier | Query Evaluator, Quality Gate, Agent | ✗ No |
| `intent_confidence` | Intent Classifier | Query Evaluator | ✗ No |
| `user_query` | Intent Classifier | Query Evaluator, Retriever, Reranker, Agent | ✗ No |
| `reasoning` | Intent Classifier | Observability | ✗ No |
| `alpha` | Query Evaluator | Retriever, Quality Gate | ✗ No |
| `query_analysis` | Query Evaluator | Observability | ✗ No |
| `retrieved_documents` | Retriever | Reranker, Agent, LLM Judge | ✗ No |
| `reranker_max_score` | Reranker | Quality Gate | ✗ No |
| `quality_gate_retried` | Quality Gate | Observability, LLM Judge | ✗ No |
| `quality_gate_reason` | Quality Gate | Observability | ✗ No |
| `quality_gate_threshold_used` | Quality Gate | Observability | ✗ No |
| `hallucination_retry_used` | LLM Judge | LLM Judge (reset at turn start) | ✗ No |
| `corrected_response` | LLM Judge | UI replacement | ✗ No |
| `llm_judgment` | LLM Judge | Observability | ✗ No |

Every node documents which state fields it reads and writes. When adding a new node, declare its state fields in `CustomAgentState` or LangGraph will silently filter your output keys.

### Hybrid Retrieval and RRF Fusion

Hybrid search combines the strengths of two retrieval methods without requiring probability calibration.

**Vector search (HNSW):** Fast semantic understanding, but can miss exact terms and rare synonyms.

**BM25 lexical search:** Perfect for exact ID matching, brands, and explicit product names, but has no semantic understanding.

**Hybrid (RRF):** Rank vectors and lexical results independently, then fuse them by reciprocal rank. The RRF formula avoids probability calibration — a perennial problem with confidence-score fusion.

**Alpha weighting:** The `alpha` parameter (0.0–1.0) controls the contribution of the vector score. It is assigned dynamically per query by the Query Evaluator:

- **α=0.0** (pure lexical): Best for exact IDs, model numbers, ASINs
- **α=0.25–0.40** (lexical-heavy): Best for brand + category, specific attributes
- **α=0.40–0.60** (balanced): Best for feature combinations, activity-based searches
- **α=0.60–0.75** (semantic-heavy): Best for conceptual needs, occasion-based queries
- **α=0.75–1.0** (pure semantic): Best for exploration, mood/style, gift ideas

The Quality Gate can adjust α if the initial choice is poor, up to one retry per query.

### Taxonomy Growth and Self-Correction

The system can discover new product attributes (colors, waterproofing requirements) and correct misclassified ones at runtime, without code deployment.

**The problem:** A shopper searches for "weatherproof jacket" but the system has never seen "weatherproof" as a waterproof synonym. Or they discover that "tan" is indexed as "yellow" instead of "brown" — a real mis-mapping that produces technically correct results (tan products) but under the wrong color bucket.

**Detection at ingest time:** During Lucille ETL, an `AttributeDetectorStage` (a generic, parameterized Java stage) scans product text for known color/waterproof variants using a longest-match-first regex built from the OpenSearch-backed taxonomy. It writes canonical values to keyword fields (`product_color_primary`, `product_waterproof_primary`), which the retriever uses for exact-match filtering.

The taxonomy itself lives in OpenSearch (not a committed file) and can be grown dynamically.

**Gap detection (new terms):** When a shopper searches for a color or waterproofing term the system hasn't learned:

- Both color's and waterproof's fallback is a **hard exact-match filter** (e.g., "chrome" for color, "weatherproof" for waterproof), reliably producing zero results — deliberately unlike the generic feature field (everything that isn't a color or a waterproofing requirement, e.g. "breathable", "noise canceling"), which stays a **soft lexical filter** to avoid over-filtering legitimate feature words

If the retriever returns nothing (color case) or very poor scores after a quality-gate retry (either attribute type), the `agent_node` offers the LLM a `trigger_enrichment(attribute_type, variant, canonical)` tool. The LLM decides whether to map the new term to an existing canonical bucket or create a new one. If it calls the tool, the mapping is written to OpenSearch and, by default (`REINDEX_TRIGGER=scoped`), a scoped re-tag triggers — `pipeline/scoped_retag.py` re-detects the attribute only on products whose text mentions the changed variant, measured live at well under a second to a few seconds, with no re-embedding.

**Correction detection (mis-mappings):** In refinement or follow-up turns, `agent_node` watches for correction language ("that's wrong", "actually that's..."). If detected, it builds a prompt with recent conversation history and offers the same `trigger_enrichment` tool, allowing the LLM to propose a fix. Before execution, an independent `EnrichmentValueJudge` evaluates whether the proposed mapping would genuinely improve search quality (a gate that can veto low-confidence proposals). If accepted, the mapping is rewritten and a reindex follows.

**Making mis-mappings visible:** When building the response context, the `agent_node` includes both the raw `product_color` and its derived `product_color_primary` as separate facts. A grounding rule instructs the LLM to flag any color-to-category mismatch directly in prose ("This tan item is indexed as yellow, which seems wrong"). This surfaces the problem immediately in chat, not just in the observability panel.

**Shared write path:** All enrichment (gap, correction, manual) flows through a single `enrich_attribute` function that writes the mapping, ensures the index has the `product_<type>` fields, regenerates Lucille config (`products.generated.conf`), and triggers the reindex.

The enrichment tool is gated behind `ENABLE_ENRICHMENT_TOOL` (default off) and is disabled in the shipped demo for safety.

### Event Streaming and Real-Time Observability

Every pipeline stage emits typed events over WebSocket. The frontend subscribes and visualizes in real-time.

**Event flow:**

```text
Backend (main.py)
├─ Intent Classifier → IntentClassificationEvent
├─ Query Evaluator → QueryEvaluationEvent
├─ Retriever → RetrievalProgressEvent, OpenSearchQueryEvent
├─ Reranker → RerankerProgressEvent
├─ Quality Gate → QualityGateEvent
├─ Agent → LLMResponseChunkEvent (per token), AgentCompleteEvent
└─ LLM Judge → LLMResponseCorrectedEvent (if auto-correction fires)
     ↓
   JSON over WebSocket
     ↓
Frontend (React)
├─ Parse Pydantic JSON
├─ Store in observabilityStore (Zustand)
└─ Render in ObservabilityPanel
```

**Event schema synchronization (critical):** Event Pydantic models in `api/schemas/events.py` must stay in sync with TypeScript types in `web/src/types/events.ts`. If they diverge, WebSocket serialization fails or the frontend doesn't render the event. CI enforces this via `test_frontend_backend_event_parity.py`.

**WebSocket handshake:**

- Frontend initiates `GET /ws/<thread_id>`
- Backend verifies the `Origin` header (`verify_websocket_origin`) — only allowed localhost ports
- If disallowed, the connection closes; if allowed, the WebSocket upgrades and stays open for its lifetime

**Inbound message contract** (frontend → backend):

```json
{
  "type": "chat_message",
  "message": "your query",
  "thread_id": "conversation-id"
}
```

**Outbound events** (backend → frontend): All events include `type` (event class name) and `node` (pipeline stage). No partial events — every message is complete JSON before transmission. Large responses (token-by-token) stream as individual complete JSON events, not fragmented chunks.

### Module Layout

The codebase is organized by concern, not by pipeline stage:

```text
langchain_agent/
├── main.py                      # Agent class, graph builder
├── cli.py                       # Command-line interface
├── setup.py                     # Service initialization
├── config_generator.py          # Dynamic Lucille config generation
├── core/
│   ├── agent_state.py          # CustomAgentState TypedDict
│   ├── config.py               # Configuration & env vars
│   ├── exceptions.py           # Error hierarchy (AgenticHybridSearchError base)
│   └── logging_config.py       # Structured JSON logging
├── pipeline/
│   ├── pipeline_nodes.py       # All node implementations (7 nodes + utilities)
│   ├── conversation_management.py
│   ├── enrichment_events.py
│   └── reindex_trigger.py      # Spawns lucille_ingest.sh subprocess
├── retrieval/
│   ├── vector_store.py         # OpenSearch client, hybrid search
│   ├── reranker.py             # Cross-encoder (only reranker)
│   ├── attribute_discovery.py  # Taxonomy seed vocabularies
│   └── link_verifier.py        # URL validation cache
├── quality/
│   ├── judge.py                # LLMJudge (hallucination detection)
│   ├── enrichment_value_judge.py # Gate for taxonomy proposals
│   └── demo_reset.py           # Demo-specific utilities
├── observability/
│   ├── embedding_cache.py      # 60-min query embedding cache
│   ├── relevancy_metrics.py
│   └── llm_content_helpers.py
├── checkpoints/
│   └── *                        # PostgreSQL checkpoint optimization
├── benchmarks/
│   └── *                        # ESCI benchmark harness
└── api/
    ├── main.py                 # FastAPI app
    ├── routes/
    │   ├── chat.py            # Chat endpoint (WebSocket)
    │   ├── suggest.py         # Typeahead autocomplete
    │   ├── admin.py           # Health, diagnose, enrich
    │   └── ...
    ├── schemas/
    │   ├── events.py          # Pydantic event models
    │   └── ...
    ├── services/              # Business logic (enrichment, etc.)
    └── middleware/
        ├── origin_auth.py     # Same-origin checking (sole auth layer)
        └── admin_auth.py      # HMAC token for admin routes (not wired today)
```

All node implementations live in `pipeline/pipeline_nodes.py` as methods on the `PipelineNodesMixin` class. State is declared once in `core/agent_state.py` and referenced everywhere.

### Error Handling

All custom exceptions inherit from a single base class, `AgenticHybridSearchError`, with fields:

- `message` — human-readable error text
- `details` — optional dict with structured context
- `recoverable` — boolean (can the user retry?)

Subclass hierarchy:

- `ConfigurationError` — invalid setup
- `DatabaseError` — Postgres or checkpoint issues
- `OpenSearchError` — index/query failures
- `LLMError` — model API failures
- `RetrievalError` — hybrid search failures
- `LinkVerificationError` — URL validation failed
- `StreamingError` — WebSocket issues
- `StateError` — invalid state transition
- `RerankerError`, `RerankerLLMError`, `RerankerValidationError` — reranker-specific
- `SearchValidationError`, `SearchFailureError` — query validation/execution
- `EmbeddingError` — vector generation failed
- `SearchTimeoutError` — query took too long
- `AgentError`, `AgentTimeoutError` — agent-specific issues

Catch `AgenticHybridSearchError` to handle any agent-related error uniformly; the `recoverable` flag tells you whether to suggest retry.

### Performance Characteristics

| Component | Latency | Notes |
| ----------- | --------- | ------- |
| Intent Classification | ~300–500ms | Single LLM call, no keyword fast-path |
| Query Evaluation | 0–500ms | Fast-path instant, LLM-path ~300–500ms |
| Vector Search (HNSW) | 200–500ms | 768-dim embeddings, k=20 |
| Lexical Search (BM25) | 100–300ms | Full-text indexing |
| RRF Fusion | ~10ms | In-memory rank merge |
| Reranking (cross-encoder) | ~1.5–2s | Local `ms-marco-MiniLM-L-12-v2`, 40 candidates scored |
| Quality Gate Retry | +1–2s | If triggered (max 1 retry per query) |
| Response Generation | 3–8s | LLM streaming |
| **Total (Q&A)** | **6–15s** | End-to-end, no retry |

Cached vector embeddings (60-min TTL) save ~2–3 seconds on repeated queries.

### Testing Strategy

- **Unit tests** (`tests/unit/`): Mocked LLMs and services, ~0.5s, no Docker required
- **Integration tests** (`tests/integration/`): Real Postgres + OpenSearch, verifies state flow and checkpoint persistence
- **E2E tests** (`tests/e2e/`): Full system with real LLM calls, smoke scenarios
- **Manual testing**: Verify correct α assignment, trigger quality-gate retries, check citation URLs

Run `make check` before any push — that's the gate.

### Adding Custom Nodes and Extensions

**Adding a new pipeline node:**

1. Implement `async def my_node(state: CustomAgentState) -> Dict[str, Any]` in `pipeline/pipeline_nodes.py`
2. Declare any new state fields in `CustomAgentState`
3. Add to the graph: `graph.add_node("my_node", my_node)`
4. Wire edges (conditional or deterministic)
5. Create `MyNodeEvent` in `api/schemas/events.py` and TypeScript counterpart in `web/src/types/events.ts`
6. Add accumulation logic in `observabilityStore.ts`
7. Add UI rendering in `ObservabilityPanel` components
8. Test with integration suite

**Adding a new attribute type** (beyond color/waterproof):

1. Add canonical seed vocabulary to `retrieval/attribute_discovery.py`
2. Seed the OpenSearch taxonomy via `AttributeMappingStore.seed_from_discovery(...)`
3. Add a filter block to `_extract_attributes()` in `pipeline/pipeline_nodes.py` (decide on hard vs. soft filter semantics upfront)
4. Add the new type's field to the BM25 boost list in `retrieval/vector_store.py` (deliberate choice to avoid extra OpenSearch round-trips)
5. The `trigger_enrichment` tool and `/api/admin/enrich` already accept any `attribute_type` string — no changes needed

**Swapping the LLM provider:**

1. Replace `ChatGoogleGenerativeAI` with your provider (`ChatOpenAI`, `ChatAnthropic`, etc.) in `main.py`
2. Update model names in `core/config.py`
3. Ensure all models support structured output (required for intent classification and reranker)
4. Validate with `PYTHONPATH=. python3 setup.py`

---

## API & WebSocket Reference

### REST Endpoints

#### Health Check

The health endpoint requires no authentication and confirms that all dependencies are reachable.

```bash
curl http://localhost:8000/api/health
```

Response (200 OK):

```json
{
  "status": "ok",
  "version": "1.1.0",
  "postgres": true,
  "llm": true,
  "vector_store": true,
  "document_count": 158637
}
```

`status` is `"ok"` when PostgreSQL and the LLM (`llm` field, true when Ollama is reachable and every configured model is pulled) are both healthy; otherwise `"degraded"`. An optional `llm_error` field carries detail when it isn't healthy. The endpoint always returns HTTP 200, even when degraded — it fails open for monitoring purposes.

#### Suggestions (Typeahead Autocomplete)

Retrieve typeahead suggestions for a search prefix. Suggestions are context-free and drawn from product titles and brands.

```bash
curl 'http://localhost:8000/api/suggest?q=wireless' \
  -H "Origin: http://localhost:8000"
```

**Query parameters:**

- `q` (required): search prefix, 1–100 characters
- `limit` (optional, default 8, range 1–20): max suggestions to return

Response (200 OK):

```json
{
  "suggestions": [
    {
      "text": "wireless headphones",
      "source": "products",
      "score": 0.95
    },
    {
      "text": "wireless speaker",
      "source": "products",
      "score": 0.88
    }
  ]
}
```

Single-character typos are corrected via spell-checking; longer queries fall back to exact prefix matching.

#### Chat

Real-time conversational interaction happens over WebSocket at `/ws/chat` (see [WebSocket Protocol](#websocket-protocol) below) — use it for anything that needs to show pipeline progress or stream tokens. ⚠️ **DRIFT NOTE**: an earlier revision of this section said there was no REST chat endpoint at all; that's no longer accurate.

There is also a **non-streaming REST fallback** at `POST /api/chat`, for callers that just want the final answer without a WebSocket connection:

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Origin: http://localhost:8000" \
  -H "Content-Type: application/json" \
  -d '{"message": "Find wireless headphones", "thread_id": "conv_abc123"}'
```

Response (200 OK):

```json
{
  "thread_id": "conversation_abc123",
  "response": "Here are some great running shoes...",
  "duration_ms": 2450.5,
  "citations": [
    {"label": "Blue Running Shoes", "url": "https://www.amazon.com/s?k=Blue+Running+Shoes"}
  ]
}
```

It runs the same LangGraph pipeline and returns only after the full response is generated — no intermediate pipeline events, no streaming. Both this endpoint and the WebSocket endpoint share the same `RATE_LIMIT_CHAT` limit (see [Rate Limiting](#rate-limiting)).

#### Conversation Management (REST)

You can list, inspect, and delete conversation history via REST endpoints. These do not start or continue a conversation — they manage stored thread records from WebSocket sessions.

**List all conversations:**

```bash
curl http://localhost:8000/api/conversations \
  -H "Origin: http://localhost:8000"
```

**Retrieve a single conversation:**

```bash
curl http://localhost:8000/api/conversations/{thread_id} \
  -H "Origin: http://localhost:8000"
```

Returns the conversation summary (metadata and full message history).

**Retrieve observability snapshot for a conversation:**

```bash
curl http://localhost:8000/api/conversations/{thread_id}/observability \
  -H "Origin: http://localhost:8000"
```

Returns per-turn metrics (NDCG, MRR, Recall, Precision) and latency breakdowns.

**Delete a single conversation:**

```bash
curl -X DELETE http://localhost:8000/api/conversations/{thread_id} \
  -H "Origin: http://localhost:8000"
```

**Delete all conversations:**

```bash
curl -X DELETE http://localhost:8000/api/conversations \
  -H "Origin: http://localhost:8000"
```

#### Admin Endpoints

All admin routes are protected by same-origin checking, same as public endpoints — there is no separate authentication layer (see [Authentication & Authorization](#authentication--authorization)).

**Admin health check:**

Probes the product index (OpenSearch) separately from the general health check.

```bash
curl http://localhost:8000/api/admin/health \
  -H "Origin: http://localhost:8000"
```

Response (200 OK):

```json
{
  "status": "healthy",
  "opensearch": {
    "connected": true,
    "index": "esci-products",
    "documents": 158637
  }
}
```

**Diagnose index fields:**

Checks whether the suggest fields (`title_suggest`, `brand_suggest`) are present in the live index mapping.

```bash
curl 'http://localhost:8000/api/admin/diagnose?q=sony' \
  -H "Origin: http://localhost:8000"
```

Query parameter `q` defaults to "sony" and is used to probe the suggest fields. Useful for detecting mapping drift after an index upgrade.

**Enrich attribute taxonomy:**

Adds a new variant-to-canonical mapping for colors or waterproofing terms and, by default (`REINDEX_TRIGGER=scoped`), triggers a scoped re-tag of just the products whose text mentions the changed variant — measured live at well under a second to a few seconds, no re-embedding. This is the same mechanism the agent's `trigger_enrichment` tool uses when it encounters an unmapped attribute during a chat turn.

```bash
curl -X POST http://localhost:8000/api/admin/enrich \
  -H "Origin: http://localhost:8000" \
  -H "Content-Type: application/json" \
  -d '{"attribute_type": "waterproof", "variant": "weatherproof", "canonical": "waterproof"}'
```

**Request fields:**

- `attribute_type` (required): `"color"` or `"waterproof"`
- `variant` (required): new term to add (non-empty string)
- `canonical` (optional): the known waterproof/color bucket it belongs to; if omitted, the system attempts dictionary-based classification

Response (200 OK):

```json
{
  "success": true,
  "attribute_type": "waterproof",
  "variant": "weatherproof",
  "canonical": "waterproof",
  "reason": null,
  "reindex_triggered": true,
  "reindex_success": true,
  "docs_processed": 905,
  "duration_seconds": 0.8
}
```

When enrichment succeeds, a scoped re-tag runs. `success: false` (still HTTP 200) indicates the term could not be classified or is already mapped:

```json
{
  "success": false,
  "attribute_type": "waterproof",
  "variant": "unobtainium",
  "canonical": null,
  "reason": "could not classify to a known waterproof bucket",
  "reindex_triggered": false,
  "reindex_success": false,
  "docs_processed": 0,
  "duration_seconds": 0.0
}
```

The enrich endpoint requires `ENABLE_ENRICHMENT_TOOL=true` to be set on the backend; it returns 403 Forbidden if the flag is absent or false.

**Demo reset:**

Re-arms both self-consuming demos (the taxonomy-correction Arc 2 and the Schema Evolution bonus) by clearing their learned mappings so they can run again from a clean state (admin demonstration only).

```bash
curl -X POST http://localhost:8000/api/admin/demo-reset \
  -H "Origin: http://localhost:8000"
```

---

### WebSocket Protocol

The WebSocket endpoint streams real-time pipeline events for a chat session. Use it for any interactive UI that needs to show progress as the agent thinks through a query.

#### Connection

Connect to the WebSocket endpoint with a `thread_id` query parameter. If you omit `thread_id`, the server generates one and reports it in the `connection_established` event.

**Development URL:**

```text
ws://localhost:8000/ws/chat?thread_id={thread_id}
```

**Optional query parameter:**

- `thread_id`: conversation identifier (UUID or custom string). If omitted, server generates one as `conversation_<8 hex chars>`.

After connecting, the server immediately sends:

```json
{
  "type": "connection_established",
  "thread_id": "conv_abc123def456",
  "timestamp": "2026-06-04T16:30:45Z"
}
```

If you did not provide a `thread_id`, this event tells you which ID the server assigned. You must echo this ID in every `chat_message` you send.

#### Sending Messages

Send a chat message as JSON. All fields are required.

```json
{
  "type": "chat_message",
  "message": "Find wireless headphones under $100",
  "thread_id": "conv_abc123def456"
}
```

The `thread_id` must match either the parameter you passed on connection or the ID reported in `connection_established`.

#### Receiving Events

The server streams back a sequence of typed events. Every event has a `type` field identifying its kind and a `node` field indicating which pipeline stage emitted it.

| Event Type | Node | Purpose |
| --- | --- | --- |
| `connection_established` | — | Handshake complete; reports assigned `thread_id` if you didn't provide one |
| `search_progress` | intent_classifier | Intent classification (type and confidence) |
| `query_expansion` | query_evaluator | Query rewriting result (resolves pronouns, comparatives) |
| `opensearch_query` | retriever | Full OpenSearch DSL query for debugging |
| `reranker_progress` | reranker | Cross-encoder reranking in progress |
| `quality_gate` | quality_gate | Quality gate verdict (`"pass"` or `"retry"`), retry count |
| `llm_response_chunk` | agent | Token-by-token response text (streaming) |
| `llm_response_corrected` | llm_judge | Auto-correction fired (replaces the preceding streamed message); includes `original_chunk` and `corrected_chunk` |
| `clarification_requested` | intent_classifier | Low-confidence intent; user clarification needed |
| `clarification_resolved` | intent_classifier | User provided clarification |
| `agent_complete` | agent | Final response and citations |
| `enrichment_triggered` | agent | Taxonomy enrichment tool was called; includes `attribute_type`, `variant`, `canonical` |
| `pipeline_summary` | — | Per-stage metrics (NDCG, MRR, latency) |

#### Example Search Flow

1. **Send message:**

   ```json
   {"type": "chat_message", "message": "wireless headphones", "thread_id": "conv_abc123def456"}
   ```

2. **Receive events:**

Intent classification begins:

```json
{"type": "search_progress", "node": "intent_classifier", "status": "classifying"}
```

Intent detected:

```json
{"type": "search_progress", "node": "intent_classifier", "intent": "search", "confidence": 0.95}
```

Query rewriting:

```json
{"type": "query_expansion", "node": "query_evaluator", "expanded_query": "wireless headphones"}
```

Reranking progress:

```json
{"type": "reranker_progress", "node": "reranker", "documents_scored": 40, "max_score": 0.87}
```

LLM generates response (streaming chunks):

```json
{"type": "llm_response_chunk", "node": "agent", "chunk": "Here are the ", "complete": false}
```

```json
{"type": "llm_response_chunk", "node": "agent", "chunk": "top wireless", "complete": false}
```

```json
{"type": "llm_response_chunk", "node": "agent", "chunk": " headphones:\n", "complete": false}
```

Response complete with citations:

```json
{
  "type": "agent_complete",
  "node": "agent",
  "response": "Here are the top wireless headphones:\n1. Bose QuietComfort...",
  "citations": [
    {"url": "https://www.amazon.com/s?k=Bose+QuietComfort", "title": "Bose QuietComfort"}
  ]
}
```

Pipeline summary:

```json
{
  "type": "pipeline_summary",
  "node": "agent",
  "metrics": {
    "intent": "search",
    "retriever_latency_ms": 1200,
    "reranker_max_score": 0.87,
    "agent_latency_ms": 8500,
    "total_latency_ms": 10200
  }
}
```

#### Close Codes

| Code | Meaning | Action |
| --- | --- | --- |
| 1000 | Normal close | Conversation ended cleanly |
| 1001 | Going away | Server shutting down |
| 4003 | Origin not allowed | Reconnect with an allow-listed Origin header |
| 4500 | Server error | Unexpected error; reconnect after checking logs |

If you receive close code 4003, your `Origin` header did not match the allow-list. Fix the `Origin` header and reconnect — there is no login/session step to retry.

#### JavaScript Example (React)

```javascript
import { useEffect, useState } from 'react';

export function ChatComponent() {
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isConnected, setIsConnected] = useState(false);
  const ws = React.useRef(null);

  useEffect(() => {
    const threadId = 'conv_abc123def456'; // Or omit to let server generate one
    const url = `ws://localhost:8000/ws/chat?thread_id=${threadId}`;

    ws.current = new WebSocket(url);
    ws.current.onopen = () => setIsConnected(true);
    ws.current.onmessage = (event) => {
      const event_obj = JSON.parse(event.data);
      console.log('Received event:', event_obj.type, event_obj);

      if (event_obj.type === 'llm_response_chunk') {
        // Append chunk to message
        setMessages((msgs) => [
          ...msgs.slice(0, -1),
          {
            ...msgs[msgs.length - 1],
            content: msgs[msgs.length - 1].content + event_obj.chunk,
          },
        ]);
      } else if (event_obj.type === 'agent_complete') {
        // Add citations
        setMessages((msgs) => [
          ...msgs.slice(0, -1),
          { ...msgs[msgs.length - 1], citations: event_obj.citations },
        ]);
      }
    };
    ws.current.onerror = (error) => console.error('WebSocket error:', error);
    ws.current.onclose = (event) => {
      setIsConnected(false);
      if (event.code === 4003) {
        console.log('Origin not allowed; fix Origin header and reconnect');
      }
    };

    return () => ws.current?.close();
  }, []);

  const sendMessage = () => {
    if (!isConnected) return;
    ws.current.send(
      JSON.stringify({
        type: 'chat_message',
        message: inputValue,
        thread_id: 'conv_abc123def456',
      })
    );
    setMessages((msgs) => [...msgs, { role: 'user', content: inputValue }]);
    setInputValue('');
    setMessages((msgs) => [...msgs, { role: 'assistant', content: '' }]);
  };

  return (
    <div>
      <div>{messages.map((msg) => <p key={msg.id}>{msg.content}</p>)}</div>
      <input
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        disabled={!isConnected}
      />
      <button onClick={sendMessage} disabled={!isConnected}>
        Send
      </button>
    </div>
  );
}
```

#### Python Example (asyncio)

```python
import asyncio
import json
import websockets

async def chat_session(thread_id: str):
    url = f"ws://localhost:8000/ws/chat?thread_id={thread_id}"
    headers = {"Origin": "http://localhost:8000"}

    async with websockets.connect(url, additional_headers=headers) as ws:
        # Wait for connection_established
        event = json.loads(await ws.recv())
        assert event["type"] == "connection_established"
        print(f"Connected to thread {event['thread_id']}")

        # Send a message
        await ws.send(
            json.dumps({
                "type": "chat_message",
                "message": "Find wireless headphones under $100",
                "thread_id": thread_id,
            })
        )

        # Stream events
        full_response = ""
        async for message in ws:
            event = json.loads(message)
            event_type = event.get("type")

            if event_type == "llm_response_chunk":
                chunk = event.get("chunk", "")
                print(chunk, end="", flush=True)
                full_response += chunk

            elif event_type == "agent_complete":
                citations = event.get("citations", [])
                print(f"\n\nCitations: {citations}")

            elif event_type == "pipeline_summary":
                metrics = event.get("metrics", {})
                print(f"Total latency: {metrics.get('total_latency_ms')} ms")

        print("\n[Session complete]")

if __name__ == "__main__":
    thread_id = "conv_abc123def456"
    asyncio.run(chat_session(thread_id))
```

---

### Authentication & Authorization

#### Same-Origin Checking (The Only Auth Layer)

There is no login gate in this application. The sole authentication mechanism is **same-origin checking**: every request must carry an `Origin` (or, for plain GET requests without an `Origin` header, a `Referer`) that matches an allow-list. A disallowed origin always receives `403 Forbidden`.

This is appropriate for a local demo running on `localhost`. All endpoints — public, admin, WebSocket — are protected by the same allow-list. There is no role-based access control or token-based authentication in the request path.

#### Allow-Listed Origins

The following origins are allow-listed by default (⚠️ **DRIFT NOTE**: an earlier revision of this list was stale — corrected below):

- `http://localhost:5173` / `http://127.0.0.1:5173` (Vite dev, default port)
- `http://localhost:5174` / `http://127.0.0.1:5174` (Vite dev, fallback port)
- `http://localhost:3000` / `http://127.0.0.1:3000` (alt dev)
- `http://localhost:8000` / `http://127.0.0.1:8000` (backend, local e2e tests)
- `http://localhost:8080` / `http://127.0.0.1:8080` (dev server)
- `https://*.a.run.app` (Cloud Run pattern, matched via regex, not an exact-match list entry; dormant, no active deployment target)

For a complete and authoritative list, see `get_allowed_origins()` and `is_allowed_origin()` in `api/middleware/origin_auth.py`.

#### Making Requests

**REST (curl example):**

```bash
curl http://localhost:8000/api/suggest?q=wireless \
  -H "Origin: http://localhost:8000"
```

Browsers set the `Origin` header automatically on all requests; no explicit header is required. Custom clients (curl, Python scripts) must include it.

**WebSocket (JavaScript):**

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/chat?thread_id=conv_abc123');
// Browsers set Origin automatically on the handshake.
```

**WebSocket (Python):**

```python
import websockets

async with websockets.connect(
    "ws://localhost:8000/ws/chat?thread_id=conv_abc123",
    additional_headers={"Origin": "http://localhost:8000"}
) as ws:
    ...
```

Non-browser clients must set the `Origin` header explicitly on the WebSocket handshake.

#### Admin Token (Preserved but Unused)

The codebase contains `verify_admin_token` in `api/middleware/admin_auth.py`, which checks an `X-Admin-Token` header against an `ADMIN_TOKEN` environment variable using constant-time comparison (`hmac.compare_digest`). This utility was preserved for potential future automation (e.g., a CI job calling admin endpoints without a browser).

**It is not currently wired into any route.** All endpoints, including `/api/admin/*`, rely on same-origin checking only. Supplying an `X-Admin-Token` header has no effect today. If you need to enable token-based access in the future, the infrastructure is in place but requires code changes to wire it into specific routes.

To generate a token for future use:

```bash
openssl rand -hex 32
```

Store it in the `ADMIN_TOKEN` environment variable. Keep tokens secret; never commit them to version control.

---

### Error Responses

#### 400 Bad Request

Indicates malformed JSON or missing required fields.

```json
{
  "detail": "Invalid JSON or missing required field 'message'"
}
```

**Fix:** Check your request body and ensure all required fields are present.

#### 403 Forbidden

Returned for two distinct reasons:

1. **Disallowed Origin:**

   ```json
   {
     "detail": "Origin header is not allowed"
   }
   ```

   **Fix:** Verify your `Origin` header is in the allow-list (see [Allow-Listed Origins](#allow-listed-origins)).

2. **Enrichment tool disabled:**
The `POST /api/admin/enrich` endpoint returns 403 when `ENABLE_ENRICHMENT_TOOL` is not set or false.

```json
{
  "detail": "Enrichment tool is not enabled"
}
```

**Fix:** Set `ENABLE_ENRICHMENT_TOOL=true` on the backend to enable this endpoint.

#### 422 Unprocessable Entity

Validation error (e.g., missing `attribute_type` or empty `variant` in an enrich request).

```json
{
  "detail": "Invalid request: variant cannot be empty"
}
```

**Fix:** Check that all required fields are provided and conform to type expectations.

#### 429 Too Many Requests

Returned when a client exceeds the per-endpoint rate limit (see [Rate Limiting](#rate-limiting)).

```json
{
  "detail": "Rate limit exceeded: 20 per 1 minute"
}
```

**Fix:** Slow down requests from that client IP; retry after the limit window resets.

#### 500 Internal Server Error

An unexpected error occurred on the server.

```json
{
  "detail": "An error occurred. Check logs for details."
}
```

**Fix:** Check `/api/health` to see which dependency probe failed (PostgreSQL, Ollama LLM, OpenSearch). Review server logs for details.

#### 503 Service Unavailable

The server is temporarily unable to respond (e.g., database connection pool exhausted).

```json
{
  "detail": "Service temporarily unavailable"
}
```

**Fix:** Retry after a short delay with exponential backoff.

---

### Status Codes and Retry Guidance

| Code | Success | Retry? | Notes |
| --- | --- | --- | --- |
| 200 | Yes | — | Request succeeded |
| 400 | No | No | Fix the request; retrying won't help |
| 403 | No | No | Check Origin header or enable the feature |
| 422 | No | No | Validation error; fix the request |
| 429 | No | Yes | Rate limit exceeded; retry after the limit window resets |
| 500 | No | Yes | Server error; retry with exponential backoff |
| 503 | No | Yes | Service unavailable; retry after a delay |

---

### Rate Limiting

⚠️ **DRIFT NOTE**: an earlier revision of this section claimed no rate limiting was enforced. That's no longer true — `slowapi`-based per-client-IP rate limiting is enabled by default (`RATE_LIMIT_ENABLED=True` in `core/config.py`):

| Endpoint(s) | Limit |
| --- | --- |
| `POST /api/chat`, `/ws/chat` | 20/minute |
| `/api/conversations` (list, get, delete, observability) | 10/minute |

Exceeding a limit returns `429 Too Many Requests` (handled by slowapi's default `RateLimitExceeded` handler). Health, suggest, and admin endpoints are not currently rate-limited.

---

⚠️ **DRIFT:** `api/README.md` line 25 lists the chat endpoint as `POST /api/chat (WebSocket)`, but the actual route is `/ws/chat` (WebSocket, not POST).

⚠️ **DRIFT:** Example code in `websocket.md` uses Cloud Run URLs (`wss://agentic-hybrid-search-XXXX.run.app`), but the only supported deployment target is localhost (`ws://localhost:8000/ws/chat`). Cloud Run is a dormant pattern with no active deployment (see issue #110/#113).

---

## Frontend / Web UI

The frontend is a React 19 single-page application built with TypeScript, Tailwind CSS v4, Zustand for state management, and Vite as the bundler. It runs on port 5173 during development and proxies `/api` calls to the backend on port 8000. The frontend ships with the backend Docker image — there is no separate Node.js service.

### Frontend Tech Stack

The frontend uses modern tooling to deliver a responsive, type-safe chat and observability interface:

- **React 19** — Component framework for the UI
- **TypeScript** — Type safety across the codebase
- **Tailwind CSS v4** — Utility-first styling with semantic HTML and WCAG 2.1 accessibility
- **Zustand** — Global state management for messages, events, and UI toggles
- **Vite** — Build tool with fast dev server and hot module reloading
- **Vitest** — Unit testing framework with 290 tests
- **WebSocket** — Real-time event streaming from the backend

### Running and Developing

From the `langchain_agent/web/` directory, start the development server:

```bash
npm install
npm run dev
```

The dev server binds to `http://localhost:5173` and automatically proxies API calls to `http://localhost:8000/api`. Your browser will hot-reload when you edit source files.

For linting and testing, use:

```bash
npm run lint          # ESLint with --max-warnings 0
npm run test          # Vitest runner; all 290 tests
npm run test -- --watch       # Watch mode for iterative testing
npm run test -- --coverage    # HTML coverage report
```

To prepare for production, build the frontend:

```bash
npm run build         # Output: dist/
```

The build step compiles TypeScript and bundles the application into `dist/`, which gets embedded in the Docker image at build time.

### Project Structure

The source tree follows a clear modular organization:

```text
src/
├── App.tsx                          Root component and page routing
├── main.tsx                         React 19 entry point, Zustand init
├── components/
│   ├── ChatPanel/                   Chat UI, message history
│   ├── ObservabilityPanel/          Real-time pipeline visualization
│   ├── NarratorPanel/               Per-turn pipeline narration for the scripted demo
│   ├── DemoSelector.tsx             Dropdown to pick one of the four scripted demos
│   ├── Layout.tsx                   Root layout wrapper
│   ├── ConfirmDialog.tsx            Reusable confirmation modal
│   ├── ErrorNotification.tsx        Toast-style error display
│   ├── SkeletonLoader.tsx           Loading placeholder
│   └── ...                          Other shared components
├── demos/
│   └── registry.ts                  The four scripted demos, as data (queries, watch-for text, arming rules)
├── hooks/
│   ├── useWebSocket.ts              WebSocket lifecycle and event routing
│   ├── useRecentSearches.ts         localStorage-backed search history
│   └── ...
├── stores/
│   ├── chatStore.ts                 Messages, threads, UI state
│   ├── observabilityStore.ts        Pipeline events and timeline
│   ├── optimizationsStore.ts        Search-optimization toggles
│   └── ...
├── types/
│   ├── events.ts                    TypeScript event types (sync with api/schemas/events.py)
│   └── ...
├── pages/                           Page-level components (GuidePage, SwaggerPage)
├── utils/                           Formatting and helper utilities
└── tests/                           Vitest tests alongside source
```

⚠️ **DRIFT NOTE**: an earlier revision of this listing showed a `LoginScreen.tsx` component and a `ConversationsSidebar/` with logout — neither exists in the current tree. There is no login gate anywhere in this app (removed entirely, issue #135); same-origin checking is the sole auth layer (see [Authentication & Authorization](#authentication--authorization)).

### Chat Panel

The Chat Panel is where users interact with the agent. It displays the conversation history and provides an input field for new queries.

**Key Components:**

- **MessageList** — Scrollable conversation history with auto-scroll on new messages
- **Message** — Individual message renderer with markdown, syntax-highlighted code blocks, and citations. When the LLM judge auto-corrects a hallucination, an amber badge appears with a "Show original" toggle to reveal the uncorrected version.
- **MessageInput** — Multi-line text input with send button and loading state
- **TypeaheadSuggestions** — Real-time dropdown showing recent searches (from browser localStorage) and spell-corrected suggestions, triggered on keystroke with debounce

**Streaming:** As the backend emits `LLMResponseChunkEvent` events over WebSocket, chunks append to `streamingContent` in the Zustand store. Once complete, the chunk moves to the persisted `messages` array.

**Citations:** Below each message, deduplicated citations appear as links (filtered by minimum reranker score of 0.10). ESCI product citations default to Amazon search-by-title form (`https://www.amazon.com/s?k={title}`).

**Recent Searches:** The typeahead maintains a max of 8 recent queries in localStorage, deduplicating case-insensitively by moving duplicates to the front. Recent searches persist across page reloads; users can clear them explicitly in the UI.

### Observability Panel

The Observability Panel gives you real-time visibility into the RAG pipeline as it runs. You watch the agent traverse intent classification, retrieval, reranking, and quality gates step-by-step.

**Key Components:**

- **StepsList** — Linear timeline of pipeline nodes with collapse/expand controls to show detail
- **StepCard** — Individual pipeline stage with elapsed time and current status
- **PipelineSummaryCard** — Per-stage metrics displayed after the agent completes: NDCG@10, MRR, Recall@20, Precision@10, and lift-per-100ms (improvement of reranked vs. BM25 baseline)
- **SearchOptimizationDetails** — Side-by-side cards showing BM25 and Hybrid+Reranked results with lift indicators, broken down by optimization (fuzzy matching, synonyms, phonetic, phrase boost, field boost)
- **DslViewerModal** — Full OpenSearch DSL query body, request line, and vector embeddings (scrubbed to `<EMBEDDING_OMITTED_768_DIMS>` for readability)
- **RawEventInspector** — Raw event JSON dump for debugging
- **HistoricalSnapshotCard** — LangGraph checkpoint snapshot view (if saved)

**Event Flow:** WebSocket receives typed pipeline events from the backend → `observabilityStore.addEvent()` updates the timeline → components re-render to show the new step. Metrics are computed server-side and sent with `agent_complete` events.

**Quality Gate Visualization:** If the quality gate retries (with adjusted alpha and wider candidate pool), you see both the initial retrieval and the retry in the timeline with metrics for each.

### State Management (Zustand)

Three Zustand stores coordinate global state across the frontend:

**chatStore** — Holds all conversation state: `threadId`, `messages[]` (each with `corrected`, `originalContent`, and `originalFaithfulness` for judge auto-correction), `isProcessing`, `streamingContent`, and `isConnected`. Actions include `addMessage()`, `setThreadId()`, and `updateMessageStatus()`.

**observabilityStore** — Tracks the event stream from the pipeline: `events[]`, `activeStep` (currently selected node), and `snapshots[]` for checkpoints. Key actions are `addEvent()` (called by `useWebSocket`), `setActiveStep()`, and `saveSnapshot()`.

**optimizationsStore** — UI toggles for visualization modes. Keys include `hybrid`, `fuzzy`, `synonyms`, `phonetic`, `phrase_boost`, `field_boost`, `typeahead`, `reranking`, `llm`, and `llm_judge`. Actions include `toggle(key)`, `setAll(value)`, and `reset()`. Toggles persist to localStorage for session recall.

### Custom Hooks

Two custom hooks handle complex side effects and data management:

**useWebSocket()** — Manages a singleton WebSocket connection to the agent backend. Returns `isConnected`, `isConnecting`, `error`, `connect(threadId)`, `disconnect()`, `sendMessage(message)`, and `stopExecution()`. The hook automatically emits typed events to `observabilityStore.addEvent()` and validates same-origin (Origin header) on handshake. Auto-reconnection handles transient failures.

**useRecentSearches()** — Reads and writes recent queries to browser localStorage under the key `agentic-search-recent`. Returns `{ recent: string[], add: (q: string) => void, clear: () => void }`. Multiple components can call this hook; they share the same localStorage but maintain independent read state.

### Event Contract

TypeScript event types in `web/src/types/events.ts` must match the Python Pydantic models in `api/schemas/events.py`. Every event's `type` (as a Literal union) and `node` field must align between both files. A pre-flight test, `test_frontend_backend_event_parity.py`, catches divergence.

If you add a new event type:

1. Add the Pydantic model to `api/schemas/events.py`
2. Export the `type: Literal[...]` in the union at the bottom of that file
3. Add the matching TypeScript interface to `web/src/types/events.ts`
4. Verify `node` field values match
5. Run: `PYTHONPATH=. pytest tests/unit/test_frontend_backend_event_parity.py`

### Testing

Tests live alongside source in `**/__tests__/` directories and are run with Vitest:

```bash
npm run test                         # Run all 290 tests once
npm run test -- --watch             # Watch mode
npm run test -- --coverage          # HTML coverage report
npm run test -- --grep "PatternName" # Filter by test name
```

Coverage spans Zustand stores (state mutations, persistence), WebSocket hooks (connection, auth, reconnection), observable components (intent badges, metrics, event rendering), and accessibility (ARIA attributes, keyboard navigation).

### Configuration

Environment variables (Vite requires the `VITE_` prefix):

| Variable | Purpose | Example |
| ---------- | --------- | --------- |
| `VITE_API_URL` | Backend API endpoint | `http://localhost:8000/api` |

The `VITE_API_URL` is set in `.env.local` during local development (by `setup.sh`) and can be overridden via Docker build `--build-arg` for production deployments.

### Troubleshooting

**Can't connect to the backend:** Verify the backend is running on port 8000:

```bash
curl http://localhost:8000/api/health
```

**Vite build fails:** Check for TypeScript errors:

```bash
npx tsc --noEmit
```

**Tests fail:** Reinstall dependencies and try again:

```bash
rm -rf node_modules package-lock.json
npm install
npm run test
```

**Event type mismatch errors:** Ensure `api/schemas/events.py` and `web/src/types/events.ts` are in sync, then run the pre-flight test:

```bash
PYTHONPATH=. pytest tests/unit/test_frontend_backend_event_parity.py
```

### Build and Deployment

The Docker build process compiles the frontend and embeds it in the Python backend container:

1. **Build stage** — Node 24 runtime runs `npm install && npm run build` to produce `dist/`
2. **Runtime stage** — Python 3.14 + gunicorn serves the built frontend from `dist/` and proxies `/api` calls to the Python backend

No separate Node.js service is needed at runtime; the frontend and backend run as a single container.

### Accessibility and Styling

All components use semantic HTML and follow WCAG 2.1 accessibility guidelines. Theme customization (colors, animations) is configured via `@theme` in `src/index.css` using Tailwind's CSS-based configuration. There is no separate `tailwind.config.js` file.

---

## Testing & Benchmarks

### Test Suite Overview

The project uses a three-layer testing pyramid: fast unit tests with mocked services, integration tests against real databases and services, and end-to-end tests against a running backend. All test commands run from `langchain_agent/` and require `PYTHONPATH=.` to resolve bare imports.

```text
tests/
├── unit/               # Fast, no external services (~0.5s total)
├── integration/        # Multi-component with live Postgres + OpenSearch
├── e2e/               # Full backend, real WebSocket streams
└── conftest.py        # Shared fixtures + environment defaults
```

### Running Tests

#### Full test suite

```bash
cd langchain_agent
PYTHONPATH=. pytest tests/ -v
```

#### By scope

```bash
PYTHONPATH=. pytest tests/unit/ -v              # ~0.5s, no dependencies
PYTHONPATH=. pytest tests/integration/ -v      # requires Docker (Postgres + OpenSearch) + Ollama
PYTHONPATH=. pytest tests/e2e/ -v              # requires running backend
```

#### By file or pattern

```bash
PYTHONPATH=. pytest tests/unit/intent/test_intent_classifier.py -v
PYTHONPATH=. pytest tests/integration/test_pipeline_flow.py -v
PYTHONPATH=. pytest tests/ -k "quality_gate"
```

#### By marker

```bash
PYTHONPATH=. pytest tests/ -m unit
PYTHONPATH=. pytest tests/ -m "integration and not slow"
PYTHONPATH=. pytest tests/unit/test_foo.py::test_bar -v    # single test
```

#### Code coverage

```bash
PYTHONPATH=. pytest tests/ --cov=. --cov-report=html
open htmlcov/index.html
```

### Pytest Markers

⚠️ DRIFT: The CLAUDE.md marker list includes obsolete markers (performance, load, stress, profile) from test files removed 2026-09-15; the list below reflects the current active markers.

The following markers are available for organizing and filtering tests:

| Marker | Purpose |
| -------- | --------- |
| `unit` | Fast component tests with mocked services |
| `integration` | Multi-component tests requiring live services |
| `e2e` | End-to-end tests against a running backend |
| `slow` | Long-running tests (e.g., full Lucille reindex); skip with `-m "not slow"` |
| `asyncio` | Async test functions |
| `websocket` | WebSocket-specific tests |
| `agent` | LangGraph agent node tests |
| `edge_cases` | Boundary and error-path tests |
| `pipeline` | Full RAG pipeline flow tests |
| `quality_gate_retry` | Quality gate retry logic |
| `retriever_reranker` | Retrieval and reranking integration |
| `requires_real_api` | Tests needing live LLM calls (local Ollama) |
| `evaluator` | Query evaluator and dynamic alpha selection |
| `intent` | Intent classification |
| `quality_gate` | Quality gate decision logic |
| `phase1`, `phase3` | Legacy groupings for CI phases |

### Unit Tests

Unit tests are fast, isolated component tests with all external services mocked. They're the first gate—run them constantly during development.

**Coverage:** 880 tests across intent classification, evaluator, quality gate, config validation, link verification, reranking, caching, embedding, and more. See `tests/unit/` for the full list.

**Runtime:** ~7 seconds total.

**Prerequisites:** None—everything is mocked.

**Best for:** Test-driven development, pre-commit validation, CI fast lane.

Run all unit tests:

```bash
PYTHONPATH=. pytest tests/unit/ -v
```

Skip unit tests when iterating on integration flows:

```bash
PYTHONPATH=. pytest tests/ -m "not unit" -v
```

### Integration Tests

Integration tests exercise real databases (Postgres, OpenSearch) and the HTTP/WebSocket API stack. They verify pipeline correctness, conversation state management, suggestion typeahead, and edge cases.

**Coverage:** Pipeline flow (classifier → evaluator → retriever → reranker → quality gate → agent), hybrid search with RRF fusion, quality gate retry logic, conversation CRUD, WebSocket lifecycle, `/api/suggest` typeahead, and admin enrichment routes.

**Runtime:** 5–60 seconds depending on which tests are selected.

**Prerequisites:**

1. Start Docker services from the repo root:

   ```bash
   docker compose up -d    # PostgreSQL + OpenSearch
   ```

2. Verify services are up:

   ```bash
   curl http://localhost:9200/_cluster/health
   PGPASSWORD=postgres psql -h localhost -U postgres -d langchain_agent -c 'SELECT 1;'
   ```

3. Confirm Ollama is running and the required models are pulled:

   ```bash
   curl http://localhost:11434/api/tags
   ```

**Running integration tests:**

```bash
PYTHONPATH=. pytest tests/integration/ -v
```

**Skip long-running tests for rapid iteration:**

```bash
PYTHONPATH=. pytest tests/integration/ -m "integration and not slow" -v
```

**CI note:** `make ci` only runs `pytest --collect-only` on integration tests to catch import errors without needing live services. Always run the actual test suite locally before pushing to main.

### End-to-End Tests

E2E tests drive a real running backend via HTTP and WebSocket to validate the complete system: health checks, authentication, and pipeline correctness across all six intents.

**Test files:**

- `test_deployment_smoke.py` — health, auth, intent coverage, citations, latency budgets (18 tests)
- `test_demo_queries_smoke.py` — regression guard for demo query scenarios (3 tests)

**Prerequisites:**

1. Start Docker services:

   ```bash
   docker compose up -d
   ```

2. Start the backend:

   ```bash
   cd langchain_agent
   make dev-api        # runs on :8000, stays in foreground
   ```

3. In another terminal, run E2E tests:

   ```bash
   PYTHONPATH=. pytest tests/e2e/ -v
   ```

**Environment variables:**

| Variable | Default | Purpose |
| ---------- | --------- | --------- |
| `CLOUD_RUN_URL` | `http://localhost:8000` | Backend URL under test |
| `TIMEOUT` | 30 | Pytest timeout in seconds |

**Smoke test (fast, single-query regression):**

```bash
make smoke            # part of `make check`
```

**Full regression suite (all intents + scenarios):**

```bash
bash scripts/smoke_local.sh    # ~90 seconds
```

**Intent coverage:**

Each of the six intent classes is tested: `search`, `comparison`, `attribute_filter`, `refinement`, `follow_up`, `summary`. The suite confirms each intent routes to the correct pipeline nodes and produces properly formatted responses with citations.

**Common issues:**

- **Connection refused** — backend not running. Verify: `curl http://localhost:8000/api/health`
- **403 on WebSocket** — origin header doesn't match allow-list. Check `api/middleware/origin_auth.py` for same-origin config.
- **Tests timeout** — increase `TIMEOUT=60`; check `logs/backend.log` for errors.
- **Data tests fail** — verify document count via `/api/health`; re-ingest with `bash scripts/lucille_ingest.sh` if empty.

### Frontend Tests

React component and hook tests run via Vitest and cover Zustand stores, WebSocket hooks, and observability components.

**Run frontend tests:**

```bash
cd langchain_agent/web
npm run test            # 290 tests
npm run test -- --watch
npm run test -- --coverage
```

### The Pre-Push Gate

Before pushing to `main`, run `make check` from `langchain_agent/`:

```bash
make check    # = make ci + make smoke
```

This runs:

1. `make ci` — linting (black, isort, flake8) + type-checking (mypy) + unit tests + frontend lint/build, all without live services.
2. `make smoke` — a single real search-intent e2e round-trip.

`make ci` alone is faster for iterative development; `make check` is the actual gate before pushing.

### ESCI Relevancy Benchmarks

The project includes a benchmark suite that measures retrieval quality on the Amazon ESCI dataset against ground-truth relevance judgments (65,028 queries in the shipped `esci_judgments` corpus). The benchmark compares three retrieval strategies on hard queries (bottom-quartile by standard-hybrid NDCG@10).

#### Benchmark Prerequisites

1. Clone the ESCI dataset to the repo root:

   ```bash
   cd /path/to/opensearch2026-agentic-search
   git clone https://github.com/amazon-science/esci-data.git ../esci
   ```

   Expected: ~1GB of parquet files.

2. Start Docker services from repo root:

   ```bash
   docker compose up -d    # PostgreSQL + OpenSearch
   ```

3. Verify OpenSearch is ready:

   ```bash
   curl -s http://localhost:9200/_cluster/health | python -m json.tool
   # Should return "status": "yellow" or "green"
   ```

4. Ingest products and judgments via Lucille ETL (one-time):

   ```bash
   cd langchain_agent
   bash scripts/lucille_ingest.sh    # full products ingest: ~35-40 min (embeds via Ollama)
   ```

   Expected: 158,637 products indexed to `agentic_hybrid_search_docs`, 65,028 queries with judgments in `esci_judgments`.

Verify:

```bash
curl -s http://localhost:9200/esci_judgments/_count | python -m json.tool
```

#### Running Benchmarks

**Fast reproducible benchmark (deterministic, no LLM):**

```bash
cd langchain_agent
make benchmark-esci-fast    # ~5 minutes for 5000 queries
```

Uses intent fast-path alpha table; no LLM calls. Reproducible and suitable for iterative tuning.

**Full adaptive benchmark (with LLM intent classification):**

```bash
cd langchain_agent
make benchmark-esci         # requires a running local Ollama server
```

Calls the local LLM for intent classification; results vary slightly by model version.

**Dry-run (sanity check):**

```bash
cd langchain_agent
PYTHONPATH=. python benchmarks/benchmark_esci.py --limit 2 --fast    # ~10 seconds
```

**Save results to JSON:**

```bash
cd langchain_agent
PYTHONPATH=. python benchmarks/benchmark_esci.py --limit 5000 --hard-only --fast \
  --output benchmark_results_$(date +%Y%m%d_%H%M%S).json
```

#### Benchmark Results

**Last Run:** 2026-04-30, 5000 queries, fast mode (deterministic, no LLM)

Hard queries: 1250 / 5000 (bottom-quartile NDCG@10 ≤ 0.2393)

| System | NDCG@10 | MRR | Recall@20 | Notes |
| -------- | --------- | ----- | ----------- | ------- |
| Lexical (BM25 only) | 0.1316 | 0.2139 | 0.1703 | Retrieval floor (α=0.0) |
| Standard Hybrid | 0.1860 | 0.2938 | 0.2779 | Reference baseline (α=0.25, RRF, no reranking) |
| Adaptive | 0.2107 | 0.3307 | 0.2978 | Full system (intent-driven α + reranker + quality gate) |

**Improvement over standard hybrid:**

- Adaptive: +13.3% NDCG@10, +12.6% MRR, +7.2% Recall@20

**Full-set results (all 5000 queries):**

| System | NDCG@10 | MRR | Recall@20 |
| -------- | --------- | ----- | ----------- |
| Lexical | 0.3310 | 0.4910 | 0.3691 |
| Standard Hybrid | 0.3802 | 0.5347 | 0.4160 |
| Adaptive | 0.3897 | 0.5467 | 0.4243 |

Results are stable across 1K–5K scale with <0.3% variance.

#### Methodology

**Lexical floor (α=0.0):** Pure BM25 retrieval, no semantic/vector component, no reranking.

**Standard hybrid (α=0.25):** Hybrid search with 60% BM25 / 40% vector (RRF fusion), k=20 candidates, no reranking.

**Adaptive (production):** Intent → alpha mapping (deterministic fast-path table or LLM-based), hybrid search with intent-specific alpha, cross-encoder reranking (top-20), quality gate retry with α ± 0.3 if max score < 0.45.

All three systems:

- Use the same retrieval candidate pool (fetch_k=40)
- Measure identical metrics (NDCG@10, MRR, Recall@20)
- Evaluate on the same 5000 queries with ground truth

#### Reproducing Results

1. Ensure ESCI dataset is cloned to `../esci/`
2. Services running: `docker compose up -d`
3. Products + judgments ingested: `bash scripts/lucille_ingest.sh`
4. Verify OpenSearch: `curl http://localhost:9200/esci_judgments/_count`
5. Dry-run: `PYTHONPATH=. python benchmarks/benchmark_esci.py --limit 2 --fast`
6. Full run: `make benchmark-esci-fast` (~5 min)
7. Results print to stdout
8. (Optional) Save JSON: `--output results.json`

#### Sliding Scale: Query Count vs Runtime

- `--limit 100`: ~30 seconds
- `--limit 500`: ~2 minutes
- `--limit 1000`: ~4 minutes
- `--limit 5000`: ~5 minutes (Makefile default)
- All 65K: (TODO: re-measure on the new corpus)

#### Benchmark Troubleshooting

| Issue | Fix |
| ------- | ----- |
| `ModuleNotFoundError: No module named 'config'` | Run with `PYTHONPATH=.` |
| `ConnectionError: Error connecting to OpenSearch` | Run `docker compose up -d` from repo root |
| `lookup_judgments returned None` | Normal—queries need exact matches in esci_judgments index |
| `CrossEncoderReranker warmup failed` | Model auto-downloads from HuggingFace (~100MB), retry |
| Ollama unreachable / model not pulled | Confirm `curl http://localhost:11434/api/tags`, or use `--fast` flag to skip LLM calls |
| Benchmark takes >30 min | Use `--limit 1000` to sample fewer queries |

### Common Test Issues

#### Tests hang or time out

Verify services are running:

```bash
docker compose ps
curl http://localhost:9200/_cluster/health
PGPASSWORD=postgres psql -h localhost -U postgres -d langchain_agent -c 'SELECT 1;'
```

Pytest has a 30-second default timeout (`pytest.ini`). Mark longer tests with `@pytest.mark.slow` or raise it via `--timeout=N`.

#### `ModuleNotFoundError: No module named 'config'`

Set `PYTHONPATH=.`:

```bash
PYTHONPATH=. pytest tests/
```

#### Integration tests skipped

Start Docker services and backend:

```bash
docker compose up -d
./scripts/start.sh
```

#### E2E tests failing with 403

Check your backend URL (defaults to `http://localhost:8000`) and verify the `Origin` header matches the allow-list in `api/middleware/origin_auth.py`. There's no login gate—same-origin checking is the only auth layer.

### Writing New Tests

For unit tests, mock all external services:

```python
# tests/unit/my_module/test_my_thing.py
import pytest
from my_module import MyThing

class TestMyThing:
    def test_valid(self):
        assert MyThing(42).value == 42

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            MyThing(-1)
```

For integration tests, use the `compiled_graph` fixture and mark with `@pytest.mark.integration`:

```python
# tests/integration/test_my_flow.py
import pytest

@pytest.mark.asyncio
@pytest.mark.integration
class TestMyFlow:
    async def test_end_to_end(self, compiled_graph):
        result = await compiled_graph.ainvoke({"messages": [("user", "hi")]})
        assert result["messages"]
```

Always mark new tests with the appropriate markers so scope-based runs pick them up correctly.

---

## Contributing & Dev Workflow

This chapter covers how to contribute code to Agentic Hybrid Search, including essential code patterns and the current development workflow.

### Code Patterns & Conventions

Before you start coding, familiarize yourself with these patterns — they're enforced by `make check` and tested by the CI suite.

#### PYTHONPATH Requirement

All Python invocations from `langchain_agent/` must set `PYTHONPATH=.`:

```bash
# ✓ Correct
PYTHONPATH=. pytest tests/unit/
PYTHONPATH=. python main.py
PYTHONPATH=. black .

# ✗ Wrong — will fail with ModuleNotFoundError
pytest tests/unit/
python main.py
```

Modules use bare imports like `from config import ...` instead of relative imports. Setting `PYTHONPATH=.` allows Python to resolve `config` as a module in the current directory.

**Set once per session:**

```bash
export PYTHONPATH=.
pytest tests/unit/
python main.py
```

#### State Access

`CustomAgentState` is a `TypedDict` with `total=False`. Only `messages` is guaranteed to exist. Always use `.get()` with a default:

```python
# ✓ Correct
intent = state.get("intent")
confidence = state.get("confidence", 0.5)
alpha = state.get("alpha", 0.25)

# ✗ Wrong — KeyError if field doesn't exist
intent = state["intent"]
```

See `core/agent_state.py` for the full list of fields by pipeline node.

#### Exception Hierarchy

All custom exceptions inherit from `AgenticHybridSearchError` (defined in `core/exceptions.py`). Never catch bare `Exception`:

```python
from core.exceptions import (
    AgenticHybridSearchError,
    SearchTimeoutError,
    RetrievalError,
)

# ✓ Correct
try:
    results = retriever.search(query, timeout=5)
except SearchTimeoutError as e:
    logger.warning("Search timed out after 5s", exc_info=True)
    # Decide: retry with longer timeout, or fail
except RetrievalError as e:
    if e.recoverable:
        # Retry with fallback strategy
    else:
        raise
except AgenticHybridSearchError as e:
    logger.error(f"Search failed: {e}")
    raise

# ✗ Wrong — silently hides bugs
except Exception:
    pass
```

#### Event Parity (Backend & Frontend)

Backend events in `api/schemas/events.py` must match frontend types in `web/src/types/events.ts`. Every return path from agent nodes must include a `"citations"` key (empty list if none). Event parity is verified by `test_frontend_backend_event_parity.py`.

#### Auth Patterns

There is no login gate — same-origin checking is the app's only auth layer. Wire new routes through `verify_same_origin` (from `api/middleware/origin_auth.py`), never through `verify_api_key` (which doesn't exist; issue #135 removed it entirely). `verify_admin_token` is available as an opt-in credential check for unattended automation, but no route wires it in today.

#### Logging & Comments

Use structured logging via the standard `logger`:

```python
import logging
logger = logging.getLogger(__name__)

# ✓ Correct
logger.warning("Search timed out", extra={"query": query, "timeout_ms": 5000})

# ✗ Wrong
print("Search timed out")  # No structure
logger.warning(f"Timeout: {query}")  # Brittle string formatting
```

Write comments for **why**, not **what**. Code should be self-documenting:

```python
# ✓ Correct — explains the non-obvious reasoning
# LLM content can arrive as a list-of-content-blocks; flatten to string for state
text = _flatten_llm_content(llm_response)

# ✗ Wrong — just repeats what the code does
# Flatten the LLM response
text = _flatten_llm_content(llm_response)
```

No docstrings for internal functions. Only add them for public APIs.

#### No Over-Engineering

Don't add error handling, fallbacks, or abstractions for scenarios that can't happen. Trust internal code and framework guarantees:

```python
# ✓ Correct — only validate at system boundaries
query = request.json["message"]
if not query:
    raise ValueError("Message required")

# But don't validate internally
alpha = state.get("alpha")  # Trust that retriever set it
# No need to check: if not isinstance(alpha, float)
```

### Development Workflow

This repo follows a "cowboy mode" workflow as of 2026-09-15: commits go directly to `main`. There is no branch protection (private repo, no GitHub Pro — confirmed via GitHub API), no CI/CD pipeline (issues #113 and #110 removed GitHub Actions workflows and the deploy step entirely), and no pull request requirement by default.

⚠️ **DRIFT:** `docs/contributing/README.md` (§ Contribution Flow) and `docs/contributing/pr-process.md` describe an older PR-based workflow (feature branch, PR, CI checks, required reviewer) that no longer reflects how this repo is actually worked on. The rest of those files (branch naming conventions, commit message format, testing) remain useful reference material, but ignore the PR flow and review process they describe. The current workflow is below.

#### The Current Workflow: Code Directly to Main

1. **Get issue context** — use `workflow-start` skill to retrieve the GitHub issue, understand scope, and plan

   ```bash
   /workflow-start
   ```

   This fetches issue details, helps you restate scope, and prepares you to code. It's optional for obvious fixes.

2. **Make changes — directly on `main`** — edit existing files first; create new files only when the task explicitly requires it

   ```bash
   git status                    # Verify main is clean and up to date
   # Edit code...
   git add <file>
   git commit -m "feat: <description>"
   ```

   **Commit message format:** `<TYPE>: <description>` where TYPE is one of:
   - `feat:` — new feature
   - `fix:` — bug fix
   - `docs:` — documentation
   - `refactor:` — code cleanup
   - `chore:` — maintenance

   Include `Closes #<N>` in the commit message to auto-close the issue when pushed:

   ```text
   feat: add refinement intent support

   - Detects "refinement" queries that narrow prior results
   - Validates category overlap; requests clarification if <0.3
   - Adds 18 unit tests

   Closes #42.
   ```

3. **Run local tests** — before pushing, verify everything passes locally

   ```bash
   cd langchain_agent
   make check     # Full gate: lint + format + unit tests + frontend + smoke
   ```

   For faster iteration while coding:

   ```bash
   make ci        # Faster: lint + format + unit tests (no Docker/smoke)
   ```

   If tests fail, fix and repeat. There is no CI or reviewer to catch failures after push — you are responsible.

4. **Self-review your diff** — run the pre-push checklist via `workflow-check` skill

   ```bash
   /workflow-check
   ```

   This skill guides you through:
   - Verifying your commits align with the plan
   - Confirming `make check` passes
   - Reading your full diff end-to-end (spot dead code, stale comments, security issues)
   - Updating `CLAUDE.md` and project memory if you discovered something non-obvious
   - **Critical:** Step 6 (update docs/memory) is the most commonly skipped step and causes stale guidance. Do not cut this corner.

5. **Push to `main`**

   ```bash
   git push origin main
   ```

   No branch protection exists to gate the push. Your local `make check` and the checklist in step 4 are the only gates.

6. **Verify locally and close the issue** — use `workflow-deploy` skill

   ```bash
   /workflow-deploy
   ```

   This skill verifies your change works end-to-end (`make dev` brings up local Docker + backend + frontend), and closes the issue. If your commit message included `Closes #N`, GitHub auto-closes it once that commit lands on `main` (this works on direct pushes to the default branch, not just PR merges).

#### Can I Still Use a Feature Branch & PR?

Yes — nothing stops you from branching manually for something you explicitly want reviewed before it lands. This is opt-in, not the default:

```bash
git checkout -b feat/issue-NNN-slug
# ... code, test, commit ...
git push origin feat/issue-NNN-slug
gh pr create --draft         # Or without --draft to go straight to ready
```

A reviewer can then review your diff and suggest changes before you push to `main`. This is useful for architectural decisions, large refactors, or when you want a second opinion. Just know that the repo provides no enforcement — it's purely opt-in.

#### Branch Naming (Reference)

If you do create a feature branch, use this format: `<type>/<issue-number>-<slug>`

| Type | When | Example |
| ------ | ------ | --------- |
| `feat/` | New feature | `feat/issue-42-refinement-intent` |
| `fix/` | Bug fix | `fix/issue-28-swagger-localhost` |
| `docs/` | Documentation | `docs/contributing-guide` |
| `refactor/` | Code cleanup | `refactor/simplify-auth` |
| `chore/` | Maintenance | `chore/upgrade-langchain` |

Use kebab-case for the slug, keep the full name under 50 chars.

### Testing Strategy for Contributions

All code changes must pass tests locally before pushing. Run the test suite from `langchain_agent/`:

```bash
# Full gate (required before pushing)
make check              # lint + format + unit tests + frontend + smoke (integration/e2e only get --collect-only)

# For iterative development
make ci                 # Fast check: lint + format + unit + frontend (no Docker, no smoke)

# By tier
PYTHONPATH=. pytest tests/unit/                   # ~0.5s, no services
PYTHONPATH=. pytest tests/integration/            # needs Postgres + OpenSearch
PYTHONPATH=. pytest tests/e2e/                    # full system
PYTHONPATH=. pytest tests/ -m phase1              # by pytest marker

# Single test
PYTHONPATH=. pytest tests/unit/test_foo.py::test_bar -v
```

**Local git hooks:** `.git/hooks/pre-commit` (installed by `scripts/setup.sh` from `scripts/pre-commit.sh`) runs black/isort/flake8 on *staged* `.py` files only — mirrors the linting in `make ci`. There is no pre-push hook that runs tests — that's your responsibility to do manually before pushing.

### Code Review Checklist (Self-Review)

Before pushing, audit your own changes:

- [ ] **No dead code** — remove unused variables, functions, imports
- [ ] **No stale comments** — comments should explain why, not what
- [ ] **Event parity** — if you touched events, frontend types match backend
- [ ] **Auth pattern** — new routes use `verify_same_origin`, never `verify_api_key`
- [ ] **PYTHONPATH** — all test commands include `PYTHONPATH=.`
- [ ] **Exception handling** — no bare `except Exception`, use subclasses
- [ ] **State access** — use `.get()` on `CustomAgentState`, not `[]`
- [ ] **Env vars** — if you added config, it's documented in `.env.example`
- [ ] **Tests** — new code has unit tests; integration tests if multi-component

### Never Force-Push Main

Even in cowboy mode, fix a bad push with `git revert`, not history rewriting:

```bash
# ✓ Correct
git revert <commit-sha>
git push origin main

# ✗ Wrong — never do this
git push --force
```

### Getting Help

- **Architecture questions**: See `ARCHITECTURE.md` and check function docstrings
- **Tech stack, patterns, commands**: Refer to `CLAUDE.md` (source of truth for this project)
- **Testing guidance**: See `tests/README.md` and `docs/contributing/testing.md`
- **Code patterns**: See `docs/contributing/code-patterns.md` and `langchain_agent/CONTRIBUTING.md`
- **Debugging**: Enable `LANGSMITH_API_KEY` for tracing at <https://smith.langchain.com>

---

## Data & ESCI Ingestion

### About the ESCI Dataset

Your system uses the **ESCI dataset** from Amazon Science — a large-scale, annotated e-commerce product search collection. The dataset contains real Amazon product listings paired with human relevance judgments for search queries, making it ideal for evaluating and benchmarking search agents in a realistic e-commerce context.

The data comes in two parts:

1. **Products** — The full corpus of 158,637 real Amazon products (every judged product of the ESCI US `test` + `small_version` queries, built query-first), each with a title, brand, color, and other text fields. The parquet is text only — no precomputed vectors; embeddings are generated at ingest time via Lucille's `OllamaEmbedStage` (`nomic-embed-text`, 768-dim).
2. **Relevance judgments** — 65,028 queries with human-annotated relevance labels showing which products are relevant to each query, using a 4-point scale: Exact (4.0), Substitute (1.0), Complement (0.1), and Irrelevant (0.0).

Both files are stored in Parquet format (a compressed columnar format) and committed to the repository using Git LFS (Large File Storage).

### Data Directory Layout

⚠️ **DRIFT NOTE**: an earlier revision of this section put the data directory under `langchain_agent/data/` — it's actually at the **repo root**, `data/` (sibling to `langchain_agent/`, not inside it), per `DATA_DIR="$REPO_DIR/data"` in `scripts/lucille_ingest.sh`:

```text
data/                                  # repo root, NOT langchain_agent/data/
├── esci_products.parquet
│   └─ 158,637 product documents with title, brand, color (text only, no vectors)
├── esci_judgments_aggregated.parquet
│   └─ 65,028 queries with relevance judgments for evaluation
└─ (no taxonomy files here — see "Attribute Detection & Taxonomy" below)
```

Both files are **automatically** pulled when you clone the repo if you have Git LFS installed (`git lfs install`). If the files are missing locally, run:

```bash
git lfs pull
```

Each file is approximately 64 MB (products) and 23 MB (judgments) due to Snappy compression.

### The Lucille Ingestion Pipeline

Your system uses **Lucille**, a highly configurable ETL (Extract, Transform, Load) framework built and maintained by KMW Technology, to ingest these data files into OpenSearch. Lucille is not part of this repository — it's an external dependency — but the configuration for ESCI-specific ingestion lives in `langchain_agent/lucille-esci/`.

The lucille-esci directory is a Maven configuration package (not Lucille's source code) that:

- Defines OpenSearch field mappings and analyzers for products and judgments
- Specifies transformation rules (HOCON configuration files)
- Bundles custom Java stages for attribute detection and brand normalization

**Key directories:**

```text
langchain_agent/lucille-esci/
├── conf/
│   ├── products.generated.conf    # Generated (not committed) — see "Generated Configuration" below
│   └── judgments.conf             # Static: maps E/S/C/I → 4.0/1.0/0.1/0.0
├── mapping/
│   ├── opensearch_mapping.json    # Field types: knn_vector, text, keyword fields
│   └── judgments_mapping.json     # Judgment index schema
├── pom.xml                        # Maven coordinates
├── src/main/java/com/kmwllc/esci/
│   ├── AttributeDetectorStage.java
│   └── BrandNormalizerStage.java
└── target/                        # Compiled artifacts (auto-generated)
```

#### Generated Configuration

The file `conf/products.generated.conf` is **generated by Python** before every ingest run — it's not committed to git. The script `langchain_agent/config_generator.py` creates it dynamically, based on:

- A fixed prelude/epilogue that configures the index name, analyzers, and field definitions
- One `AttributeDetectorStage` block for each attribute type (color, waterproof) currently registered in your OpenSearch cluster

This dynamic generation allows the ingest pipeline to adapt to new attribute types as they're discovered and added to OpenSearch at runtime.

**Key fields in the generated config:**

- `indexName = "agentic_hybrid_search_docs"` — products are indexed here
- `analyzerName = "multilingual_analyzer"` — text analysis across languages
- `collection_id = "esci_products"` — set on every product doc (required by all retrieval queries to filter)
- `knn_vector.dimension = 768` — matches your embeddings and configuration

#### Field Mappings

OpenSearch expects specific field types. The mapping template in `mapping/opensearch_mapping.json` defines:

- `knn_vector` — 768-dimensional HNSW vector index for semantic search
- `product_title`, `product_brand`, `product_color` — both text (full-text search) and keyword (faceting) mappings
- `title_suggest`, `brand_suggest` — edge-ngram fields for autocomplete typeahead
- `product_color_primary`, `product_color_secondary`, `product_waterproof_primary`, `product_waterproof_secondary` — added during ingest by attribute detection (see below)
- `product_brand_normalized` — lowercased brand names added during ingest

### Running the Ingestion

The ingestion script is `langchain_agent/scripts/lucille_ingest.sh`. Always run it from the `langchain_agent/` directory:

```bash
cd langchain_agent
bash scripts/lucille_ingest.sh
```

**What happens (default Docker path):**

1. Builds a custom Docker image layering your attribute-detection code onto the public Lucille base image (~1 min on first run, ~10 s cached)
2. Regenerates `conf/products.generated.conf` via `config_generator.py`
3. Runs Lucille products ingest: reads `data/esci_products.parquet`, applies transformations, embeds each document through Ollama's `nomic-embed-text` (`OllamaEmbedStage`), bulk-indexes into OpenSearch (full ~158K-product run: ~35-40 minutes on an M4 Max)
4. Runs Lucille judgments ingest: reads `data/esci_judgments_aggregated.parquet`, indexes into `esci_judgments` for ground-truth lookups

You don't need to install Java or Maven locally — the Docker path is the default and requires only Docker Desktop. Lucille reaches the host's Ollama server via `host.docker.internal` (the script translates a `localhost` `OLLAMA_HOST` automatically).

**Common options:**

- `bash scripts/lucille_ingest.sh --reset-index` — Atomically recreates the index (use this if you want a clean slate)
- `bash scripts/lucille_ingest.sh --skip-judgments` — Ingest products only
- `bash scripts/lucille_ingest.sh --skip-products` — Ingest judgments only (rarely needed)

The ingestion is **idempotent** — running it multiple times is safe and won't duplicate data.

### Attribute Detection & Taxonomy

During ingestion, Lucille runs two custom Java stages to enrich product documents:

**Attribute Detection** — The `AttributeDetectorStage` scans the `chunk_text` (a concatenation of title, brand, and color) for known color and waterproof variants. If it finds a match, it writes canonical values to `product_color_primary`, `product_color_secondary`, `product_waterproof_primary`, and `product_waterproof_secondary`. This normalization improves filter recall — queries for "blue headphones" match all shades of blue (Navy, Cyan, Teal) using the canonical mapping.

**Brand Normalization** — The `BrandNormalizerStage` lowercases brand names and writes them to `product_brand_normalized`, ensuring case-insensitive brand filtering.

Both stages run during ingest, in a single pass through the pipeline — no separate post-processing step.

#### The Taxonomy Store

The color and waterproof mappings (variant → canonical value, e.g., "grey" → "gray") live in OpenSearch itself, in a separate index called `agentic_hybrid_search_attribute_mappings`. They are **not** committed to git — the taxonomy is a runtime artifact that your system grows and refines as it learns from search interactions.

On a **fresh cluster**, the taxonomy store is empty. The attribute-detection stages will fail to ingest if they can't load the taxonomy (hard failure by design — silent degradation is not an option). To populate the initial taxonomy, run:

```bash
cd langchain_agent
make seed-taxonomy
```

This is **destructive** — it erases any mappings the agent has learned at runtime and rebuilds the taxonomy from scratch by sampling product text. You typically run this once per fresh cluster setup (it's automated by `scripts/setup.sh` on first-time setup). If you need to reset and rebuild the taxonomy later, `make seed-taxonomy` is the entry point.

**Growing the taxonomy:** At runtime, your agent can learn and add new mappings through the enrichment flywheel. When a shopper queries "navy blue headphones" and the system doesn't know "navy" maps to "blue", the agent can trigger enrichment to add the mapping, which then triggers a scoped re-tag (`REINDEX_TRIGGER=scoped`, the default) — re-detecting the attribute only on products whose text mentions the changed variant, measured live at well under a second to a few seconds — to apply the new rule. This keeps the taxonomy fresh without manual intervention, and without a full reindex.

### Ingestion Troubleshooting

**Docker image build fails:**

```bash
docker compose build lucille --no-cache
```

**Lucille ingest fails with "file not found":**

```bash
ls -lh ../data/esci_*.parquet     # repo-root data/, not langchain_agent/data/
# If missing, pull them via Git LFS:
git lfs pull
```

**Products are indexed but attribute fields are empty:**

Check that `conf/products.generated.conf` was regenerated correctly and that the taxonomy is loaded:

```bash
# Regenerate the config:
cd langchain_agent
python config_generator.py
```

Then check your OpenSearch cluster:

```bash
# Verify the taxonomy index exists and has content:
curl -u elastic:password http://localhost:9200/agentic_hybrid_search_attribute_mappings/_doc/_search | jq '.hits.hits | length'
```

If the taxonomy is empty, run `make seed-taxonomy`.

**OpenSearch connection fails during ingest:**

Check your `.env` file for the correct host and port:

```bash
grep OPENSEARCH_HOST langchain_agent/.env
grep OPENSEARCH_PORT langchain_agent/.env
```

The default is `http://localhost:9200`. Ensure OpenSearch is running:

```bash
docker compose ps  # Should show opensearch running
```

### Common Tasks

**Reindex all products with current configuration:**

```bash
cd langchain_agent
make reindex
# or:
bash scripts/lucille_ingest.sh --reset-index
```

**Reindex products only (skip judgments):**

```bash
cd langchain_agent
make reindex-products
# or:
bash scripts/lucille_ingest.sh --reset-index --skip-judgments
```

**Build a different product sample:**

The shipped `data/esci_products.parquet` is built query-first by
`langchain_agent/scripts/build_product_sample.py` from a full ESCI dataset
checkout. Embeddings are no longer precomputed offline — Lucille embeds
each document through Ollama's `nomic-embed-text` at ingest time
(`OllamaEmbedStage`), so regenerating the sample only requires re-running
that script against a fresh ESCI checkout and then re-running
`scripts/lucille_ingest.sh`; there is no separate batch-embedding step.

**Re-aggregate judgments (e.g., for a different locale):**

```bash
cd langchain_agent
PYTHONPATH=. python scripts/prepare_judgments_parquet.py --locale us --force
```

Then re-ingest:

```bash
bash scripts/lucille_ingest.sh --skip-products
```

**Check ingestion idempotency:**

Run the ingest twice. Document counts and embeddings should remain identical (no duplicates).

```bash
bash scripts/lucille_ingest.sh
bash scripts/lucille_ingest.sh
# Query OpenSearch to verify counts are stable
```

---

## Appendix A: Known Documentation Drift

While compiling this manual, each chapter was checked against the project's current, verified state (its root `CLAUDE.md`) rather than trusted blindly from source docs. The following discrepancies were found. None of them affect how the app actually works today — they're stale documentation, not stale code — but they're worth fixing at the source next time someone touches those files.

| # | Where | What's stale | Current, correct fact |
| --- | --- | --- | --- |
| 1 | `langchain_agent/README.md` (overview/tech-stack section, ~line 36-37) | Claims generation/classification models are "Gemini 3 Flash" / "Gemini 3.1 Flash Lite" | Actual models (per the same file's own Configuration section, root `README.md`, and `CLAUDE.md`) are **Gemini 2.5 Flash** (generation) and **Gemini 2.5 Flash-Lite** (classify/eval/judge) |
| 2 | `langchain_agent/api/README.md` (~line 25) | Lists the chat endpoint as `POST /api/chat (WebSocket)` | The actual route is `/ws/chat` — a WebSocket endpoint, not a POST route |
| 3 | `docs/integration/websocket.md` (example code) | Uses Cloud Run URLs (`wss://agentic-hybrid-search-XXXX.run.app`) | The only supported target is `ws://localhost:8000/ws/chat` — Cloud Run is a dormant, unused pattern (no deploy mechanism exists; see issues #110 and #113) |
| 4 | `CLAUDE.md`'s pytest marker list | Includes obsolete markers (`performance`, `load`, `stress`, `profile`) | Those markers belong to test files removed 2026-09-15; the current active marker set is the one listed in the [Testing & Benchmarks](#testing--benchmarks) chapter, sourced from `tests/README.md` |
| 5 | `docs/contributing/README.md` and `docs/contributing/pr-process.md` | Describe an older PR-based workflow (feature branch, draft PR, required reviewer, CI checks gating merge) | The repo switched to **"cowboy mode"** on 2026-09-15: commits go directly to `main`, no branch protection exists, there's no CI, and `make check` run locally is the only gate. A branch + PR is still allowed but is opt-in, not the default. See the [Contributing & Dev Workflow](#contributing--dev-workflow) chapter for the current process. |
| 6 | `langchain_agent/web/src/components/README.md` (project structure listing) | Lists a `LoginScreen.tsx` component and describes `ConversationsSidebar` as including "logout" | There is **no login gate** in this app — it was removed entirely (issue #135); same-origin checking is the sole auth layer (see [Authentication & Authorization](#authentication--authorization) in the API chapter, and the "no login screen" notes in the Setup and Demo chapters). `LoginScreen.tsx` and any logout affordance are most likely vestigial/dead code left over from before that removal — worth confirming and deleting if so, rather than treating as a working feature. |
| 7 | `langchain_agent/DEMO_QUERIES.md` | Describes example queries in a format the Demo-chapter source agent flagged as superseded | `langchain_agent/DEMO.md` (dated 2026-09-15) is the current, authoritative demo script — a **four-demo, nine-turn** scripted walkthrough (two main arcs plus two bonus scenes; see `web/src/demos/registry.ts`) driven by a **Next** button, not free-form querying. `DEMO_QUERIES.md` should be treated as historical/reference only. |

**How to use this table:** if you're the one who fixes stale docs, each row names the exact file and section to edit. None of these represent architecture or code that needs to change — only prose that hasn't caught up to it yet.

### Appendix A-2: Drift Found and Fixed in This Manual Itself (2026-09-19)

A follow-up pass checked this manual's *own* body text against the live codebase (not just other files), since the table above only ever audited outside sources. These were confirmed against source and corrected in place; listed here for the audit trail rather than left as open items:

| # | Chapter | What was stale | Fix landed |
| --- | --- | --- | --- |
| 8 | Using the App: Demo Walkthrough | Described only two story arcs plus one bonus (six or seven turns); the "Data Enrichment: Schema Evolution" (waterproof) demo from `web/src/demos/registry.ts` was missing entirely | Added the missing bonus section, corrected turn counts to four demos / nine turns throughout |
| 9 | Architecture Deep Dive | Pipeline diagram and "seven-stage" framing omitted the `summary` node and its routing entirely | Corrected to eight nodes; diagram and a new "Summary Node" subsection now show the `summary` branch |
| 10 | API & WebSocket Reference | Claimed no REST chat endpoint exists; claimed no rate limiting is enforced; allow-listed-origins list was stale | Documented the real `POST /api/chat` fallback, documented the actual `slowapi`-based rate limits (20/min chat, 10/min conversations) and added a 429 error section, corrected the origin allow-list |
| 11 | Frontend / Web UI | Project structure listed a `LoginScreen.tsx` and `ConversationsSidebar` with logout, neither of which exist; Vitest test count said 101/278, actual is 290 | Replaced the component listing with the real tree (`DemoSelector`, `NarratorPanel`, `demos/registry.ts`, etc.); corrected all test-count mentions |
| 12 | Testing & Benchmarks | Unit test count said 863; actual collected count is 880 | Corrected the count |
| 13 | Contributing & Dev Workflow | "Full gate" description implied `make check` runs the full integration/e2e suites | Corrected to note integration/e2e only get `--collect-only` under `make check`/`make ci` |
| 14 | Data & ESCI Ingestion | Said data files live in `langchain_agent/data/`; actual location is repo-root `data/` (a sibling directory) | Corrected the path everywhere it appeared, including two commands that would have failed as originally written |
