"""
Unit tests for observability.otel — opt-in OTLP tracing setup.
"""

import pytest

from observability import otel


@pytest.fixture(autouse=True)
def reset_provider():
    otel._provider = None
    yield
    otel._provider = None


@pytest.mark.unit
class TestSetupTracing:
    def test_noop_without_endpoint(self, monkeypatch):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        assert otel.setup_tracing() is None

    def test_shutdown_is_noop_when_disabled(self, monkeypatch):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        otel.shutdown_tracing()  # must not raise

    def test_enabled_installs_provider_once(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:1")
        monkeypatch.setenv("OTEL_SERVICE_NAME", "test-svc")
        instrumented = []
        monkeypatch.setattr(
            "opentelemetry.instrumentation.langchain.LangchainInstrumentor.instrument",
            lambda self: instrumented.append(True),
        )
        monkeypatch.setattr("opentelemetry.trace.set_tracer_provider", lambda p: None)

        provider = otel.setup_tracing()
        assert provider is not None
        assert provider.resource.attributes["service.name"] == "test-svc"
        assert otel.setup_tracing() is provider
        assert instrumented == [True]

        otel.shutdown_tracing()
        assert otel._provider is None
