# Hooks

[← web/src](../)

Custom React hooks for complex UI logic: WebSocket management, recent searches, and state binding.

## Available Hooks

| Hook | Purpose | Return Type |
|------|---------|-------------|
| **useWebSocket()** | WebSocket lifecycle, message sending, event dispatch | `UseWebSocketReturn` |
| **useRecentSearches()** | Recent query history from localStorage | `{ recent: string[], add: (q: string) => void }` |

## useWebSocket

Manages singleton WebSocket connection to the agent backend, emits events to stores.

```typescript
function useWebSocket(): UseWebSocketReturn {
  isConnected: boolean
  isConnecting: boolean
  error: string | null
  connect: (threadId: string) => void
  disconnect: (options?: { preserveThreadId?: boolean }) => void
  sendMessage: (message: string) => void
  stopExecution: () => void
}
```

**Usage:**

```typescript
const { connect, sendMessage, isConnected } = useWebSocket()

useEffect(() => {
  if (threadId) connect(threadId)
}, [threadId])

const handleSend = (msg: string) => {
  if (isConnected) sendMessage(msg)
}
```

**Behavior:**
- Connects to `wss://<host>/ws/{threadId}` on `connect()`
- Reuses singleton instance (no duplicate connections)
- Emits typed events → `observabilityStore.addEvent()`
- Handles close code `4401` (unauthorized) → triggers reauth
- Auto-reconnect on transient failures
- `stopExecution()` sends cancel signal to backend

**Important:** Connection requires valid session cookie (set by LoginScreen). WS handshake validates via `verify_websocket_session()` in backend.

## useRecentSearches

Reads/writes recent queries to browser localStorage.

```typescript
function useRecentSearches(): {
  recent: string[]
  add: (query: string) => void
}
```

**Usage:**

```typescript
const { recent, add } = useRecentSearches()

const handleSendMessage = (query: string) => {
  add(query)  // Persist to localStorage
  // ... send to backend
}

// TypeaheadSuggestions uses recent for dropdown
```

**Behavior:**
- Max 10 recent queries
- Duplicates deduplicated (moved to front)
- Persisted to key `ahs_recent_searches` in localStorage
- Survives page reload but cleared on logout

## Files

```
hooks/
├── useWebSocket.ts                 ← WebSocket singleton + event dispatch
├── useRecentSearches.ts            ← localStorage history
└── __tests__/                      ← Vitest tests
    ├── useWebSocket.test.ts
    └── useRecentSearches.test.ts
```

## Testing

Hooks are tested via `renderHook` from `@testing-library/react`:

```typescript
import { renderHook, act } from '@testing-library/react'
import { useWebSocket } from '../useWebSocket'

test('connects to WebSocket', () => {
  const { result } = renderHook(() => useWebSocket())
  act(() => {
    result.current.connect('thread-123')
  })
  expect(result.current.isConnected).toBe(true)
})
```

## Best Practices

- **useWebSocket** is a singleton: multiple component calls share one connection
- **useRecentSearches** is per-component: multiple callers get independent reads but share localStorage
- Both hooks are safe to call from multiple components simultaneously
- Avoid destructuring in component render; use object refs or useMemo for performance
