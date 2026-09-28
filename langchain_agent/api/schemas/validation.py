"""Shared request-validation helpers for API schemas.

THREAD_ID_PATTERN is the one definition of a valid thread_id; both chat
schemas in api/routes/chat.py validate through it.
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
