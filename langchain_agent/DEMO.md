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
make dev            # Docker + Langfuse + backend + frontend
make demo-reset     # ARM ARC 2 — see below
```

Open <http://localhost:5173>. There is no login screen.

**Arming matters.** Arc 2 works because the catalog mis-files tan boots under
yellow. Running it *fixes* that, so a second run has nothing to demonstrate —
it does not error, it just quietly stops being a demo. `make demo-reset` puts
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
| Demo dropdown | Switches arcs. Selecting arc 2 re-arms it. |

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
| 3 | `what about trail running?` | search | **0.70** semantic-heavy | none | 0.998 |

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
**real Lucille re-index of all 9,618 products** runs. The elapsed counter ticks
the whole way — this is the ingest pipeline running, not a cached swap. It takes
about **20 seconds**; talk over it.

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

> **Heads-up:** turn 3 can sit on "Checking whether a tool is needed" for ~30s
> before streaming — longer than any other turn, because the correction is now in
> the conversation history for the tool-offer call to reason about. The status
> card says what it is doing. Have a sentence ready.

---

## What not to claim

Each of these was tested; the measurements are in the commit history.

- **Never mention price, cost, or budget.** The catalog has **no price field in
  any form**. The agent is instructed to refuse and redirect. An invented dollar
  figure is the worst thing this demo could put on a screen.
- **Do not say dynamic alpha makes the results better.** It provably changes the
  *ranking*, but at α 0.25 the first page of "blue running shoes" includes blue
  *jeans*, while a pure-semantic run of the same query returns five actual
  running shoes. Alpha is *how literally it read the question*, not a quality
  win. **The reranker** is what removes the jeans.
- **Do not promise a quality-gate retry, or a recovery.** Neither arc triggers
  one: every turn passes on the first attempt. When the gate does fire elsewhere
  it is usually because the catalog genuinely has nothing, and extra candidates
  cannot invent a product.
- **Do not promise a reshuffled product list in arc 2 turn 3.** The honest proof
  is the filter value.

---

## Q&A

**What models?** Gemini 3 Flash for generation, Gemini 3.1 Flash Lite for
classification and query evaluation, `models/gemini-embedding-001` (768-dim) for
embeddings. Reranking is a **local cross-encoder** (`ms-marco-MiniLM-L-12-v2`),
not an LLM call — baked into the image, no added API latency.

**How does RRF fusion work?** Per document,
`score = 1/(rank_vector + 60) + 1/(rank_lexical + 60)`. Normalizes ranks from
both methods without needing probability calibration.

**Was that re-index real, or just the affected products?** The whole catalog — a
full Lucille run, ~20s for 9,618 products. A full reindex turned out to be fast
enough to run live, so there was no need for a narrower, less authentic
mechanism. On Cloud Run the same call dispatches `reindex.yml` and reports the
run URL (`REINDEX_TRIGGER`).

**Why didn't the quality gate catch the bug itself?** Because it is not a
failure by any tracked metric — it is a wrong-but-confident result, scoring 0.56
against a 0.45 threshold. Automated gap-detection here catches *zero-result* dead
ends; a silent mis-mapping has the opposite signature, a passing score. It needs
a person to look at it and say something.

**What stops the agent writing garbage into the taxonomy?** The canonical bucket
is validated against a fixed, bounded list per attribute type, so it cannot
invent a category; the correction path only overwrites an existing mapping when
a model explicitly supplies a different canonical after a dispute, so a casual
mention rewrites nothing; and the whole tool is behind `ENABLE_ENRICHMENT_TOOL`,
off by default.

**Beyond colour?** Yes — the same store, detection stage, and
`trigger_enrichment` tool cover material too, and the correction path is generic
over `attribute_type`. This script only walks colour end to end.

**Non-e-commerce domains?** Yes. Swap ESCI products for your own documents; the
pipeline is domain-agnostic.

**Conversation memory?** LangGraph checkpoints in PostgreSQL. Long chats get
context compaction.

**Latency?** Intent 10–500ms → query eval 10–500ms → retrieval 200–500ms →
reranking 1–2s → agent 3–8s. Roughly 6–15s per turn, and you will see the agent
step dominate.

**Index size?** Amazon ESCI (~1.2M US products); the demo uses a 10K sample
(9,618 indexed) for fast setup.

---

## If something goes wrong

| Symptom | Fix |
|---|---|
| Arc 2 turn 1 shows no mismatch | The index is already corrected. **Restart**, or `make demo-reset`. |
| Next is disabled, reads "Connecting…" | The socket is not open yet. It enables itself; do not click through. |
| A reply looks attached to the wrong question | You clicked ahead. **Restart** and let each turn finish. |
| Backend slow or timing out | First query after a cold start pays model warm-up. Send one throwaway query before the room fills. |
| Frontend blank | `cd langchain_agent/web && npm run dev` |

**Shorter cut:** arc 2 alone is a complete story in about five minutes — the bug
that passes every check, the live repair, the proof. Open by saying you will
skip ahead to the hard case.
