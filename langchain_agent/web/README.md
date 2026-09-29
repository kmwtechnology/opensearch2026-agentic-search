# Web UI

> **Parent**: [../README.md](../README.md) · API and event contract: [../api/README.md](../api/README.md)

React 19 + TypeScript + Vite, Tailwind CSS v4, Zustand stores, `react-markdown`
for answers, `lucide-react` icons, Vitest + Testing Library.

## Scripts

```bash
npm install
npm run dev          # Vite on :5173 (make dev runs this for you)
npm run build        # tsc + vite build → dist/ (what the demo image ships)
npm run lint         # eslint, --max-warnings 0
npm run test         # vitest run  (npm run test:watch for watch mode)
```

`make ci` runs test, lint, `tsc --noEmit`, and build.

## Talking to the backend

The UI only ever uses relative URLs. In development Vite proxies `/api` and
`/ws` to the native backend on :8080 (`vite.config.ts`); in the demo container
the built UI and the API share one origin on :8000. The WebSocket URL is built
from `window.location` (`hooks/useWebSocket.ts`), so both cases work without
configuration. `VITE_API_URL` exists for the unusual case of a separate origin
with no proxy — leave it unset.

Requests carry the browser's `Origin`, which is the backend's only auth check.

## Structure

```text
src/
├── App.tsx                     routes: / (chat), /guide, /swagger
├── components/
│   ├── ChatPanel/              MessageList, Message, ProductCard, MessageInput
│   ├── ObservabilityPanel/     per-node StepCard + details/, PipelineSummaryCard, DslViewerModal
│   ├── NarratorPanel/          plain-language narration of the event stream (narrate.ts)
│   ├── DemoSelector.tsx        the scripted demos
│   └── Layout.tsx
├── demos/registry.ts           SOURCE OF TRUTH for the three scripted demos (queries, steps, expectations)
├── hooks/                      useWebSocket (event dispatch into the stores), useRecentSearches
├── stores/                     Zustand
├── pages/                      GuidePage (presenter notes), SwaggerPage
├── types/events.ts             mirrors api/schemas/events.py — enforced by a Python parity test
└── utils/                      api.ts (fetch wrapper), threadId.ts
```

| Store | Holds |
|---|---|
| `chatStore` | thread id, messages, streaming text, queued messages, connection state |
| `observabilityStore` | per-node steps and their events, the latest intent / alpha / quality-gate / reranker data, the pipeline summary, the enrichment banner state |

## Rendering rules worth knowing

- **An answer renders exactly once.** Citations arrive on `agent_complete`, one
  frame after the last `llm_response_chunk`, so `chatStore.completeTurn` writes
  the text and the citations in a single update and `MessageList` withholds a
  still-streaming assistant bubble (the pipeline status card stays up instead).
  Don't finalize on `llm_response_chunk`; `agent_error` is the failure path.
- **Product cards are inline.** Each bullet in the answer becomes a
  `ProductCard` when its bolded name prefix-matches a citation label
  (`productIndex.ts`); the card uses the citation's `image_url` straight from
  Amazon's CDN and falls back to a plain bullet on a 404. Nothing is bundled.
- **Events are the contract.** `types/events.ts` must match
  `api/schemas/events.py` field for field; add or remove an event on both
  sides or `tests/unit/test_frontend_backend_event_parity.py` fails.

## Tests

Vitest suites live in `__tests__/` folders next to the code: the three
stores, `useWebSocket` (client side of the event contract), `narrate`,
`ProductCard` / `Message` / `MessageList` (the rendering rules above), and the
observability detail cards.
