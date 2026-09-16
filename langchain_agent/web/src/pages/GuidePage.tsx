/**
 * Guide for the Agentic Hybrid Search demo — the 3 scripted demos, the UI,
 * and how to read the pipeline output.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'

interface Section {
  id: string
  title: string
  content: React.ReactNode
}

export function GuidePage() {
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['intro']))
  const sectionRefs = useRef<Record<string, HTMLDivElement | null>>({})

  const toggleSection = useCallback((id: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }, [])

  const scrollToSection = useCallback((id: string) => {
    // Wait for the expand state-update to commit + paint before scrolling, so the
    // section's final laid-out offset (with content) is what we land on.
    window.setTimeout(() => {
      const el = sectionRefs.current[id]
      el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 60)
  }, [])

  const navigateToSection = useCallback(
    (id: string) => {
      // TOC navigation always opens the section (never toggles closed) and scrolls to it.
      setExpandedSections((prev) => {
        if (prev.has(id)) return prev
        const next = new Set(prev)
        next.add(id)
        return next
      })
      if (window.location.hash !== `#${id}`) {
        window.history.replaceState(null, '', `#${id}`)
      }
      scrollToSection(id)
    },
    [scrollToSection]
  )

  const sections: Section[] = [
    {
      id: 'intro',
      title: '🎯 Welcome to Agentic Hybrid Search',
      content: (
        <div className="space-y-4">
          <p className="text-gray-700">
            This is a production-grade AI-powered e-commerce product search agent — hybrid search (semantic + lexical),
            intelligent reranking, and real-time observability — presented through three scripted, projector-friendly
            demos rather than freeform chat. Pick one from the header and follow along; the "Demos" section below
            walks through each one.
          </p>
          <div className="bg-blue-50 border-l-4 border-blue-500 p-4">
            <h4 className="font-semibold text-blue-900 mb-2">Key Capabilities</h4>
            <ul className="text-blue-800 space-y-1 text-[1.375rem]">
              <li>✓ Natural language product search</li>
              <li>✓ Product comparison and attribute filtering</li>
              <li>✓ Real-time streaming responses with citations</li>
              <li>✓ Conversation memory and resumption</li>
              <li>✓ Per-query search optimization toggles (10 flags) — hybrid, fuzzy, synonyms, phonetic, phrase_boost, field_boost, typeahead, reranking, llm, llm_judge</li>
              <li>✓ Pipeline Quality Summary card — offline NDCG/MRR/Recall@20/Precision@10 vs an ESCI ground-truth baseline, with latency cost-benefit framing. Renders in two places: a card in the Details panel, and a "Ground Truth" tab in the Narrator panel</li>
              <li>✓ Full pipeline observability with real-time events</li>
            </ul>
          </div>
        </div>
      ),
    },
    {
      id: 'quickstart',
      title: '⚡ Quick Start',
      content: (
        <div className="space-y-4">
          <div className="space-y-3">
            <h4 className="font-semibold text-gray-900">1. Start the services</h4>
            <pre className="bg-[var(--color-stage-bg)] text-[var(--color-stage-ink)] p-3 rounded text-[1.375rem] overflow-x-auto">
              <code>cd langchain_agent{'\n'}make dev</code>
            </pre>
            <p className="text-[1.375rem] text-gray-600">This starts the API (port 8000) and frontend (port 5173)</p>

            <h4 className="font-semibold text-gray-900 mt-4">2. Open the UI</h4>
            <p className="text-[1.375rem]">Visit <a href="http://localhost:5173" className="text-blue-600 hover:underline">http://localhost:5173</a></p>
            <p className="text-[1.25rem] text-[var(--color-stage-ink-soft)] mt-1">The UI automatically detects the API URL: localhost:5173 connects to http://localhost:8000.</p>

            <h4 className="font-semibold text-gray-900 mt-4">3. Run a demo</h4>
            <p className="text-[1.375rem] text-gray-600">Pick a demo from the header dropdown, then click Next to run its first turn.</p>

            <h4 className="font-semibold text-gray-900 mt-4">4. Verify the setup (optional)</h4>
            <pre className="bg-[var(--color-stage-bg)] text-[var(--color-stage-ink)] p-3 rounded text-[1.375rem] overflow-x-auto">
              <code>cd langchain_agent{'\n'}make smoke</code>
            </pre>
            <p className="text-[1.375rem] text-gray-600 mt-1">Runs a focused smoke test to verify all components are working (~13-20s)</p>
          </div>
        </div>
      ),
    },
    {
      id: 'demos',
      title: '🎬 The Three Demos',
      content: (
        <div className="space-y-4">
          <p className="text-[1.375rem] text-gray-700">
            The header's demo selector picks between three scripted demos, each proving a different part of the
            pipeline. Pick one, follow its turns in order, and watch the Details panel for the numbers
            called out below.
          </p>

          <div className="border-l-4 border-blue-500 pl-4">
            <h4 className="font-semibold text-gray-900">Adaptive Query Enhancements</h4>
            <p className="text-[1.375rem] text-gray-600">
              One conversation, three turns that narrow the way a real shopper actually shops — no turn starts a
              new thread and no turn contradicts an earlier one. Watch alpha (the hybrid search dial) move as the
              questions get less literal: 0.25 → 0.35 → 0.70.
            </p>
            <ol className="list-decimal list-inside space-y-2 text-[1.375rem] text-gray-700 mt-2">
              <li>
                <code className="bg-gray-100 px-1">Show me blue running shoes</code> — alpha sits at 0.25,
                lexical-heavy. "blue" and "running" are real indexed attributes, so two filters appear: color:
                blue, feature: running.
              </li>
              <li>
                <code className="bg-gray-100 px-1">only size 10</code> — three words, and alpha nudges up to 0.35
                as a third filter (feature: 10) stacks on top of the first two. Results stay pinned to the same
                10 products from turn 1 — the reply says so directly ("From the 10 products I showed you
                earlier"). This is narrowing, not a fresh search.
              </li>
              <li>
                <code className="bg-gray-100 px-1">what about trail running?</code> — four words, no subject, no
                color, no size — and the query rewriter expands it to "Show me blue trail running shoes in size
                10", carrying both earlier constraints forward. Alpha jumps to 0.70, semantic-heavy, because the
                question is now about purpose rather than a literal attribute. Don't expect a specific intent
                label to be called out here — watch the filters compounding and the rewrite happening; that
                behavior is what holds up every run, not the classifier's name for it.
              </li>
            </ol>
            <p className="text-[1.25rem] text-[var(--color-stage-ink-soft)] mt-2">
              This catalog has no price field at all — every turn stays on attributes that actually exist (color,
              size, material, brand, feature).
            </p>
          </div>

          <div className="border-l-4 border-emerald-500 pl-4">
            <h4 className="font-semibold text-gray-900">Proving It With Real Judgments</h4>
            <p className="text-[1.375rem] text-gray-600">
              A standalone proof point, run separately from the two conversational arcs. One turn, one query that
              happens to have real Amazon ESCI relevance judgments behind it, so the Pipeline Quality Summary
              shows genuine graded metrics instead of its usual self-referential confidence proxy.
            </p>
            <ol className="list-decimal list-inside space-y-2 text-[1.375rem] text-gray-700 mt-2">
              <li>
                <code className="bg-gray-100 px-1">sewing machine</code> — the summary card switches to real
                NDCG@10 per stage: stock BM25 0.81 → BM25 0.91 → Hybrid 0.95 → Reranked 0.92. Every optimized
                stage clearly beats the plain-BM25 baseline — that's the point — but it isn't a clean climb
                straight to the top: reranked actually lands slightly below hybrid here. Graded against Amazon's
                own relevance judgments, not this system's own scoring.
              </li>
            </ol>
            <p className="text-[1.25rem] text-[var(--color-stage-ink-soft)] mt-2">
              Only 3 products are judged for this query — the sample corpus' judgment sets are sparse. The number
              is real; it isn't large.
            </p>
          </div>

          <div className="border-l-4 border-rose-500 pl-4">
            <h4 className="font-semibold text-gray-900">Classification &amp; Ingestion</h4>
            <p className="text-[1.375rem] text-gray-600">
              One bad catalog tag, fixed live, then proven fixed by searching again. This demo re-arms itself
              automatically each time you open it, since the fix it demonstrates consumes the very bug it's
              showing off.
            </p>
            <ol className="list-decimal list-inside space-y-2 text-[1.375rem] text-gray-700 mt-2">
              <li>
                <code className="bg-gray-100 px-1">show me tan boots</code> — the color filter resolves "tan" to
                "yellow", a real shipped mis-tagging affecting every product the catalog lists as tan. It passes
                the quality gate cleanly, which is the uncomfortable part: no automated check catches a
                wrong-but-mapped result.
              </li>
              <li>
                <code className="bg-gray-100 px-1">that's not tan, that's tagged yellow which is wrong</code> —
                the correction is detected, a second model approves the change, and a real Lucille re-index of
                9,618 products kicks off. Watch the elapsed-time counter — this is the actual ingest pipeline
                running, not a cached swap.
              </li>
              <li>
                <code className="bg-gray-100 px-1">show me tan boots</code> — the same query, asked again in a
                brand-new conversation (continuing the old thread would rewrite it down a lexical path instead of
                re-testing the fix). The filter now reads{' '}
                <code className="bg-gray-100 px-1">product_color_primary: "brown"</code> — that field changing is
                the proof: the fix is permanent, for every shopper after this one.
              </li>
            </ol>
          </div>
        </div>
      ),
    },
    {
      id: 'using-ui',
      title: '💬 Using the Chat UI',
      content: (
        <div className="space-y-4">
          <h4 className="font-semibold text-gray-900">The Layout</h4>
          <p className="text-[1.375rem] text-gray-600 mb-2">
            The header contains a demo selector, turn progress indicator (pips and query text), green Next button (for scripted turns), Restart button (clears conversation and re-arms the catalog), Details/Narration toggle (F2 keyboard shortcut), Guide link, and API reference/Swagger link. Below are two panels sized for a 1920×1080 projector — no resizable panes, no sidebar. There is no conversations list; each demo re-arms itself instead of letting you browse history.
          </p>
          <div className="grid grid-cols-2 gap-4 my-3">
            <div className="bg-gray-100 p-3 rounded">
              <p className="font-semibold text-[1.375rem]">Left: Chat</p>
              <p className="text-[1.25rem] text-gray-600 mt-1">Type questions, see streaming responses with citations</p>
            </div>
            <div className="bg-gray-100 p-3 rounded">
              <p className="font-semibold text-[1.375rem]">Right: Narrator / Details</p>
              <p className="text-[1.25rem] text-gray-600 mt-1">Watch the pipeline execute step-by-step; press F2 to toggle between narration (Narrator panel) and the full detail panel</p>
            </div>
          </div>

          <div className="space-y-2">
            <h4 className="font-semibold text-gray-900 mt-4">Tips for Best Results</h4>
            <ul className="space-y-1 text-[1.375rem] text-gray-700">
              <li className="flex gap-2"><span>💡</span> Use exact query strings in demo turns — several are crafted for specific behaviors (e.g., "show me tan boots" for the taxonomy demo, "sewing machine" for ground-truth metrics)</li>
              <li className="flex gap-2"><span>🎯</span> Avoid asking about price — there is no price field in this catalog. Focus on attributes like color, size, material, brand, and feature</li>
              <li className="flex gap-2"><span>🔄</span> The taxonomy demo re-arms itself automatically on selection, restoring the original tan→yellow mis-tag so the turn-1 failure is fresh every time</li>
              <li className="flex gap-2"><span>📋</span> Click citations to see full product details on Amazon</li>
              <li className="flex gap-2"><span>⚙️</span> Watch the Narrator/Details panel to understand why results were ranked this way and what the Pipeline Quality Summary shows</li>
            </ul>
          </div>
        </div>
      ),
    },
    {
      id: 'search-optimizations',
      title: '🎛️ Search Optimization Toggles',
      content: (
        <div className="space-y-4">
          <p className="text-[1.375rem] text-gray-700">
            The Details panel exposes 10 per-query toggles that flip individual search features on or off. Changes apply to the <em>next</em> query you send and the panel reflects what actually ran (skipped stages collapse).
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[1.375rem]">
            <div className="bg-gray-50 p-2 rounded"><code className="font-mono text-gray-900">hybrid</code> — vector + BM25 fusion. Off ⇒ pure BM25.</div>
            <div className="bg-gray-50 p-2 rounded"><code className="font-mono text-gray-900">fuzzy</code> — adds <code>fuzziness: AUTO</code> to multi_match.</div>
            <div className="bg-gray-50 p-2 rounded"><code className="font-mono text-gray-900">synonyms</code> — query-time synonym expansion via the <code>english_analyzer</code>.</div>
            <div className="bg-gray-50 p-2 rounded"><code className="font-mono text-gray-900">phonetic</code> — adds <code>title_phonetic</code> / <code>brand_phonetic</code> fields.</div>
            <div className="bg-gray-50 p-2 rounded"><code className="font-mono text-gray-900">phrase_boost</code> — adds the <code>title_phrase</code> field with a 2.5× boost.</div>
            <div className="bg-gray-50 p-2 rounded"><code className="font-mono text-gray-900">field_boost</code> — keeps per-field <code>^N</code> weights. Off ⇒ all fields equal.</div>
            <div className="bg-gray-50 p-2 rounded"><code className="font-mono text-gray-900">typeahead</code> — frontend autocomplete suggestions.</div>
            <div className="bg-gray-50 p-2 rounded"><code className="font-mono text-gray-900">reranking</code> — Cross-encoder (default, ~2s / 40-doc batch) or optional Gemini LLM (~500ms–1s). Off ⇒ retriever order is final.</div>
            <div className="bg-gray-50 p-2 rounded"><code className="font-mono text-gray-900">llm</code> — agent generation. Off ⇒ deterministic markdown product list.</div>
            <div className="bg-gray-50 p-2 rounded"><code className="font-mono text-gray-900">llm_judge</code> — hallucination detection & auto-correction. Off ⇒ no verification pass.</div>
          </div>

          <div className="bg-blue-50 border-l-4 border-blue-500 p-3 mt-4 text-[1.375rem]">
            <p className="font-semibold text-blue-900">Try this:</p>
            <ol className="text-blue-900 list-decimal list-inside mt-1 space-y-1">
              <li>During the adaptive-query demo, run the first turn with all toggles on.</li>
              <li>Toggle <code>reranking</code> off before running a subsequent turn — watch the Reranker row disappear from the Pipeline Quality Summary card and the Reranked stage drop out of the Narrator panel.</li>
              <li>Toggle <code>llm</code> off and run another turn — the agent renders a raw markdown product list with retrieval scores instead of a synthesized answer.</li>
              <li>Use the "All" On/Off switch to bulk-flip all toggles and observe how the Narrator/Details panel responds to the change.</li>
            </ol>
          </div>

          <p className="text-[1.25rem] text-[var(--color-stage-ink-soft)]">
            Toggles persist to <code>localStorage</code> via Zustand (<code>search-optimizations</code>) so they survive reloads. Flip all toggles at once with the <em>All</em> On/Off switch on the Search Optimizations card.
          </p>
        </div>
      ),
    },
    {
      id: 'pipeline-summary',
      title: '📈 Pipeline Quality Summary',
      content: (
        <div className="space-y-4">
          <p className="text-[1.375rem] text-gray-700">
            The last card in the Details panel scores every retrieval against ESCI ground truth (when the query exists) or a self-referential confidence proxy (when it doesn't). It's how you tell — at a glance — whether each stage of the pipeline is earning its latency.
          </p>

          <h4 className="font-semibold text-gray-900 mt-2">Ground-truth layout</h4>
          <p className="text-[1.375rem] text-gray-600">
            Three rows — <strong>BM25</strong>, <strong>Hybrid</strong>, <strong>Reranked</strong> — each with NDCG@10, MRR, Recall@20, Precision@10. ESCI labels are mapped to relevance:
          </p>
          <div className="grid grid-cols-4 gap-2 text-[1.25rem]">
            <div className="bg-emerald-50 p-2 rounded text-center"><strong>E</strong>xact = 4.0</div>
            <div className="bg-blue-50 p-2 rounded text-center"><strong>S</strong>ubstitute = 1.0</div>
            <div className="bg-amber-50 p-2 rounded text-center"><strong>C</strong>omplement = 0.1</div>
            <div className="bg-gray-100 p-2 rounded text-center"><strong>I</strong>rrelevant = 0.0</div>
          </div>

          <h4 className="font-semibold text-gray-900 mt-2">Latency cost-benefit</h4>
          <p className="text-[1.375rem] text-gray-600">
            A per-stage table with wall-clock latency and (for ground-truth queries) the marginal NDCG lift normalized to 100ms. Negative lift on the reranker row means it slowed you down without helping.
          </p>

          <h4 className="font-semibold text-gray-900 mt-2">Ground Truth tab in Narrator</h4>
          <p className="text-[1.375rem] text-gray-600">
            When a pipeline_summary event lands, this same data also renders as a "Ground Truth" tab inside the Narrator panel on the right — a bar-chart view of BM25 / Hybrid / Reranked NDCG@10 for that turn, separate from the Details panel's metrics-table card. It only appears once the summary event arrives.
          </p>

          <h4 className="font-semibold text-gray-900 mt-2">Fallback layout</h4>
          <p className="text-[1.375rem] text-gray-600">
            For novel queries (not in ESCI), the card shows a self-referential confidence proxy: top-1 reranker score, score gap to #2, score variance, and rank churn (top-10 positions that changed pre/post rerank). Color-coded high / medium / low chip — <em>not</em> NDCG, the card calls this out.
          </p>

          <div className="bg-amber-50 border-l-4 border-amber-500 p-3 mt-2 text-[1.375rem]">
            <p className="font-semibold text-amber-900">Enable ground-truth metrics:</p>
            <p className="text-amber-900 mt-1">The ESCI judgments are ingested via Lucille ETL as part of the standard setup:</p>
            <pre className="bg-[var(--color-stage-bg)] text-[var(--color-stage-ink)] p-2 rounded text-[1.25rem] overflow-x-auto mt-1">
              <code>bash scripts/lucille_ingest.sh</code>
            </pre>
            <p className="text-amber-900 mt-1 text-[1.25rem]">
              ~9,618 products and ~97,345 queries are ingested locally via Lucille (sparse judgments, averaging ~1 judged product per query). After ingestion, queries that match an ESCI query exactly (lowercased) trigger the BM25 → Hybrid → Reranked layout. Use <code className="bg-yellow-100 px-1">--skip-judgments</code> flag to skip this step.
            </p>
          </div>
        </div>
      ),
    },
    {
      id: 'llm-judge',
      title: '⚖️ LLM-as-Judge & Hallucination Gate',
      content: (
        <div className="space-y-4">
          <p className="text-[1.375rem] text-gray-700">
            When the <code>llm_judge</code> toggle is on (and the agent generated a synthesized response), a second Gemini Flash Lite call evaluates the answer against the deterministic raw-list baseline. The card adds a <strong>Generation</strong> row to the Pipeline Quality Summary with a pairwise verdict, four absolute scores (faithfulness, answer_relevance, citation_accuracy, context_utilization), and a list of flagged claims.
          </p>

          <h4 className="font-semibold text-gray-900 mt-2">Hallucination categories</h4>
          <p className="text-[1.375rem] text-gray-600">Each flagged claim is tiered into one of four categories. The two on the left are dangerous and worth retrying; the two on the right are surfaced for review but do not pay the ~20-30s retry tax.</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[1.25rem]">
            <div className="bg-rose-50 border-l-4 border-rose-500 p-2">
              <p className="font-semibold text-rose-900">Fabrication 🔴</p>
              <p className="text-rose-800 mt-1">An outright wrong fact (e.g. "Made in USA" when no FACTS block supports it). Triggers retry.</p>
            </div>
            <div className="bg-rose-50 border-l-4 border-rose-500 p-2">
              <p className="font-semibold text-rose-900">Cross-product bleed 🔴</p>
              <p className="text-rose-800 mt-1">A fact transferred between products (e.g. battery life from product B attached to product A). Triggers retry.</p>
            </div>
            <div className="bg-amber-50 border-l-4 border-amber-500 p-2">
              <p className="font-semibold text-amber-900">Inference 🟡</p>
              <p className="text-amber-800 mt-1">A paraphrase that goes slightly beyond the source. Surfaced for review only.</p>
            </div>
            <div className="bg-amber-50 border-l-4 border-amber-500 p-2">
              <p className="font-semibold text-amber-900">Overreach 🟡</p>
              <p className="text-amber-800 mt-1">A general claim beyond what's grounded ("best in class"). Surfaced for review only.</p>
            </div>
          </div>

          <h4 className="font-semibold text-gray-900 mt-2">Auto-correction retry (Layer 3a)</h4>
          <p className="text-[1.375rem] text-gray-600">
            The judge triggers a regenerate-and-re-judge pass whenever at least one flag is fabrication or cross-product bleed, regardless of the faithfulness score. The agent re-prompts the LLM with explicit "do NOT include claim X" instructions, then re-judges; the UI shows both the original and corrected verdicts with an <em>Auto-corrected</em> badge.
          </p>
        </div>
      ),
    },
    {
      id: 'architecture',
      title: '🏗️ Architecture Overview',
      content: (
        <div className="space-y-4">
          <div className="space-y-2 text-[1.375rem]">
            <p className="font-semibold text-gray-900">Core Pipeline (8 nodes)</p>
            <pre className="bg-[var(--color-stage-bg)] text-[var(--color-stage-ink)] p-2 rounded text-[1.25rem] overflow-x-auto">
              <code>{`intent_classifier ─┬─(summary)──► summary ─┬─(continue)──► retriever
                    ├─(clarify)──► agent    └─(done)──────► agent
                    └─(other)────► query_evaluator ──► retriever ──► reranker ──► quality_gate ─┬─(retry)───► retriever
                                                                                                  └─(continue)► agent ──► llm_judge ──► END`}</code>
            </pre>
            <p className="text-[1.25rem] text-gray-600">
              Eight nodes, not seven: <code className="bg-gray-100 px-1">intent_classifier</code>,{' '}
              <code className="bg-gray-100 px-1">query_evaluator</code>,{' '}
              <code className="bg-gray-100 px-1">summary</code>, <code className="bg-gray-100 px-1">retriever</code>
              , <code className="bg-gray-100 px-1">reranker</code>,{' '}
              <code className="bg-gray-100 px-1">quality_gate</code>, <code className="bg-gray-100 px-1">agent</code>
              , <code className="bg-gray-100 px-1">llm_judge</code>. A "summary" intent skips straight to the{' '}
              <code className="bg-gray-100 px-1">summary</code> node instead of retrieval, then rejoins at
              retriever or agent depending on whether the conversation continues. A low-confidence classification
              (below 0.7) routes straight to <code className="bg-gray-100 px-1">agent</code> for clarification.
              Query rewriting (resolving pronouns/follow-ups against history) happens inside{' '}
              <code className="bg-gray-100 px-1">retriever</code>, not as a separate node. Quality gate may
              loop back to the retriever exactly once with alpha adjusted ±0.3. LLM judge runs only when both the{' '}
              <code className="bg-gray-100 px-1">llm</code> and <code className="bg-gray-100 px-1">llm_judge</code>{' '}
              toggles are on, and can trigger a second auto-correction generation pass when fabrications are
              flagged (see "LLM-as-Judge" section).
            </p>

            <p className="font-semibold text-gray-900 mt-3">Tech Stack</p>
            <div className="grid grid-cols-2 gap-2">
              <div className="bg-gray-50 p-2 rounded text-[1.25rem]">
                <p className="font-mono text-gray-900">LLM Generation</p>
                <p className="text-gray-600">Gemini 2.5 Flash</p>
              </div>
              <div className="bg-gray-50 p-2 rounded text-[1.25rem]">
                <p className="font-mono text-gray-900">LLM Classify/Eval/Judge</p>
                <p className="text-gray-600">Gemini 2.5 Flash-Lite</p>
              </div>
              <div className="bg-gray-50 p-2 rounded text-[1.25rem]">
                <p className="font-mono text-gray-900">Reranking</p>
                <p className="text-gray-600">Cross-encoder (~2s / 40-doc batch, default) or Gemini (~500ms–1s, optional)</p>
              </div>
              <div className="bg-gray-50 p-2 rounded text-[1.25rem]">
                <p className="font-mono text-gray-900">Embeddings</p>
                <p className="text-gray-600">models/gemini-embedding-001 (768-dim)</p>
              </div>
              <div className="bg-gray-50 p-2 rounded text-[1.25rem]">
                <p className="font-mono text-gray-900">Vector DB</p>
                <p className="text-gray-600">OpenSearch 3.8.0 (HNSW + BM25)</p>
              </div>
              <div className="bg-gray-50 p-2 rounded text-[1.25rem]">
                <p className="font-mono text-gray-900">Checkpoints</p>
                <p className="text-gray-600">PostgreSQL 18 (pgvector)</p>
              </div>
              <div className="bg-gray-50 p-2 rounded text-[1.25rem]">
                <p className="font-mono text-gray-900">Framework</p>
                <p className="text-gray-600">LangGraph + LangChain</p>
              </div>
              <div className="bg-gray-50 p-2 rounded text-[1.25rem]">
                <p className="font-mono text-gray-900">Ingest Pipeline</p>
                <p className="text-gray-600">Lucille (KMW's own Java/Maven ETL framework)</p>
              </div>
              <div className="bg-gray-50 p-2 rounded text-[1.25rem]">
                <p className="font-mono text-gray-900">Frontend</p>
                <p className="text-gray-600">React 19 + TypeScript + Tailwind</p>
              </div>
            </div>

            <div className="bg-amber-50 border-l-4 border-amber-500 p-3 mt-3">
              <p className="font-semibold text-amber-900">Security model</p>
              <p className="text-amber-800 mt-1">
                Same-origin checking is the sole auth layer, enforced on every REST call and the WebSocket
                handshake — there is no login screen and no session cookie (removed entirely, issue #135). Every
                same-origin caller is unauthenticated, including{' '}
                <code className="bg-amber-100 px-1">/api/admin/*</code>.{' '}
                <code className="bg-amber-100 px-1">verify_admin_token</code> /{' '}
                <code className="bg-amber-100 px-1">ADMIN_TOKEN</code> exist as a preserved utility for future
                automation, not wired into any route today.
              </p>
            </div>
          </div>
        </div>
      ),
    },
    {
      id: 'troubleshooting',
      title: '🔧 Troubleshooting',
      content: (
        <div className="space-y-4">
          <div className="space-y-3 text-[1.375rem]">
            <div className="border-l-4 border-red-500 pl-3">
              <p className="font-semibold text-gray-900">ModuleNotFoundError: No module named 'config'</p>
              <p className="text-gray-600">Missing <code className="bg-gray-100 px-1">PYTHONPATH=.</code></p>
              <p className="text-[var(--color-stage-ink-soft)] text-[1.25rem] mt-1">Fix: <code className="bg-gray-100 px-1">cd langchain_agent && PYTHONPATH=. pytest tests/</code></p>
            </div>

            <div className="border-l-4 border-red-500 pl-3">
              <p className="font-semibold text-gray-900">ConnectionError: Error connecting to OpenSearch</p>
              <p className="text-gray-600">OpenSearch not running</p>
              <p className="text-[var(--color-stage-ink-soft)] text-[1.25rem] mt-1">Fix: <code className="bg-gray-100 px-1">cd langchain_agent && make dev</code> from repo root to start all services</p>
            </div>

            <div className="border-l-4 border-red-500 pl-3">
              <p className="font-semibold text-gray-900">Google AI API validation failed</p>
              <p className="text-gray-600">Missing GOOGLE_API_KEY</p>
              <p className="text-[var(--color-stage-ink-soft)] text-[1.25rem] mt-1">Fix: Get key from <a href="https://aistudio.google.com/apikey" className="text-blue-600 hover:underline">aistudio.google.com/apikey</a>, add to .env</p>
            </div>

            <div className="border-l-4 border-red-500 pl-3">
              <p className="font-semibold text-gray-900">WebSocket connection refused</p>
              <p className="text-gray-600">Backend not running</p>
              <p className="text-[var(--color-stage-ink-soft)] text-[1.25rem] mt-1">Fix: <code className="bg-gray-100 px-1">cd langchain_agent && make dev</code> to start the API</p>
            </div>

            <div className="border-l-4 border-yellow-500 pl-3">
              <p className="font-semibold text-gray-900">Slow responses (first request after startup)</p>
              <p className="text-gray-600">Cross-encoder model loading on first reranking call</p>
              <p className="text-[var(--color-stage-ink-soft)] text-[1.25rem] mt-1">Expected: ~6–15s typical latency. First request can be 30+ seconds (cross-encoder / reranker model load). Subsequent requests are faster. Check the Details panel for per-stage latencies to isolate the bottleneck.</p>
            </div>

            <div className="border-l-4 border-yellow-500 pl-3">
              <p className="font-semibold text-gray-900">Demo: Taxonomy demo turn 1 shows nothing wrong</p>
              <p className="text-gray-600">Demo not re-armed after previous run</p>
              <p className="text-[var(--color-stage-ink-soft)] text-[1.25rem] mt-1">The demo consumes a data defect (tan mis-tagged as yellow) and the prior run fixed it. The UI auto-re-arms on selection, but if you run turn 1 twice in one session, the second run shows no issue because the catalog no longer has the bug. Re-select the demo in the dropdown to re-arm.</p>
            </div>

            <div className="border-l-4 border-yellow-500 pl-3">
              <p className="font-semibold text-gray-900">Demo: Taxonomy demo turn 3 shows wrong results</p>
              <p className="text-gray-600">Query is being rewritten down a lexical path instead of showing the fixed tag</p>
              <p className="text-[var(--color-stage-ink-soft)] text-[1.25rem] mt-1">Turn 3 must be run in a brand-new conversation — reusing the same thread causes the query rewriter to take a lexical shortcut instead of re-searching. Close the conversation and start a new one before running turn 3.</p>
            </div>

            <div className="border-l-4 border-yellow-500 pl-3">
              <p className="font-semibold text-gray-900">Demo: has_ground_truth is always false</p>
              <p className="text-gray-600">Expected behavior (except for one specific query)</p>
              <p className="text-[var(--color-stage-ink-soft)] text-[1.25rem] mt-1">The ESCI judgments are sparse — most of the demo queries don't match any ESCI query exactly. Only the "sewing machine" turn in the "Proving It With Real Judgments" demo produces has_ground_truth=true. Anywhere else it's false is expected, not a bug.</p>
            </div>

            <div className="border-l-4 border-yellow-500 pl-3">
              <p className="font-semibold text-gray-900">Demo: F2 key not toggling detail panel</p>
              <p className="text-gray-600">Chat input has focus</p>
              <p className="text-[var(--color-stage-ink-soft)] text-[1.25rem] mt-1">Keyboard shortcuts only work when the detail panel or main page has focus. If the chat input field is active (cursor blinking), F2 will type into the message instead of toggling the panel. Click elsewhere first or submit your message.</p>
            </div>

            <div className="border-l-4 border-yellow-500 pl-3">
              <p className="font-semibold text-gray-900">Default cross-encoder reranking latency</p>
              <p className="text-gray-600">~2 seconds for a 40-doc batch</p>
              <p className="text-[var(--color-stage-ink-soft)] text-[1.25rem] mt-1">This is the local cross-encoder model running on CPU/GPU, not an API call. If using the optional Gemini LLM reranker, expect ~500ms–1s instead. Check the Details panel for actual measured latency on your hardware.</p>
            </div>
          </div>

          <h4 className="font-semibold text-gray-900 mt-4">Resources & Configuration</h4>
          <div className="text-[1.375rem] text-gray-700 space-y-1">
            <p><strong>API Docs:</strong> <a href="/swagger" className="text-blue-600 hover:underline">Interactive Swagger UI at /swagger</a></p>
            <p><strong>Key commands:</strong> <code className="bg-gray-100 px-1">make dev</code> (start), <code className="bg-gray-100 px-1">make ci</code> (lint/type/test), <code className="bg-gray-100 px-1">make smoke</code> (verify), <code className="bg-gray-100 px-1">bash scripts/lucille_ingest.sh</code> (ingest)</p>
            <p><strong>Config:</strong> See <code className="bg-gray-100 px-1">langchain_agent/.env.example</code> for all environment variables and <code className="bg-gray-100 px-1">CLAUDE.md</code> for the detailed project guide.</p>
          </div>
        </div>
      ),
    },
  ]

  const expandAll = useCallback(() => {
    setExpandedSections(new Set(sections.map((s) => s.id)))
  }, [])

  const collapseAll = useCallback(() => {
    setExpandedSections(new Set())
  }, [])

  // Deep-link support: react to the URL hash on mount and on subsequent hashchange
  // events (e.g., user pastes a fragment URL into the address bar while already on
  // /guide). TOC clicks use history.replaceState which is intentionally silent and
  // does not trigger hashchange — so no feedback loop.
  useEffect(() => {
    const applyHash = () => {
      const hash = window.location.hash.slice(1)
      if (!hash) return
      const exists = sections.some((s) => s.id === hash)
      if (!exists) return
      setExpandedSections((prev) => {
        if (prev.has(hash)) return prev
        const next = new Set(prev)
        next.add(hash)
        return next
      })
      scrollToSection(hash)
    }
    applyHash()
    window.addEventListener('hashchange', applyHash)
    return () => window.removeEventListener('hashchange', applyHash)
  }, [])

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 to-gray-100 py-8 px-4">
      <div className="max-w-[1500px] mx-auto">
        {/* Header */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6 flex flex-wrap items-center gap-6">
          <img src="/kmw-logo.svg" alt="KMW Technology" className="h-16 w-auto flex-shrink-0" />
          <div className="h-16 w-px flex-shrink-0 bg-gray-200" aria-hidden="true" />
          <div>
            <h1 className="text-[2.75rem] font-bold text-gray-900 mb-2">📖 Agentic Hybrid Search Guide</h1>
            <p className="text-gray-600">Guide to the demo, the UI, and how to read the pipeline.</p>
          </div>
        </div>

        {/* Table of Contents */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
          <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
            <h2 className="font-semibold text-gray-900">Quick Navigation</h2>
            <div className="flex items-center gap-1 text-[1.25rem]">
              <button
                onClick={expandAll}
                className="text-gray-600 hover:text-gray-900 hover:bg-gray-100 px-2 py-1 rounded transition-colors"
                title="Expand all sections"
              >
                Expand all
              </button>
              <span className="text-[var(--color-stage-ink-muted)]" aria-hidden="true">·</span>
              <button
                onClick={collapseAll}
                className="text-gray-600 hover:text-gray-900 hover:bg-gray-100 px-2 py-1 rounded transition-colors"
                title="Collapse all sections"
              >
                Collapse all
              </button>
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-1">
            {sections.map((section) => (
              <button
                key={section.id}
                onClick={() => navigateToSection(section.id)}
                className="text-left text-[1.375rem] text-blue-600 hover:text-blue-700 hover:bg-blue-50 px-2 py-1.5 rounded transition-colors"
              >
                {section.title}
              </button>
            ))}
          </div>
        </div>

        {/* Sections */}
        <div className="space-y-4">
          {sections.map((section) => {
            const isExpanded = expandedSections.has(section.id)
            return (
              <div
                key={section.id}
                id={section.id}
                ref={(el) => {
                  sectionRefs.current[section.id] = el
                }}
                className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden scroll-mt-4"
              >
                <button
                  onClick={() => toggleSection(section.id)}
                  className="w-full flex items-center justify-between p-4 hover:bg-gray-50 transition-colors"
                  aria-expanded={isExpanded}
                  aria-controls={`${section.id}-panel`}
                >
                  <h2 className="text-[1.75rem] font-semibold text-gray-900">{section.title}</h2>
                  {isExpanded ? (
                    <ChevronUp className="w-5 h-5 text-[var(--color-stage-ink-soft)]" />
                  ) : (
                    <ChevronDown className="w-5 h-5 text-[var(--color-stage-ink-soft)]" />
                  )}
                </button>

                {isExpanded && (
                  <div
                    id={`${section.id}-panel`}
                    role="region"
                    aria-labelledby={section.id}
                    className="border-t border-gray-200 p-4 bg-gray-50"
                  >
                    {section.content}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {/* Footer */}
        <div className="mt-8 text-center text-[1.375rem] text-gray-600">
          <p>Need more help? Check the <a href="/swagger" className="text-blue-600 hover:underline">Swagger UI</a></p>
        </div>
      </div>
    </div>
  )
}
