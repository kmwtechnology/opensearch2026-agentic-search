"""LLM response content normalization shared by the pipeline nodes and
conversation management (split out of main.py in #47)."""

from typing import Any


def _flatten_llm_content(response: Any) -> str:
    """Normalize an LLM response's `content` to a flat string.

    Gemini-family models return ``content`` as a list of content blocks
    (e.g. ``[{"type": "text", "text": "..."}, ...]``) instead of a flat
    string. Pydantic event models in api/schemas/events.py declare these
    fields as ``str``, so passing the raw list raises a validation error.
    This helper picks out the text blocks and joins them.

    Accepts either an ``AIMessage``-like object (extracts ``.content``)
    or a raw content payload.
    """
    content = getattr(response, "content", response)
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return content if isinstance(content, str) else str(content)
