# Components

[← web/src](../) | [← langchain_agent/web](../../)

This directory contains all reusable React components organized by functional domain.

## Directory Overview

| Component | Purpose | Files |
|-----------|---------|-------|
| **[ObservabilityPanel](./ObservabilityPanel/)** | Real-time pipeline monitoring, event stream visualization, metrics display | 9 components |
| **[ChatPanel](./ChatPanel/)** | Chat UI: message rendering, input field, typeahead suggestions, message list | 4 components + tests |
| **[NarratorPanel](./NarratorPanel/)** | Plain-language "what just happened" narration for projected demos (#103) | 2 components + tests |
| **DemoSelector** | Names the demo being run; presenter-selected, never auto-detected | 1 component |

## Shared Components

| Component | Purpose |
|-----------|---------|
| `Layout.tsx` | Root layout wrapper with sidebar + main content grid |
| `ConfirmDialog.tsx` | Reusable confirmation modal for destructive actions |
| `ErrorNotification.tsx` | Toast-style error alerts with auto-dismiss |
| `SkeletonLoader.tsx` | Loading placeholder component |

## Styling

All components use **Tailwind CSS v4** for styling. Theme customization (colors, animations) lives in `src/index.css` via `@theme` (CSS-based config — there is no `tailwind.config.js`). Components follow semantic HTML and WCAG 2.1 accessibility guidelines.

## Store Dependencies

Components communicate with Zustand stores:
- `chatStore` — messages, thread state, streaming
- `observabilityStore` — event stream, snapshots
- `optimizationsStore` — UI toggles (show BM25, reranker, etc.)

There is no login gate and no `authStore` — same-origin checking is the app's only auth layer (see the root `CLAUDE.md`'s "Auth model" section).

See [`../stores/README.md`](../stores/) for detailed store exports.

## Hooks

Components use custom hooks for complex logic:
- `useWebSocket()` — WebSocket connection and message handling
- `useRecentSearches()` — Recent query history management

See [`../hooks/README.md`](../hooks/) for hook signatures.
