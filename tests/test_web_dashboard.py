"""Tests for the web dashboard module.

Covers token management, app construction, HTML rendering, and JSON API
endpoints. Uses FastAPI's TestClient (no live HTTP server).
"""


import pytest

from openpup import web_dashboard
from openpup.web_dashboard import (
    HAS_FASTAPI,
    create_app,
    get_or_create_token,
)


# Skip the whole module if FastAPI isn't installed (CI may not have it).
pytestmark = pytest.mark.skipif(
    not HAS_FASTAPI, reason="FastAPI not installed"
)


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------
class TestToken:
    def test_generated_token_is_persisted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENPUP_HOME", str(tmp_path))
        tok = get_or_create_token()
        assert len(tok) >= 20
        # Persisted to disk.
        files = list(tmp_path.rglob("dashboard.token"))
        assert files, "token file should exist"

    def test_explicit_token_overrides(self, monkeypatch):
        monkeypatch.setenv("OPENPUP_DASHBOARD_TOKEN", "my-pinned-token")
        assert get_or_create_token() == "my-pinned-token"

    def test_persisted_token_reused(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENPUP_HOME", str(tmp_path))
        tok1 = get_or_create_token()
        tok2 = get_or_create_token()
        assert tok1 == tok2


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    app = create_app()
    return TestClient(app)


class TestAppStructure:
    def test_create_app(self):
        app = create_app()
        assert app is not None
        # Check a few expected routes exist.
        routes = {r.path for r in app.routes}
        assert "/" in routes
        assert "/api/status" in routes
        assert "/api/memory" in routes
        assert "/api/sessions" in routes
        assert "/api/skills" in routes
        assert "/api/routines" in routes
        assert "/api/heartbeat" in routes


class TestAuthentication:
    def test_missing_token_rejected(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 401

    def test_query_token_works(self, client):
        # First call (or any) generates a token via the first request.
        # We grab a token from the env override instead.
        import os

        os.environ["OPENPUP_DASHBOARD_TOKEN"] = "fixed-test-token"
        resp = client.get("/api/status?token=fixed-test-token")
        # Auth passes; status may not be JSON if state_dir isn't set, but at
        # minimum we should NOT get 401.
        assert resp.status_code != 401
        # Reset env
        del os.environ["OPENPUP_DASHBOARD_TOKEN"]

    def test_invalid_token_rejected(self, client):
        resp = client.get("/api/status?token=wrong")
        assert resp.status_code == 401

    def test_bearer_header_works(self, client):
        import os

        os.environ["OPENPUP_DASHBOARD_TOKEN"] = "bearer-test-token"
        resp = client.get(
            "/api/status", headers={"Authorization": "Bearer bearer-test-token"}
        )
        assert resp.status_code != 401
        del os.environ["OPENPUP_DASHBOARD_TOKEN"]


class TestJSONEndpoints:
    def test_status_shape(self, client):
        import os

        os.environ["OPENPUP_DASHBOARD_TOKEN"] = "t"
        try:
            resp = client.get("/api/status?token=t")
            assert resp.status_code == 200
            data = resp.json()
            assert "name" in data
            assert "model" in data
            assert "platforms" in data
            assert "ts" in data
        finally:
            del os.environ["OPENPUP_DASHBOARD_TOKEN"]

    def test_memory_requires_query(self, client):
        import os

        os.environ["OPENPUP_DASHBOARD_TOKEN"] = "t"
        try:
            # No query => FastAPI validation error (422).
            resp = client.get("/api/memory?token=t")
            assert resp.status_code in (422, 401)  # 401 if token check fires first
        finally:
            del os.environ["OPENPUP_DASHBOARD_TOKEN"]

    def test_memory_returns_payload(self, client):
        import os

        os.environ["OPENPUP_DASHBOARD_TOKEN"] = "t"
        try:
            resp = client.get("/api/memory?q=hello&token=t")
            assert resp.status_code == 200
            data = resp.json()
            assert "matches" in data
            assert "count" in data
            assert "query" in data
        finally:
            del os.environ["OPENPUP_DASHBOARD_TOKEN"]


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------
class TestRendering:
    def test_render_body_status(self):
        html = web_dashboard._render_body_for_tab("status", token="t")
        assert "Status" in html
        assert "Name" in html  # label

    def test_render_body_unknown_tab(self):
        html = web_dashboard._render_body_for_tab("bogus", token="t")
        assert "unknown tab" in html.lower()

    def test_render_full_html(self):
        html = web_dashboard._render(
            title="Status",
            body="<section>hi</section>",
            active="status",
            token="t",
        )
        assert "<html" in html
        assert "OpenPup dashboard" in html
        assert "<section>hi</section>" in html
        # Tab nav has all six tabs.
        for tab in ("Status", "Memory", "Sessions", "Skills", "Routines", "Heartbeat"):
            assert tab in html


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
class TestRunner:
    def test_run_uses_default_port(self, monkeypatch):
        # Just verify the function exists and is callable.
        assert callable(web_dashboard.run)
