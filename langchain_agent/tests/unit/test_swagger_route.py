"""Pre-flight guard for the FastAPI auto-doc route.

The Swagger UI lives at ``/swagger`` (renamed from FastAPI's default
``/docs``). The frontend's ``SwaggerPage`` iframe and the sidebar's "API"
link both target ``/swagger`` — if anyone flips the FastAPI ``docs_url``
back to ``/docs`` (the framework default), those iframes silently 404.

The test reads the FastAPI app config statically — it doesn't boot the
service or hit OpenSearch / Postgres, so it's safe to run with no
infrastructure.
"""

import pytest

from api.main import app


@pytest.mark.unit
class TestSwaggerRoute:
    def test_swagger_is_served_at_swagger(self):
        """``/swagger`` must serve the API docs.

        FastAPI's built-in docs_url is deliberately None (#103): the stock
        Swagger UI renders at ~12px, which is unreadable projected, and the SPA
        embeds this page cross-origin so it cannot restyle it. A custom route
        serves the same generated spec with projector-sized CSS. What matters
        is that the PATH still works — the frontend iframe and the header link
        both target it.
        """
        paths = {getattr(r, "path", None) for r in app.routes}
        assert "/swagger" in paths, (
            "Expected a route at /swagger. Frontend SwaggerPage iframe and the "
            f"header link target it. Got: {sorted(p for p in paths if p)}"
        )
        assert app.docs_url is None, (
            "docs_url should stay None so FastAPI's default (small-type) docs "
            "route does not shadow the projector-sized one."
        )

    def test_redoc_still_at_default(self):
        """Sanity check: redoc URL is unaffected by the rename."""
        assert app.redoc_url == "/redoc"

    def test_swagger_path_registered(self):
        """The /swagger path must appear in the registered routes."""
        paths = {route.path for route in app.routes if hasattr(route, "path")}
        assert "/swagger" in paths, (
            "FastAPI registers docs_url as a route automatically; missing "
            "/swagger means docs_url got disabled (set to None)."
        )

    def test_legacy_docs_path_not_registered(self):
        """The legacy /docs path must NOT be registered — it would shadow the
        SPA's React-Router /docs route had we kept one (we renamed to /swagger).
        """
        paths = {route.path for route in app.routes if hasattr(route, "path")}
        assert "/docs" not in paths, (
            "Legacy /docs route is still registered. After the rename, "
            "FastAPI should only expose /swagger for the auto-docs."
        )
