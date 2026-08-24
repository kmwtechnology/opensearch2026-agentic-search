# ChatPanel

[← components](../) | [← web/src](../../)

Chat interface: message list, input field with typeahead, citation display, and streaming message rendering.

## Files

| File | Purpose |
|------|---------|
| `index.tsx` | Container component composing message list + input field |
| `MessageList.tsx` | Scrollable conversation history with auto-scroll on new messages |
| `Message.tsx` | Individual message renderer with markdown, citations, code highlighting |
| `MessageInput.tsx` | Text input with multi-line support, send button, loading state |
| `TypeaheadSuggestions.tsx` | Real-time query suggestion dropdown (recent searches + spell-correction) |

## Store Dependencies

- `chatStore` — messages, thread ID, streaming state, processing flag
- `authStore` — login state (hide input if not authenticated)
- `optimizationsStore` — UI display mode toggles

## Key Concepts

**Streaming:** As server emits `LLMResponseChunkEvent` events, chunks append to `streamingContent` in store. When complete, chunk is moved to `messages` array.

**Citations:** Rendered as links below message text. Deduplicated and filtered by minimum reranker score (0.10). URLs default to Amazon search-by-title form (`https://www.amazon.com/s?k={title}`).

**Typeahead:** Triggered on keystroke with debounce. Returns recent searches (from browser localStorage via `useRecentSearches()`) + spell-corrected versions. Skips correction when query is a corpus token or corpus prefix.

**Markdown & Code:** Messages use `react-markdown` + `highlight.js` for code block syntax highlighting (bash, python, sql, etc.).
