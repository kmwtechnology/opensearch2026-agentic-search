"""Unit tests for the Langfuse callback integration (local-dev only).

Covers the two isolation guarantees:
1. Flag gate — get_callbacks() is a no-op unless LANGFUSE_ENABLED is true.
2. Package absence — a missing/broken langfuse SDK degrades to [] instead of crashing,
   and the SDK is never referenced by any production dependency or GCP deploy path.
"""

import os
import sys
from contextlib import ExitStack
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

import integrations.langfuse_integration as lfi

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))


def _fake_sdk(client_cls=None, handler_cls=None, get_client=None):
    """Stand-in `langfuse` package: Langfuse, get_client, and langchain.CallbackHandler."""
    root = ModuleType("langfuse")
    root.Langfuse = client_cls or MagicMock(name="Langfuse")
    root.get_client = get_client or MagicMock(name="get_client")
    sub = ModuleType("langfuse.langchain")
    sub.CallbackHandler = handler_cls or MagicMock(name="CallbackHandler")
    root.langchain = sub
    return {"langfuse": root, "langfuse.langchain": sub}


def _enabled(*, modules, public_key="pk_test", secret_key="sk_test"):
    """Patch config to enabled, reset the once-per-process resolve state, inject a fake SDK."""
    stack = ExitStack()
    stack.enter_context(patch.object(lfi, "LANGFUSE_ENABLED", True))
    stack.enter_context(patch.object(lfi, "LANGFUSE_PUBLIC_KEY", public_key))
    stack.enter_context(patch.object(lfi, "LANGFUSE_SECRET_KEY", secret_key))
    stack.enter_context(patch.object(lfi, "LANGFUSE_BASE_URL", "http://localhost:3000"))
    stack.enter_context(patch.object(lfi, "_resolved", False))
    stack.enter_context(patch.object(lfi, "_handler_cls", None))
    stack.enter_context(patch.dict(sys.modules, modules))
    return stack


def test_disabled_by_default_returns_empty():
    with patch.object(lfi, "LANGFUSE_ENABLED", False), patch.object(lfi, "_resolved", False):
        assert lfi.get_callbacks() == []


def test_enabled_returns_handler_and_inits_client_once():
    client_cls = MagicMock(name="Langfuse")
    handler_instance = MagicMock(name="handler")
    handler_cls = MagicMock(name="CallbackHandler", return_value=handler_instance)

    with _enabled(modules=_fake_sdk(client_cls, handler_cls)):
        first = lfi.get_callbacks()
        second = lfi.get_callbacks()

    assert first == [handler_instance] and second == [handler_instance]
    client_cls.assert_called_once_with(
        public_key="pk_test", secret_key="sk_test", base_url="http://localhost:3000"
    )
    assert handler_cls.call_count == 2
    handler_cls.assert_called_with(public_key="pk_test", trace_context=None)


def test_missing_keys_returns_empty_without_importing_sdk():
    client_cls = MagicMock(name="Langfuse")
    with _enabled(modules=_fake_sdk(client_cls), secret_key=None):
        assert lfi.get_callbacks() == []
    client_cls.assert_not_called()


def test_missing_sdk_returns_empty():
    # A None entry in sys.modules makes `import langfuse` raise ImportError.
    with _enabled(modules={"langfuse": None, "langfuse.langchain": None}):
        assert lfi.get_callbacks() == []


def test_client_init_failure_returns_empty():
    broken = MagicMock(side_effect=RuntimeError("bad config"))
    with _enabled(modules=_fake_sdk(client_cls=broken)):
        assert lfi.get_callbacks() == []


def test_handler_creation_failure_returns_empty():
    broken = MagicMock(side_effect=RuntimeError("boom"))
    with _enabled(modules=_fake_sdk(handler_cls=broken)):
        assert lfi.get_callbacks() == []


def test_shutdown_is_noop_when_tracing_never_started():
    get_client = MagicMock(name="get_client")
    with _enabled(modules=_fake_sdk(get_client=get_client)):
        lfi.shutdown_tracing()
    get_client.assert_not_called()


def test_shutdown_flushes_active_client():
    client = MagicMock(name="client")
    get_client = MagicMock(name="get_client", return_value=client)
    with _enabled(modules=_fake_sdk(get_client=get_client)):
        assert lfi.get_callbacks()
        lfi.shutdown_tracing()
    get_client.assert_called_once_with(public_key="pk_test")
    client.shutdown.assert_called_once_with()


@pytest.mark.parametrize(
    "relpath",
    [
        "langchain_agent/requirements.txt",
        "langchain_agent/Dockerfile",
        "langchain_agent/scripts/deploy.sh",
        ".github/workflows/build-deploy.yml",
    ],
)
def test_langfuse_absent_from_production_paths(relpath):
    with open(os.path.join(REPO_ROOT, relpath)) as f:
        assert "langfuse" not in f.read().lower(), f"{relpath} must not reference langfuse"


def test_langfuse_present_in_dev_requirements():
    with open(os.path.join(REPO_ROOT, "langchain_agent/requirements-dev.txt")) as f:
        assert "langfuse" in f.read().lower()


def test_record_metrics_noop_when_disabled():
    with patch.object(lfi, "LANGFUSE_ENABLED", False):
        lfi.record_metrics("trace123", foo=1.0)  # must not raise


def test_record_metrics_noop_when_trace_id_none():
    client_cls = MagicMock(name="Langfuse")
    with _enabled(modules=_fake_sdk(client_cls=client_cls)):
        assert lfi.get_callbacks(trace_id="t1")  # resolves _handler_cls
        lfi.record_metrics(None, foo=1.0)  # must not raise
    client_cls.assert_called_once()  # resolve happened, but no score created


def test_record_metrics_noop_when_not_resolved():
    with patch.object(lfi, "LANGFUSE_ENABLED", True), patch.object(lfi, "_handler_cls", None):
        lfi.record_metrics("trace123", foo=1.0)  # must not raise; never imports langfuse


def test_record_metrics_creates_score_per_metric():
    client = MagicMock(name="client")
    get_client = MagicMock(name="get_client", return_value=client)

    with _enabled(modules=_fake_sdk(get_client=get_client)):
        assert lfi.get_callbacks(trace_id="trace123")  # resolves _handler_cls
        lfi.record_metrics("trace123", retriever_latency_ms=12.3, bm25_latency_ms=4.5)

    get_client.assert_called_once_with(public_key="pk_test")
    assert client.create_score.call_count == 2
    client.create_score.assert_any_call(
        trace_id="trace123", name="retriever_latency_ms", value=12.3, data_type="NUMERIC"
    )
    client.create_score.assert_any_call(
        trace_id="trace123", name="bm25_latency_ms", value=4.5, data_type="NUMERIC"
    )


def test_record_metrics_scores_strings_as_categorical():
    """String values (e.g. an LLM-judge verdict or hallucination category) score CATEGORICAL."""
    client = MagicMock(name="client")
    get_client = MagicMock(name="get_client", return_value=client)

    with _enabled(modules=_fake_sdk(get_client=get_client)):
        assert lfi.get_callbacks(trace_id="trace123")
        lfi.record_metrics("trace123", judge_verdict="llm_response", judge_faithfulness=0.92)

    assert client.create_score.call_count == 2
    client.create_score.assert_any_call(
        trace_id="trace123", name="judge_verdict", value="llm_response", data_type="CATEGORICAL"
    )
    client.create_score.assert_any_call(
        trace_id="trace123", name="judge_faithfulness", value=0.92, data_type="NUMERIC"
    )


def test_record_metrics_swallows_errors():
    get_client = MagicMock(name="get_client", side_effect=RuntimeError("connection error"))
    with _enabled(modules=_fake_sdk(get_client=get_client)):
        assert lfi.get_callbacks(trace_id="trace123")
        lfi.record_metrics("trace123", foo=1.0)  # must not raise


def test_new_trace_id_noop_when_disabled():
    with patch.object(lfi, "LANGFUSE_ENABLED", False):
        assert lfi.new_trace_id() is None


def test_new_trace_id_delegates_to_sdk():
    client_cls = MagicMock(name="Langfuse")
    client_cls.create_trace_id = MagicMock(return_value="generated-id")
    with _enabled(modules=_fake_sdk(client_cls=client_cls)):
        assert lfi.new_trace_id(seed="thread-1") == "generated-id"
    client_cls.create_trace_id.assert_called_once_with(seed="thread-1")


def test_configure_playground_skips_without_google_api_key():
    import scripts.configure_langfuse_playground as script

    with patch.object(script, "GOOGLE_API_KEY", None):
        assert script.main() == 0


def _fake_playground_sdk(client_cls):
    """Fake `langfuse` package tree for configure_langfuse_playground.py's imports:
    `from langfuse import Langfuse` and
    `from langfuse.api.llm_connections.types.llm_adapter import LlmAdapter`.
    Built via sys.modules injection (not `patch("langfuse.Langfuse")`) because CI's
    unit-test job only installs requirements.txt, never requirements-dev.txt -- the
    real `langfuse` package is never importable there, by design (mirrors prod).
    """
    root = ModuleType("langfuse")
    root.Langfuse = client_cls
    api = ModuleType("langfuse.api")
    llm_connections = ModuleType("langfuse.api.llm_connections")
    types_mod = ModuleType("langfuse.api.llm_connections.types")
    adapter_mod = ModuleType("langfuse.api.llm_connections.types.llm_adapter")
    adapter_mod.LlmAdapter = MagicMock(name="LlmAdapter", GOOGLE_AI_STUDIO="google-ai-studio")
    root.api = api
    api.llm_connections = llm_connections
    llm_connections.types = types_mod
    types_mod.llm_adapter = adapter_mod
    return {
        "langfuse": root,
        "langfuse.api": api,
        "langfuse.api.llm_connections": llm_connections,
        "langfuse.api.llm_connections.types": types_mod,
        "langfuse.api.llm_connections.types.llm_adapter": adapter_mod,
    }


def test_configure_playground_upserts_connection():
    import scripts.configure_langfuse_playground as script

    client_instance = MagicMock(name="client")
    client_cls = MagicMock(name="Langfuse", return_value=client_instance)

    with (
        patch.object(script, "GOOGLE_API_KEY", "test-key"),
        patch.dict(sys.modules, _fake_playground_sdk(client_cls)),
    ):
        assert script.main() == 0

    client_instance.api.llm_connections.upsert.assert_called_once()
    _, kwargs = client_instance.api.llm_connections.upsert.call_args
    assert kwargs["provider"] == "google-ai-studio"
    assert kwargs["secret_key"] == "test-key"
