# Components

[← web/src](../) | [← langchain_agent/web](../../)

This directory contains all reusable React components organized by functional domain.

## Directory Overview

| Component | Purpose | Files |
|-----------|---------|-------|
| **[ObservabilityPanel](./ObservabilityPanel/)** | Real-time pipeline monitoring, event stream visualization, metrics display | 9 components |
| **[ChatPanel](./ChatPanel/)** | Chat UI: message rendering, input field, typeahead suggestions, message list | 4 components + tests |
| **[ConversationsSidebar](./ConversationsSidebar/)** | Sidebar navigation: conversation list, thread switching, logout button | 2 components + tests |

## Shared Components

| Component | Purpose |
|-----------|---------|
| `LoginScreen.tsx` | Authentication form (session password entry) |
| `Layout.tsx` | Root layout wrapper with sidebar + main content grid |
| `ConfirmDialog.tsx` | Reusable confirmation modal for destructive actions |
| `ErrorNotification.tsx` | Toast-style error alerts with auto-dismiss |
| `SkeletonLoader.tsx` | Loading placeholder component |

## Styling

All components use **Tailwind CSS** for styling. Dark mode is configured in `tailwind.config.ts`. Components follow semantic HTML and WCAG 2.1 accessibility guidelines.

## Store Dependencies

Components communicate with Zustand stores:
- `chatStore` — messages, thread state, streaming
- `observabilityStore` — event stream, snapshots
- `optimizationsStore` — UI toggles (show BM25, reranker, etc.)
- `authStore` — login state, session management

See [`../stores/README.md`](../stores/) for detailed store exports.

## Hooks

Components use custom hooks for complex logic:
- `useWebSocket()` — WebSocket connection and message handling
- `useRecentSearches()` — Recent query history management

See [`../hooks/README.md`](../hooks/) for hook signatures.
