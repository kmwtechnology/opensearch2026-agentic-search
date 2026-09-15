# Stores

[← web/src](../)

Zustand state management stores for global UI and application state.

## Overview

| Store | Purpose | Main State | Key Actions |
|-------|---------|-----------|-------------|
| **chatStore** | Messages, conversation, streaming | `threadId`, `messages[]`, `isProcessing`, `streamingContent` | `addMessage()`, `setThreadId()`, `updateMessageStatus()` |
| **observabilityStore** | Event stream, pipeline timeline | `events[]`, `activeStep`, `snapshots[]` | `addEvent()`, `setActiveStep()`, `saveSnapshot()` |
| **optimizationsStore** | UI search-optimization toggles | `optimizations` (a `Record<OptimizationKey, boolean>` — `hybrid`, `fuzzy`, `synonyms`, `phonetic`, `phrase_boost`, `field_boost`, `typeahead`, `reranking`, `llm`, `llm_judge`) | `toggle(key)`, `setAll(value)`, `reset()` |

## Store Files

```
stores/
├── chatStore.ts                    ← Messages, thread, streaming, processing state
├── observabilityStore.ts           ← Event stream, snapshots, timeline
├── optimizationsStore.ts           ← UI toggle switches
└── __tests__/                      ← Vitest tests for each store
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
type OptimizationKey =
  | 'hybrid' | 'fuzzy' | 'synonyms' | 'phonetic' | 'phrase_boost'
  | 'field_boost' | 'typeahead' | 'reranking' | 'llm' | 'llm_judge'

interface OptimizationsState {
  optimizations: Record<OptimizationKey, boolean>
  toggle: (key: OptimizationKey) => void
  setAll: (value: boolean) => void
  reset: () => void
}
```

**When to use:** ObservabilityPanel (conditional rendering based on toggles), persistent to localStorage for session continuity.

## Persistence

- `chatStore`: Recent messages persisted to localStorage + server (via REST)
- `observabilityStore`: Events ephemeral (cleared on new conversation or page reload)
- `optimizationsStore`: UI toggles saved to localStorage for session recall
