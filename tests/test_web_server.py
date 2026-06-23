"""Unit tests for the FastAPI web server (a2a_orchestrator.web_server)."""
from __future__ import annotations

import importlib
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def web_app(env_isolated, tmp_path, monkeypatch):
    """Create a FastAPI app with a fresh server module."""
    monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "web.jsonl"))

    # Force re-import of config + server.
    for mod in list(sys.modules):
        if mod.startswith("a2a_orchestrator"):
            monkeypatch.delitem(sys.modules, mod, raising=False)

    import a2a_orchestrator.config as config_mod
    importlib.reload(config_mod)
    import a2a_orchestrator.server as srv
    importlib.reload(srv)
    srv.registry.load()
    srv.session_store.clear()
    srv.message_store = srv.MessageStore(path=tmp_path / "web.jsonl")
    # C2 fix: send_a2a now uses ctx.message_store (per-tenant), so we
    # must also update the default tenant context's store.
    srv._default_ctx.message_store = srv.message_store

    from a2a_orchestrator.web_server import create_app
    app = create_app(server_module=srv)
    return app, srv


class TestHealthEndpoint:
    def test_health_check(self, web_app):
        app, _ = web_app
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["service"] == "a2a-orchestrator"


class TestAgentsEndpoint:
    def test_list_agents(self, web_app):
        app, _ = web_app
        client = TestClient(app)
        resp = client.get("/v1/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "agents" in data
        assert data["count"] >= 0


class TestMetricsEndpoint:
    def test_get_metrics(self, web_app):
        app, _ = web_app
        client = TestClient(app)
        resp = client.get("/v1/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "messages_delivered" in data


class TestChainEndpoint:
    def test_get_chain_status(self, web_app):
        app, _ = web_app
        client = TestClient(app)
        resp = client.get("/v1/chain/conv-test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "chain" in data


class TestSendEndpoint:
    def test_send_a2a(self, web_app):
        app, _ = web_app
        client = TestClient(app)
        resp = client.post("/v1/send", json={
            "target": "agent-b",
            "reason": "Need DBA help with schema change.",
            "summary": "User wants to add archived_at column to orders table.",
            "from_id": "agent-a",
            "session_id": "conv-web-001",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["next_senior"] == "agent-b"

    def test_send_missing_field(self, web_app):
        app, _ = web_app
        client = TestClient(app)
        resp = client.post("/v1/send", json={
            "target": "agent-b",
            # missing reason, summary, from_id
        })
        assert resp.status_code == 422


class TestSagaEndpoint:
    def test_get_saga_not_found(self, web_app):
        app, _ = web_app
        client = TestClient(app)
        resp = client.get("/v1/saga/saga-nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False


class TestSearchEndpoint:
    def test_search(self, web_app):
        app, _srv = web_app
        client = TestClient(app)
        # First send a message so there's something to search.
        client.post("/v1/send", json={
            "target": "agent-b",
            "reason": "Need DBA help with migration.",
            "summary": "User wants to add a column to the orders table.",
            "from_id": "agent-a",
            "session_id": "conv-search-001",
        })
        resp = client.post("/v1/search", json={"query": "migration"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["count"] >= 1

    def test_search_missing_query(self, web_app):
        app, _ = web_app
        client = TestClient(app)
        resp = client.post("/v1/search", json={})
        assert resp.status_code == 422


class TestRegisterEndpoints:
    def test_create_challenge(self, web_app):
        app, _ = web_app
        client = TestClient(app)
        resp = client.post("/v1/register/challenge", json={"agent_id": "agent-new"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "challenge" in data

    def test_create_challenge_missing_agent_id(self, web_app):
        app, _ = web_app
        client = TestClient(app)
        resp = client.post("/v1/register/challenge", json={})
        assert resp.status_code == 422


class TestTenantsEndpoint:
    def test_list_tenants(self, web_app):
        app, _ = web_app
        client = TestClient(app)
        resp = client.get("/v1/tenants")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["count"] >= 1  # at least "default"


class TestCorsHeaders:
    def test_cors_origin_header(self, web_app):
        app, _ = web_app
        client = TestClient(app)
        # Preflight request.
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers


class TestApiKeyAuth:
    def test_auth_required_when_key_set(self, env_isolated, tmp_path, monkeypatch):
        """When A2A_WEB_API_KEY is set, requests without it are rejected."""
        monkeypatch.setenv("A2A_WEB_API_KEY", "secret-key-123")
        monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "web.jsonl"))

        for mod in list(sys.modules):
            if mod.startswith("a2a_orchestrator"):
                monkeypatch.delitem(sys.modules, mod, raising=False)

        import a2a_orchestrator.config as config_mod
        importlib.reload(config_mod)
        import a2a_orchestrator.server as srv
        importlib.reload(srv)
        srv.registry.load()
        srv.session_store.clear()
        srv.message_store = srv.MessageStore(path=tmp_path / "web.jsonl")
        # C2 fix: send_a2a now uses ctx.message_store (per-tenant).
        srv._default_ctx.message_store = srv.message_store

        from a2a_orchestrator.web_server import create_app
        app = create_app(server_module=srv)
        client = TestClient(app)

        # Without API key → 401.
        resp = client.get("/v1/agents")
        assert resp.status_code == 401

        # With correct API key → 200.
        resp = client.get("/v1/agents", headers={"X-API-Key": "secret-key-123"})
        assert resp.status_code == 200

    def test_health_does_not_require_auth(self, env_isolated, tmp_path, monkeypatch):
        """The /health endpoint does not require auth even when API key is set."""
        monkeypatch.setenv("A2A_WEB_API_KEY", "secret-key-123")
        monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "web.jsonl"))

        for mod in list(sys.modules):
            if mod.startswith("a2a_orchestrator"):
                monkeypatch.delitem(sys.modules, mod, raising=False)

        import a2a_orchestrator.config as config_mod
        importlib.reload(config_mod)
        import a2a_orchestrator.server as srv
        importlib.reload(srv)
        srv.registry.load()

        from a2a_orchestrator.web_server import create_app
        app = create_app(server_module=srv)
        client = TestClient(app)

        resp = client.get("/health")
        assert resp.status_code == 200
