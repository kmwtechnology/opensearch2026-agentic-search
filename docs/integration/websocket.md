# WebSocket Guide

Real-time message streaming for responsive chat UIs.

**Parent:** [Integration Guide](README.md)

---

## Connection

### URL

**Development:**
```
ws://localhost:8000/ws/{thread_id}
```

**Production:**
```
wss://agentic-hybrid-search-XXXX.run.app/ws/{thread_id}
```

Replace `{thread_id}` with a conversation ID (e.g., `conv_abc123def456`).

### Authentication

The session cookie **must** be present in the WebSocket handshake. Browsers send it automatically; custom clients must include it explicitly.

**JavaScript (browser):**
```javascript
const ws = new WebSocket(
  `wss://agentic-hybrid-search-XXXX.run.app/ws/${threadId}`,
  [],
  { credentials: 'include' }  // Include cookies
);
```

**Python (custom client):**
```python
import websockets
import json

async def connect():
    headers = {
        'Cookie': 'ahs_session=...'  # From login response
    }
    async with websockets.connect(
        f'wss://agentic-hybrid-search-XXXX.run.app/ws/{thread_id}',
        additional_headers=headers
    ) as ws:
        # Connected
        await ws.send(json.dumps({
            'type': 'chat_message',
            'message': 'Find wireless headphones',
            'thread_id': thread_id
        }))
```

### Connection Established

On successful connection, the server sends:
```json
{
  "type": "connection_established",
  "thread_id": "conv_abc123def456",
  "timestamp": "2026-06-04T16:30:45Z"
}
```

---

## Sending Messages

### Chat Message

```json
{
  "type": "chat_message",
  "message": "Find wireless headphones under $100",
  "thread_id": "conv_abc123def456"
}
```

Required fields: `type`, `message`, `thread_id`.

---

## Receiving Events

The server streams back a sequence of **typed events**. All events have a `type` field and a `node` field (which pipeline stage emitted it).

### Event Types

| Event | Node | Purpose |
|-------|------|---------|
| `connection_established` | — | Handshake complete |
| `search_progress` | intent_classifier | Intent classification in progress |
| `reranker_progress` | reranker | Reranking top-K documents |
| `quality_gate` | quality_gate | Quality gate verdict (retry or continue) |
| `query_expansion` | query_evaluator | Query rewriting result |
| `opensearch_query` | retriever | Full OpenSearch DSL (for debugging) |
| `llm_response_chunk` | agent | Token-by-token response text |
| `clarification_requested` | intent_classifier | Low-confidence intent; ask user |
| `clarification_resolved` | intent_classifier | User clarified intent |
| `agent_complete` | agent | Full response and citations ready |
| `pipeline_summary` | — | Per-stage metrics (NDCG, MRR, latency) |

### Example: Search Flow

**1. User sends message:**
```json
{"type": "chat_message", "message": "wireless headphones", "thread_id": "..."}
```

**2. Server responds with events:**

```json
{"type": "search_progress", "node": "intent_classifier", "status": "classifying"}
```

```json
{"type": "search_progress", "node": "intent_classifier", "intent": "search", "confidence": 0.95}
```

```json
{"type": "query_expansion", "node": "query_evaluator", "expanded_query": "wireless headphones"}
```

```json
{"type": "reranker_progress", "node": "reranker", "documents_scored": 40, "max_score": 0.87}
```

```json
{"type": "llm_response_chunk", "node": "agent", "chunk": "Here are the ", "complete": false}
```

```json
{"type": "llm_response_chunk", "node": "agent", "chunk": "top wireless", "complete": false}
```

```json
{"type": "llm_response_chunk", "node": "agent", "chunk": " headphones:\n", "complete": false}
```

```json
{
  "type": "agent_complete",
  "node": "agent",
  "response": "Here are the top wireless headphones:\n1. Bose ...",
  "citations": [
    {"url": "https://www.amazon.com/s?k=Bose+QuietComfort", "title": "Bose QuietComfort"}
  ]
}
```

```json
{
  "type": "pipeline_summary",
  "node": "agent",
  "metrics": {
    "intent": "search",
    "retriever_latency_ms": 1200,
    "reranker_max_score": 0.87,
    "agent_latency_ms": 8500,
    "total_latency_ms": 10200
  }
}
```

---

## Close Codes

| Code | Meaning | Action |
|------|---------|--------|
| 1000 | Normal close | Conversation ended |
| 1001 | Going away | Server shutting down |
| 4401 | Auth failed | Session cookie expired; re-authenticate |
| 4500 | Server error | Unexpected error; reconnect |

**On close code 4401:** User must re-authenticate via `POST /api/auth/login` and reconnect with a new cookie.

---

## JavaScript Example (React)

```javascript
import { useEffect, useState } from 'react';

export function ChatComponent() {
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isConnected, setIsConnected] = useState(false);
  const ws = React.useRef(null);

  useEffect(() => {
    const threadId = 'conv_abc123def456'; // From login
    const url = `wss://agentic-hybrid-search-XXXX.run.app/ws/${threadId}`;

    ws.current = new WebSocket(url);
    ws.current.onopen = () => setIsConnected(true);
    ws.current.onmessage = (event) => {
      const event_obj = JSON.parse(event.data);
      console.log('Received event:', event_obj.type, event_obj);

      if (event_obj.type === 'llm_response_chunk') {
        // Append chunk to message
        setMessages((msgs) => [
          ...msgs.slice(0, -1),
          {
            ...msgs[msgs.length - 1],
            content: msgs[msgs.length - 1].content + event_obj.chunk,
          },
        ]);
      } else if (event_obj.type === 'agent_complete') {
        // Add citations
        setMessages((msgs) => [
          ...msgs.slice(0, -1),
          { ...msgs[msgs.length - 1], citations: event_obj.citations },
        ]);
      }
    };
    ws.current.onerror = (error) => console.error('WebSocket error:', error);
    ws.current.onclose = (event) => {
      setIsConnected(false);
      if (event.code === 4401) {
        console.log('Session expired; re-authenticate');
      }
    };

    return () => ws.current?.close();
  }, []);

  const sendMessage = () => {
    if (!isConnected) return;
    ws.current.send(
      JSON.stringify({
        type: 'chat_message',
        message: inputValue,
        thread_id: 'conv_abc123def456',
      })
    );
    setMessages((msgs) => [...msgs, { role: 'user', content: inputValue }]);
    setInputValue('');
    setMessages((msgs) => [...msgs, { role: 'assistant', content: '' }]);
  };

  return (
    <div>
      <div>{messages.map((msg) => <p key={msg.id}>{msg.content}</p>)}</div>
      <input
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        disabled={!isConnected}
      />
      <button onClick={sendMessage} disabled={!isConnected}>
        Send
      </button>
    </div>
  );
}
```

---

## Python Example (asyncio)

```python
import asyncio
import json
import websockets

async def chat_session(thread_id: str, cookie: str):
    url = f"wss://agentic-hybrid-search-XXXX.run.app/ws/{thread_id}"
    headers = {"Cookie": f"ahs_session={cookie}"}

    async with websockets.connect(url, additional_headers=headers) as ws:
        # Wait for connection_established
        event = json.loads(await ws.recv())
        assert event["type"] == "connection_established"
        print(f"Connected to thread {event['thread_id']}")

        # Send a message
        await ws.send(
            json.dumps({
                "type": "chat_message",
                "message": "Find wireless headphones under $100",
                "thread_id": thread_id,
            })
        )

        # Stream events
        full_response = ""
        async for message in ws:
            event = json.loads(message)
            event_type = event.get("type")

            if event_type == "llm_response_chunk":
                chunk = event.get("chunk", "")
                print(chunk, end="", flush=True)
                full_response += chunk

            elif event_type == "agent_complete":
                citations = event.get("citations", [])
                print(f"\n\nCitations: {citations}")

            elif event_type == "pipeline_summary":
                metrics = event.get("metrics", {})
                print(f"Latency: {metrics.get('total_latency_ms')} ms")

        print("\n[Session complete]")

# Run
if __name__ == "__main__":
    cookie = "..."  # From login
    thread_id = "conv_abc123def456"
    asyncio.run(chat_session(thread_id, cookie))
```

---

For REST API examples, see [REST API](rest-api.md). For auth details, see [Auth Patterns](auth-patterns.md).
