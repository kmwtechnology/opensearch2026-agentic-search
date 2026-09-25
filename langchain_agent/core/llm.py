"""
The one place chat models are constructed (#148): local Ollama via ChatOllama.

Every LLM caller -- generation, intent/alpha evaluation, the LLM judge, the
enrichment value judge -- builds its model here, so model settings that must
hold everywhere live in one spot:

* ``reasoning=False``: Qwen3-family models "think" by default, which adds
  seconds per call and, for structured output, puts reasoning text where a
  JSON object is expected. Nothing in this pipeline consumes the reasoning.
* ``num_ctx``: Ollama *silently truncates* a prompt longer than the context
  window (its default is small), and the agent's system prompt plus product
  context plus conversation history runs long. Set explicitly, never defaulted.
* ``keep_alive``: a cold model load is 7-18s -- keep it resident between turns.
"""

import json
import urllib.request
from typing import Iterable, List, Optional

from langchain_ollama import ChatOllama

from core.config import OLLAMA_HOST, OLLAMA_KEEP_ALIVE, OLLAMA_NUM_CTX


def build_chat_model(
    model: str, temperature: float = 0.0, max_tokens: Optional[int] = None
) -> ChatOllama:
    """ChatOllama with the pipeline-wide settings above. ``max_tokens`` caps output."""
    return ChatOllama(
        model=model,
        base_url=OLLAMA_HOST,
        temperature=temperature,
        num_predict=max_tokens,
        num_ctx=OLLAMA_NUM_CTX,
        keep_alive=OLLAMA_KEEP_ALIVE,
        reasoning=False,
    )


def missing_ollama_models(models: Iterable[str]) -> List[str]:
    """Which of ``models`` the Ollama server hasn't pulled.

    Raises ``OSError`` (``URLError``) if the server is unreachable -- callers
    decide whether that's fatal. Tags are listed as ``name:tag``; a configured
    name without a tag means ``:latest``.
    """
    with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=5) as resp:
        pulled = {m["name"] for m in json.load(resp)["models"]}
    return [m for m in dict.fromkeys(models) if m not in pulled and f"{m}:latest" not in pulled]
