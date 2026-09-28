"""Shared request-validation helpers for API schemas.

Centralizes THREAD_ID_PATTERN so REST (conversations.py) and WebSocket/REST
chat (chat.py) endpoints agree on what a valid thread_id looks like -- these
used to be two independently-maintained regexes that had already diverged
(chat.py required a letter-led ID, conversations.py allowed a digit-led one),
so a thread_id accepted by one endpoint could be rejected by the other.
"""

import re

# Must start with a letter, then alphanumeric/underscore/hyphen, max 64 chars.
# Matches what the frontend actually generates (`conversation_<random>`,
# web/src/stores/chatStore.ts).
THREAD_ID_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")

THREAD_ID_ERROR_MESSAGE = (
    "thread_id must start with a letter and contain only "
    "alphanumeric characters, underscores, or hyphens (max 64 chars)"
)


def validate_thread_id_value(v: str) -> str:
    """Raise ValueError if `v` isn't a valid thread_id. For pydantic field_validators."""
    if not THREAD_ID_PATTERN.match(v):
        raise ValueError(THREAD_ID_ERROR_MESSAGE)
    return v


def validate_message_content_value(v: str) -> str:
    """Raise ValueError if `v` is empty/whitespace-only. For pydantic field_validators."""
    v = v.strip()
    if not v:
        raise ValueError("message cannot be empty or whitespace only")
    return v
