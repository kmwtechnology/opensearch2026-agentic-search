# ConversationsSidebar

[← components](../) | [← web/src](../../)

Navigation sidebar: conversation list with filtering, thread switching, and session logout.

## Files

| File | Purpose |
|------|---------|
| `index.tsx` | Container sidebar with conversation list, new-conversation button, logout |
| `ConversationItem.tsx` | Individual conversation list item with click-to-switch and hover actions |

## Store Dependencies

- `chatStore` — conversation list, current thread ID, loading state
- `authStore` — logout action

## Key Concepts

**Thread Switching:** Clicking a conversation item calls `chatStore.setThreadId(id)` → fetches message history → re-renders chat panel.

**New Conversation:** "+" button creates new thread (server generates UUID) → sets as active.

**Logout:** Two-click confirm → `authStore.logout()` → clears session cookie → redirects to LoginScreen.

**Sorting:** Conversations sorted by `updated_at` descending (most recent first). Optional search/filter for large conversation lists (future optimization).

**Keyboard Navigation:** Arrow keys cycle through list items, Enter to switch. Escape to close on mobile.
