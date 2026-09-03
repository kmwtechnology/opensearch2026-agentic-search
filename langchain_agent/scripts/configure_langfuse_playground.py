"""Configure Langfuse's Playground with a Google AI Studio LLM connection.

Run after `docker compose --profile observability up -d` (see `make langfuse-up`).
Idempotent: upsert keys on provider name, safe to re-run. Local dev only --
never invoked from any GCP-deployed path.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import GOOGLE_API_KEY, LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY


def main() -> int:
    if not GOOGLE_API_KEY:
        print("GOOGLE_API_KEY not set in .env -- skipping Playground configuration.")
        return 0

    try:
        from langfuse import Langfuse
        from langfuse.api.llm_connections.types.llm_adapter import LlmAdapter
    except ImportError:
        print("langfuse SDK not installed -- run `pip install -r requirements-dev.txt` first.")
        return 1

    client = Langfuse(
        public_key=LANGFUSE_PUBLIC_KEY, secret_key=LANGFUSE_SECRET_KEY, base_url=LANGFUSE_BASE_URL
    )
    try:
        client.api.llm_connections.upsert(
            provider="google-ai-studio",
            adapter=LlmAdapter.GOOGLE_AI_STUDIO,
            secret_key=GOOGLE_API_KEY,
            with_default_models=True,
        )
    except Exception as exc:
        print(
            f"Could not configure Langfuse Playground (is Langfuse up? {LANGFUSE_BASE_URL}): {exc}"
        )
        return 1

    print(f"Langfuse Playground configured with Google AI Studio at {LANGFUSE_BASE_URL}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
