// Must satisfy the backend's THREAD_ID_PATTERN (api/schemas/validation.py):
// letter-led, then [A-Za-z0-9_-], max 64 chars.
export function newThreadId(): string {
  return `conversation_${Math.random().toString(36).slice(2, 10)}`
}
