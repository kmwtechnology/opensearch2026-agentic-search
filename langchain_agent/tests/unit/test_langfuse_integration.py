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
    handler_cls.assert_called_with(public_key="pk_test")


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
