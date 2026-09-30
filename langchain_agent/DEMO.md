# DEMO.md — Conference Walkthrough

Two arcs, six turns, about twelve minutes. Everything is driven by the **Next**
button; you never type a query.

> **The queries and the one-line "watch for" notes live in
> `web/src/demos/registry.ts`, and that file is the source of truth.** The app
> reads it; this document repeats it for the person holding the clicker. If you
> change one, change the other.

---

## Before you present

```bash
cd langchain_agent
make dev            # Docker services, dev backend :8080 + dev UI :5173, demo container :8000
./scripts/reset_demo_taxonomy.sh   # ARM ARC 2 — see below
```

Present from <http://localhost:5173> (the live dev UI) or from
<http://localhost:8000> (the same UI and backend built into one container by
`make dev`). Both run the same scripts; the container is frozen as of the last
`make dev`, so re-run it after any edit you want on stage. There is no login
screen.

**Start Docker first, and never let it cycle afterwards.** The backend opens its
PostgreSQL checkpointer pool once, at startup, and does not reopen it. If Docker
Desktop is not running when the backend starts — or is restarted underneath it —
the containers come back healthy but the backend does not: turn 1 dies with
`consuming input failed: server closed the connection unexpectedly`, which reads
like a frontend fault and is not one. There is no automatic recovery; restart the
backend. Confirm before you walk on stage that all three are answering:

```bash
curl -sf localhost:9200 >/dev/null && echo "opensearch ok"
curl -sf localhost:8080/api/health >/dev/null && echo "dev backend ok"
curl -sf localhost:5173 >/dev/null && echo "dev ui ok"
curl -sf localhost:8000/api/health >/dev/null && echo "demo container ok"
```

**Present at 1920x1080 or larger, fullscreen.** Browser chrome eats ~180px of
height; the narrator panel is laid out for what is left.

**Arming matters.** Arc 2 works because the catalog mis-files tan boots under
yellow. Running it *fixes* that, so a second run has nothing to demonstrate —
it does not error, it just quietly stops being a demo. `./scripts/reset_demo_taxonomy.sh` puts
the defect back in about a second. The **Restart** button in the header does it
for you, and selecting arc 2 re-arms it automatically, so you should never have
to think about this on stage. Verify if you want to be sure:

```bash
curl -s -XPOST localhost:9200/agentic_hybrid_search_docs/_search \
  -H 'Content-Type: application/json' \
  -d '{"size":0,"query":{"match_phrase":{"product_color":"tan"}},
       "aggs":{"c":{"terms":{"field":"product_color_primary"}}}}' | jq '.aggregations.c.buckets'
```

Armed looks like `yellow: 35`. Already-run looks like `brown: 29`.

---

## Driving it

| Control | What it does |
|---|---|
| **Next** | Fills and sends the next scripted turn. Click it and talk. |
| **Restart** | Clears the transcript, resets the narration, rewinds to turn 1, **and re-arms the index**. |
| **F2** | Full pipeline detail — raw DSL, per-node timings. For Q&A, not for the walkthrough. |
| Demo dropdown | Switches arcs (and the optional bonus scene — see below). Selecting arc 2 or the schema-evolution bonus re-arms it. |

The header reads **"Next up · Turn N of M"** — it names the query the button
will send, which during a running turn is one ahead of what is on screen.

**Wait for each turn to finish before clicking Next.** Clicking ahead queues the
message and its reply lands after the following question, which makes an answer
look attached to the wrong query. This is a known bug, not stage fright.

The right-hand panel narrates one line per pipeline stage, with gauges for the
two numbers that are positions on a range: **alpha** (exact words ↔ meaning) and
the **quality bar** (best match against the threshold it had to clear).

---

## Arc 1 — The shopper (3 turns, ~4 min)

One person, one conversation, narrowing the way people actually shop. Nothing
starts a new thread; nothing contradicts an earlier turn.

**The spine is alpha moving: 0.25 → 0.35 → 0.70.** The dial swings as the
questions get less literal, and nobody configured it per query.

| # | Query | Intent | α | Filters | Score |
|---|---|---|---|---|---|
| 1 | `Show me blue running shoes` | attribute_filter | **0.25** lexical-heavy | color: blue, feature: running | 0.97 |
| 2 | `only size 10` | refinement | **0.35** balanced | + feature: 10 | 0.95 |
| 3 | `what about trail running?` | refinement | **0.70** semantic-heavy | none | 0.998 |

**Turn 1 — it reads the question before answering it.**
Two of the words are real indexed attributes, so the filter line shows
`color: blue, feature: running` and alpha sits left of centre: there is
something concrete to match, so exact words carry more weight.

**Turn 2 — three words, and it keeps your place.**
A third filter appears and the results stay pinned to the products from turn 1.
The reply says so itself: *"From the 10 products I showed you earlier."* It
narrowed rather than searched again.

**Turn 3 — four words with no subject, colour, or size.**
Watch the **Query Rewriter** line: it turns `what about trail running?` into
*"Show me blue trail running shoes in size 10"*, carrying both earlier
constraints forward. Alpha jumps to 0.70 because this question is about purpose,
not a literal attribute.

> Ask the room to notice that nothing in turn 3 says "blue" or "size 10". The
> conversation supplied them.

---

## Arc 2 — The developer (3 turns, ~5 min) — the centerpiece

A different person: the developer who owns this catalog. Arc 1 showed the agent
improving how it *searches*. This shows it repairing the *data*.

### Turn 1 — `show me tan boots`

The filter resolves tan to **`color: yellow`**. This is a real shipped
mis-mapping affecting every product the catalog lists as Tan.

**Pause here.** The result **passes the quality gate — 0.56 against a bar of
0.45.** Nothing is broken by any metric the system tracks: the boots really are
relevant to "tan boots" in every respect except the colour bucket they are filed
under. That is why no automated check catches it.

The agent flags it in prose anyway: *"listed as Tan but indexed as yellow, which
looks like a tagging error."*

### Turn 2 — `that's not tan, that's tagged yellow which is wrong`

Use this phrasing. `"that's not"` is what trips the correction detector.

In order: the correction is detected, a second model approves the change, and a
**scoped re-tag** runs — `pipeline/scoped_retag.py` re-checks only the products
whose text mentions "tan" and re-detects their color, rather than a full
catalog reindex. The elapsed counter ticks briefly — measured live, it re-checks
905 products and re-tags 679 in under a second; talk over it.

It ends on **"Correction applied"** with the pair that makes the point:

```
✗ WAS   tan → yellow
✓ NOW   tan → brown
```

### Turn 3 — `show me tan boots` (new conversation, automatically)

Same question. The filter now reads **`color: brown`**.

**That field changing is the proof** — not the product list, which looks much the
same. The fix is in the data, permanent, for every future shopper.

The closing beat is what the agent *stops* saying: in turn 1 it volunteered a
tagging error; here it says nothing, because there is nothing left to flag.

> **Heads-up:** turn 3 can sit on the status card longer than other turns before
> streaming. Nothing is checking anything on this turn (it is a plain
> `attribute_filter` query); treat it as ordinary answer-generation latency and
> have a sentence ready.

---

## What not to claim

Each of these was tested; the measurements are in the commit history.

- **Never mention price, cost, or budget.** The catalog has **no price field in
  any form**. The agent is instructed to refuse and redirect. An invented dollar
  figure is the worst thing this demo could put on a screen.
- **Do not say dynamic alpha makes the results better.** Between 0 and 1 the
  fused query is identical (see the FAQ); at α 0.25 the first page of "blue running shoes" includes blue
  *jeans*, while a pure-semantic run of the same query returns five actual
  running shoes. Alpha is *how literally it read the question*, not a quality
  win. **The reranker** is what removes the jeans.
- **Do not promise a quality-gate recovery.** Arc 2 turn 2 *does* fire the gate
  and retry, and the retry *fails* — the narrator reads "Still under the bar
  after retrying — 0.30 against 0.45", directly above the correction card. Have
  a sentence ready, because it is on screen during your best moment. The honest
  one: *the shopper's complaint is not a product query, so there is nothing in
  the catalog that scores well against it — and the agent answers by fixing the
  data instead of by searching harder.* That 0.30 is the reranker's rescale
  ceiling for a uniformly-irrelevant batch, not a coincidence. No turn in either
  arc recovers after a failed gate; extra candidates cannot invent a product.
- **Do not promise a reshuffled product list in arc 2 turn 3.** The honest proof
  is the filter value.

---

## Bonus — schema evolution (optional, ~1 min)

Arc 2 shows the agent *correcting* a wrong tag — a shopper has to notice
and dispute it first. This shows the same taxonomy-growth machinery's other
shape: teaching the catalog a genuinely new filter dimension, unprompted.
`ENABLE_ENRICHMENT_TOOL` is already `true` in this repo's local `.env`, so
nothing extra to flip.

If there's time, select **"Data Enrichment: Schema Evolution"** from the
dropdown (this re-arms it — see below) and run both turns:

**Turn 1 — `Show me waterproof boots`**

Zero results. `product_waterproof_primary` genuinely doesn't exist yet on a
freshly-armed cluster (`WATERPROOF_CANONICALS` ships with zero seed
variants on purpose — see `retrieval/attribute_discovery.py`). Watch for
the agent to notice the gap **on its own** and call `trigger_enrichment` —
no shopper has to ask, unlike Arc 2. A scoped re-tag follows, same
elapsed-counter card as Arc 2's correction — measured live, it tagged 7,441
products in about 8 seconds.

> **If the model declines to call the tool this run:** it's a genuine
> per-turn LLM decision, not a scripted certainty — the turn just shows the
> gap and stops there. Re-running the turn (or re-selecting the demo, which
> re-arms it) is the recovery. Confirmed live across multiple consecutive
> runs, it calls the tool every time — but don't promise 100% on stage.

**Turn 2 — `Show me waterproof boots` (new conversation, automatically)**

Same query. The filter now reads `product_waterproof_primary: "waterproof"`
and real results come back (HI-TEC, OAKI, Columbia hiking/rain boots in the
live run that validated this). That's the proof — a filter dimension that
did not exist two minutes ago, permanent for every future shopper.

**Arming.** Like Arc 2, this demo consumes its own precondition — teaching
it "waterproof" once means the gap is gone on a second run. The shared
Restart/re-arm mechanism (`/api/admin/demo-reset`) now resets **both** Arc
2's color mapping and this demo's waterproof taxonomy unconditionally on
every call, so selecting either demo or hitting Restart re-arms whichever
one you're about to run — nothing presenter-facing changes.

---

## Q&A

**What models?** `qwen3.6:35b-a3b-q4_K_M` via local Ollama for generation,
classification, query evaluation, and judging — no cloud API key needed.
`nomic-embed-text` (768-dim) via Ollama for embeddings. Reranking is a
**local cross-encoder** (`ms-marco-MiniLM-L-12-v2`), not an LLM call — baked
into the image, no added latency.

**How are the two searches fused?** One OpenSearch `hybrid` query runs kNN and
BM25; a search pipeline min-max normalizes each score list and averages them
at equal weights. `alpha` switches to pure BM25 at exactly 0 and pure kNN at
exactly 1; in between the fused query is the same.

**Was that re-index real, or just the affected products?** Just the affected
products — a scoped re-tag (`pipeline/scoped_retag.py`) re-detects the
attribute only on products whose text mentions the changed variant and
bulk-updates just those, with no re-embedding. It's a real re-detection
against live OpenSearch, not a cached swap. There is no full-catalog
reindex mode any more — the corpus is a permanent precomputed export with
no rebuild path (see `data/README.md`).

**Why didn't the quality gate catch the bug itself?** Because it is not a
failure by any tracked metric — it is a wrong-but-confident result, scoring 0.56
against a 0.45 threshold. Automated gap-detection here catches *zero-result* dead
ends; a silent mis-mapping has the opposite signature, a passing score. It needs
a person to look at it and say something.

**What stops the agent writing garbage into the taxonomy?** The canonical bucket
is validated against a fixed, bounded list per attribute type, so it cannot
invent a category; the correction path only overwrites an existing mapping when
a model explicitly supplies a different canonical after a dispute, so a casual
mention rewrites nothing; a second, independent model call judges whether the
change would actually help shoppers before anything is written; and the whole
tool is behind `ENABLE_ENRICHMENT_TOOL` (off in code, on in this repo's `.env`).

**Beyond colour?** Yes — the same taxonomy store, scoped re-tag, and
`trigger_enrichment` tool cover waterproof too (see "Bonus — schema
evolution" above, which walks it end to end as a growth story), and the
correction path is generic over `attribute_type`.

**Conversation memory?** LangGraph checkpoints in PostgreSQL, one thread per
conversation; the `summary` intent summarizes from them on request.

**Latency?** See the table in ARCHITECTURE.md — roughly 6–21 s per turn, and
you will see answer generation and the judge dominate.

**Index size?** Amazon ESCI (~1.2M US products); the demo uses a corpus of
158,637 products — every judged product of the ESCI US test + small_version
queries.

---

## If something goes wrong

| Symptom | Fix |
|---|---|
| Arc 2 turn 1 shows no mismatch | The index is already corrected. **Restart**, or `./scripts/reset_demo_taxonomy.sh`. |
| Next is disabled, reads "Connecting…" | The socket is not open yet. It enables itself; do not click through. |
| A reply looks attached to the wrong question | You clicked ahead. **Restart** and let each turn finish. |
| Backend slow or timing out | First query after a cold start pays model warm-up. Send one throwaway query before the room fills. |
| Frontend blank | `./scripts/stop.sh && make dev`, then check `logs/frontend.log` |

**Shorter cut:** arc 2 alone is a complete story in about five minutes — the bug
that passes every check, the live repair, the proof. Open by saying you will
skip ahead to the hard case.
