# Agentic Hybrid Search — React Frontend

> **Parent**: [langchain_agent/README.md](../README.md)

React 18 + TypeScript + Tailwind + Zustand single-page app. Built with Vite; proxies `/api`
to the backend on `:8000` during development.

## Quick Start

```bash
cd langchain_agent/web
npm install
npm run dev         # Vite dev server on :5173
```

Open <http://localhost:5173>.

## Architecture

```text
src/
├── App.tsx                    # Root component, page routing
├── main.tsx                   # Entry point, Zustand store init
├── components/                # React components
│   ├── ChatPanel/             # Chat UI, message history
│   ├── ObservabilityPanel/    # Real-time pipeline visualization
│   ├── ConversationsSidebar/  # Conversation list + logout
│   └── ...
├── hooks/                     # Custom React hooks
│   ├── useWebSocket.ts        # WebSocket lifecycle + auth
│   ├── useRecentSearches.ts   # localStorage-backed search history
│   └── ...
├── stores/                    # Zustand state management
│   ├── chatStore.ts           # Messages, conversations, UI state
│   ├── observabilityStore.ts  # Pipeline events + stage visualization
│   ├── authStore.ts           # Login/logout, session state
│   └── ...
├── types/                     # TypeScript type definitions
│   ├── events.ts              # Pydantic event models (MUST match api/schemas/events.py)
│   └── ...
├── pages/                     # Page-level components (routed via App.tsx)
├── utils/                     # Utilities (formatters, helpers)
└── tests/                     # Vitest unit tests (__tests__/ dirs alongside source)
```

## Directory Documentation

Detailed documentation for subdirectories:

| Directory | Purpose | Link |
|-----------|---------|------|
| **Components** | React UI components (chat, observability, sidebar) | [src/components/README.md](./src/components/) |
| **Stores** | Zustand state management (chat, auth, observability) | [src/stores/README.md](./src/stores/) |
| **Hooks** | Custom React hooks (WebSocket, recent searches) | [src/hooks/README.md](./src/hooks/) |

Start with the components directory to understand the UI structure, then explore stores for state management patterns, and hooks for WebSocket / side-effect logic.

## Development

### Commands

| Command | Purpose |
|---------|---------|
| `npm run dev` | Vite dev server, auto-reload, proxy `/api` → `:8000` |
| `npm run build` | TypeScript + Vite build → `dist/` |
| `npm run lint` | ESLint |
| `npm run test` | Vitest runner; 101 tests |
| `npm run test -- --watch` | Vitest watch mode |
| `npm run test -- --coverage` | Coverage report |

### Key Files

- **`App.tsx`** — Route setup, page selection, theme provider
- **`main.tsx`** — React 18 root, Vite entry
- **`vite-env.d.ts`** — Vite type definitions
- **`.env.local`** — Local env vars (`VITE_API_URL` set by parent `setup.sh`)

### Frontend Stores

| Store | Purpose |
|-------|---------|
| `chatStore.ts` | Messages, active conversation, UI state (chat vs. pipeline view); `ChatMessage` carries `corrected`, `originalContent`, `originalFaithfulness`, `correctedFaithfulness` for judge auto-correction display |
| `observabilityStore.ts` | Pipeline events from WebSocket, stage-by-stage visualization |
| `authStore.ts` | Login state, session validity, user credentials |

### WebSocket Integration

- **Hook:** `useWebSocket.ts` — manages connection, auth, reconnection, event routing
- **Auth:** Session cookie (automatic on login) OR `X-Admin-Token` header (automation)
- **Events:** Typed Pydantic payloads streamed from backend; emitted per pipeline stage
- **URL:** `/api/chat` (proxied to backend by Vite)

### Event Contract

**CRITICAL:** `web/src/types/events.ts` must match `api/schemas/events.py`.

Every `type: Literal[...]` event must exist in both files. Every event's `node` field must agree.
Pre-flight test `test_frontend_backend_event_parity.py` catches divergence.

If you add a new event in `events.py`:
1. Add the Pydantic model to `api/schemas/events.py`
2. Export the `type: Literal[...]` in the union at the bottom
3. Add the matching TypeScript interface to `web/src/types/events.ts`
4. Verify `node` field values match in both files
5. Run: `PYTHONPATH=. pytest tests/unit/test_frontend_backend_event_parity.py`

## Components

Key observability components render pipeline events:

| Component | Purpose | File |
|-----------|---------|------|
| `IntentClassifierDetails` | Intent badge, confidence, keyword/LLM path | `ObservabilityPanel/` |
| `SearchOptimizationDetails` | BM25 synonym expansion, fuzzy, phrase boost, phonetic | `ObservabilityPanel/SearchOptimizationDetails.tsx` |
| `PipelineSummaryCard` | Per-stage NDCG/MRR/Recall/Precision (or confidence proxy) | `ObservabilityPanel/PipelineSummaryCard.tsx` |
| `DslViewerModal` | Full OpenSearch DSL body with request line + embedded vectors scrubbed | `ObservabilityPanel/` |
| `TypeaheadSuggestions` | Did you mean? / Suggestions / Recent Searches combobox | `ChatPanel/` |
| `Message` | Single chat message bubble; renders markdown, citations, streaming cursor, and amber "AI-corrected" badge with "Show original" toggle when `message.corrected=true` | `ChatPanel/Message.tsx` |

## Testing

```bash
npm run test                  # Run all 101 tests once
npm run test -- --watch      # Watch mode
npm run test -- --coverage   # HTML coverage report
```

Tests live alongside source in `**/__tests__/` directories.

Coverage spans:
- Zustand stores (state mutations, persistence)
- WebSocket hooks (connection, auth, reconnection)
- Observable components (intent badges, confidence colors, event rendering)
- Accessibility (ARIA attributes, keyboard navigation)

Example:
```bash
cd langchain_agent/web
npm run test -- --watch --grep "TypeaheadSuggestions"
```

## Build & Deployment

### Local Build

```bash
npm run build       # Output: dist/
npx http-server dist   # Serve dist/ locally for testing
```

### Cloud Run Deployment

Multi-stage Docker build in `../Dockerfile`:
1. **Build stage** — Node 24, `npm install && npm run build` → `dist/`
2. **Runtime stage** — Python 3.14 + gunicorn serves `dist/` + proxies `/api` to Python backend

The frontend is built into the Docker image and served from the Python backend on Cloud Run.
No separate Node.js service — all one container.

## Configuration

Environment variables (Vite requires `VITE_` prefix):

| Variable | Purpose | Example |
|----------|---------|---------|
| `VITE_API_URL` | Backend API endpoint | `http://localhost:8000/api` (local) or `https://example.run.app/api` (Cloud Run) |

Set in `.env.local` (local) or via Docker build `--build-arg` (Cloud Run).

## Troubleshooting

**Can't connect to backend:**
```bash
curl http://localhost:8000/api/health
# Check that the backend is running on :8000
```

**Vite build fails:**
```bash
npm run build
# Check for TypeScript errors:
npx tsc --noEmit
```

**Tests failing:**
```bash
npm run test -- --reporter=verbose
# Check that node_modules is up to date:
rm -rf node_modules package-lock.json
npm install
```

**Event type mismatch errors:**
- Edit both `api/schemas/events.py` and `web/src/types/events.ts`
- Run pre-flight test: `PYTHONPATH=. pytest tests/unit/test_frontend_backend_event_parity.py`

## References

- [React 18 docs](https://react.dev/)
- [TypeScript docs](https://www.typescriptlang.org/)
- [Tailwind CSS](https://tailwindcss.com/)
- [Zustand docs](https://github.com/pmndrs/zustand)
- [Vite docs](https://vitejs.dev/)
- [Vitest docs](https://vitest.dev/)
