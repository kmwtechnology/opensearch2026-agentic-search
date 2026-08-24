# Stores

[← web/src](../)

Zustand state management stores for global UI and application state.

## Overview

| Store | Purpose | Main State | Key Actions |
|-------|---------|-----------|-------------|
| **authStore** | Login/logout, session state | `isLoggedIn`, `error` | `login(password)`, `logout()`, `markUnauthenticated()` |
| **chatStore** | Messages, conversation, streaming | `threadId`, `messages[]`, `isProcessing`, `streamingContent` | `addMessage()`, `setThreadId()`, `updateMessageStatus()` |
| **observabilityStore** | Event stream, pipeline timeline | `events[]`, `activeStep`, `snapshots[]` | `addEvent()`, `setActiveStep()`, `saveSnapshot()` |
| **optimizationsStore** | UI feature toggles | `showBM25`, `showReranker`, `showMetrics`, `showRaw` | `toggleBM25()`, `toggleMetrics()` |

## Store Files

```
stores/
├── authStore.ts                    ← Session, login password, logout
├── chatStore.ts                    ← Messages, thread, streaming, processing state
├── observabilityStore.ts           ← Event stream, snapshots, timeline
├── optimizationsStore.ts           ← UI toggle switches
└── __tests__/                      ← Vitest tests for each store
    ├── authStore.test.ts
    ├── chatStore.test.ts
    ├── observabilityStore.test.ts
    └── optimizationsStore.test.ts
```

## Usage Pattern

All stores use Zustand's `create()` hook. Import and use like:

```typescript
import { useChatStore } from '../stores/chatStore'

function MyComponent() {
  const { messages, addMessage } = useChatStore()
  // Rendered with messages, addMessage is action
}
```

## authStore

```typescript
interface AuthState {
  isLoggedIn: boolean
  error: string | null
  login: (password: string) => Promise<void>
  logout: () => Promise<void>
  markUnauthenticated: () => void
}
```

**When to use:** LoginScreen, Layout (conditionally render chat), useWebSocket (auth failures trigger reconnect).

## chatStore

```typescript
interface ChatState {
  threadId: string | null
  messages: ChatMessage[]
  isProcessing: boolean
  streamingContent: string
  isConnected: boolean
  addMessage: (msg: ChatMessage) => void
  setThreadId: (id: string) => void
  updateMessageStatus: (id: string, status?: 'queued') => void
  // ... 10+ more actions
}
```

**When to use:** ChatPanel (message list + input), ConversationsSidebar (thread switch), useWebSocket (message updates).

## observabilityStore

```typescript
interface ObservabilityState {
  events: AgentEvent[]
  activeStep: string | null
  snapshots: ObservabilitySnapshot[]
  addEvent: (event: AgentEvent) => void
  setActiveStep: (nodeId: string) => void
  saveSnapshot: (snapshot: ObservabilitySnapshot) => void
}
```

**When to use:** ObservabilityPanel (event timeline + metrics), useWebSocket (new events from WS stream).

## optimizationsStore

```typescript
interface OptimizationsState {
  showBM25: boolean
  showReranker: boolean
  showMetrics: boolean
  showRaw: boolean
  toggleBM25: () => void
  toggleReranker: () => void
  // ... toggle actions for each flag
}
```

**When to use:** ObservabilityPanel (conditional rendering based on toggles), persistent to localStorage for session continuity.

## Persistence

- `chatStore`: Recent messages persisted to localStorage + server (via REST)
- `authStore`: Login state tied to HTTP-only cookie (not persisted in JS)
- `observabilityStore`: Events ephemeral (cleared on new conversation or page reload)
- `optimizationsStore`: UI toggles saved to localStorage for session recall
