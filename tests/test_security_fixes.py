"""Tests for security fixes H1-H4, M1-M3, L1-L3.

Each test targets a specific finding from the security review and
verifies the fix prevents the attack vector.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# --------------------------------------------------------------------------- #
# H1: Path traversal via unsanitized tenant_id
# --------------------------------------------------------------------------- #

class TestH1PathTraversal:
    """tenant_id must be validated before any path join."""

    @pytest.mark.parametrize("malicious_id", [
        "../../etc",
        "..",
        "/etc/passwd",
        "foo/../bar",
        "foo/../../baz",
        ".hidden",
        "UPPERCASE",
        "with space",
        "with;semicolon",
        "with|pipe",
    ])
    def test_malicious_tenant_id_rejected_by_tenant_manager(self, malicious_id):
        """TenantManager.get_or_create rejects path-traversal tenant ids."""
        from a2a_orchestrator.tenant import TenantManager
        mgr = TenantManager(default_cards_dir=Path("/tmp/nonexistent"))
        with pytest.raises(ValueError, match="Invalid tenant_id"):
            mgr.get_or_create(malicious_id)

    def test_malicious_tenant_id_rejected_by_resolve_tenant(self, monkeypatch):
        """server._resolve_tenant rejects path-traversal tenant ids."""
        monkeypatch.setenv("A2A_FALLBACK_JSONL", tempfile.mktemp(suffix=".jsonl"))
        for mod in list(sys.modules):
            if mod.startswith("a2a_orchestrator"):
                monkeypatch.delitem(sys.modules, mod, raising=False)
        import a2a_orchestrator.config as config_mod
        importlib.reload(config_mod)
        import a2a_orchestrator.server as srv
        importlib.reload(srv)
        with pytest.raises(ValueError, match="Invalid tenant_id"):
            srv._resolve_tenant("../../etc")

    def test_valid_tenant_id_accepted(self, tmp_path):
        """Valid kebab-case tenant ids are accepted."""
        from a2a_orchestrator.tenant import TenantManager
        mgr = TenantManager(default_cards_dir=tmp_path)
        ctx = mgr.get_or_create("tenant-ok")
        assert ctx.tenant_id == "tenant-ok"

    def test_default_tenant_accepted(self, tmp_path):
        """The default tenant id passes validation."""
        from a2a_orchestrator.tenant import DEFAULT_TENANT, TenantManager
        mgr = TenantManager(default_cards_dir=tmp_path)
        ctx = mgr.get_or_create(DEFAULT_TENANT)
        assert ctx.tenant_id == DEFAULT_TENANT


# --------------------------------------------------------------------------- #
# H2: Constant-time API key comparison (web server)
# --------------------------------------------------------------------------- #

class TestH2ConstantTimeAPIKey:
    """Web server API key check must use secrets.compare_digest."""

    def test_valid_api_key_accepted(self, env_isolated, tmp_path, monkeypatch):
        monkeypatch.setenv("A2A_WEB_API_KEY", "secret-key-12345")
        monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "h2.jsonl"))
        for mod in list(sys.modules):
            if mod.startswith("a2a_orchestrator"):
                monkeypatch.delitem(sys.modules, mod, raising=False)
        import a2a_orchestrator.config as config_mod
        importlib.reload(config_mod)
        import a2a_orchestrator.server as srv
        importlib.reload(srv)
        srv.registry.load()
        srv.session_store.clear()
        srv.message_store = srv.MessageStore(path=tmp_path / "h2.jsonl")
        srv._default_ctx.message_store = srv.message_store
        from a2a_orchestrator.web_server import create_app
        from fastapi.testclient import TestClient
        app = create_app(server_module=srv)
        client = TestClient(app)
        resp = client.get("/v1/agents", headers={"X-API-Key": "secret-key-12345"})
        assert resp.status_code == 200

    def test_invalid_api_key_rejected(self, env_isolated, tmp_path, monkeypatch):
        monkeypatch.setenv("A2A_WEB_API_KEY", "secret-key-12345")
        monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "h2b.jsonl"))
        for mod in list(sys.modules):
            if mod.startswith("a2a_orchestrator"):
                monkeypatch.delitem(sys.modules, mod, raising=False)
        import a2a_orchestrator.config as config_mod
        importlib.reload(config_mod)
        import a2a_orchestrator.server as srv
        importlib.reload(srv)
        srv.registry.load()
        srv.session_store.clear()
        srv.message_store = srv.MessageStore(path=tmp_path / "h2b.jsonl")
        srv._default_ctx.message_store = srv.message_store
        from a2a_orchestrator.web_server import create_app
        from fastapi.testclient import TestClient
        app = create_app(server_module=srv)
        client = TestClient(app)
        # Slightly different key — must be rejected.
        resp = client.get("/v1/agents", headers={"X-API-Key": "secret-key-12346"})
        assert resp.status_code == 401

    def test_uses_compare_digest_not_equals(self):
        """Verify the source uses secrets.compare_digest, not !=."""
        import inspect

        from a2a_orchestrator import web_server
        source = inspect.getsource(web_server)
        assert "secrets.compare_digest" in source
        # The old vulnerable pattern should not be present in the auth check.
        assert "provided != expected_key" not in source


# --------------------------------------------------------------------------- #
# H3: Constant-time WebSocket auth token comparison
# --------------------------------------------------------------------------- #

class TestH3ConstantTimeWSToken:
    """WebSocket auth token check must use secrets.compare_digest."""

    def test_uses_compare_digest_not_equals(self):
        """Verify the source uses secrets.compare_digest, not !=."""
        import inspect

        from a2a_orchestrator import ws_server
        source = inspect.getsource(ws_server)
        assert "secrets.compare_digest" in source
        assert "provided_token != self._auth_token" not in source

    @pytest.mark.asyncio
    async def test_valid_token_accepted(self):
        """A valid auth token allows subscription."""
        import asyncio

        import websockets
        from a2a_orchestrator.ws_server import WebSocketServer
        server = WebSocketServer(port=18801, auth_token="ws-secret-token")
        await server.start_async()
        try:
            async with websockets.connect("ws://127.0.0.1:18801") as ws:
                await ws.send(json.dumps({
                    "action": "subscribe",
                    "session_id": "s1",
                    "auth_token": "ws-secret-token",
                }))
                resp = await asyncio.wait_for(ws.recv(), timeout=2.0)
                assert json.loads(resp)["ok"] is True
        finally:
            server.stop()

    @pytest.mark.asyncio
    async def test_invalid_token_rejected(self):
        """An invalid auth token is rejected."""
        import asyncio

        import websockets
        from a2a_orchestrator.ws_server import WebSocketServer
        server = WebSocketServer(port=18802, auth_token="ws-secret-token")
        await server.start_async()
        try:
            async with websockets.connect("ws://127.0.0.1:18802") as ws:
                await ws.send(json.dumps({
                    "action": "subscribe",
                    "session_id": "s1",
                    "auth_token": "wrong-token",
                }))
                resp = await asyncio.wait_for(ws.recv(), timeout=2.0)
                parsed = json.loads(resp)
                assert parsed["ok"] is False
                assert "auth_token" in parsed["reason"]
        finally:
            server.stop()


# --------------------------------------------------------------------------- #
# H4: Cross-tenant Mnemos access via load_context
# --------------------------------------------------------------------------- #

class TestH4CrossTenantMnemos:
    """Mnemos session_id must be prefixed with tenant_id for isolation."""

    def test_persist_uses_tenant_prefixed_session_id(self, env_isolated,
                                                     tmp_path, monkeypatch):
        """_persist prefixes the Mnemos session_id with tenant_id."""
        monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "h4.jsonl"))
        for mod in list(sys.modules):
            if mod.startswith("a2a_orchestrator"):
                monkeypatch.delitem(sys.modules, mod, raising=False)
        import a2a_orchestrator.config as config_mod
        importlib.reload(config_mod)
        import a2a_orchestrator.server as srv
        importlib.reload(srv)
        srv.registry.load()
        srv.session_store.clear()
        srv.message_store = srv.MessageStore(path=tmp_path / "h4.jsonl")
        srv._default_ctx.message_store = srv.message_store

        message = {
            "message_id": "msg-h4test0001",
            "session_id": "conv-h4-001",
            "from": "agent-a",
            "to": "agent-b",
            "intent": "handoff",
        }
        with patch.object(srv.mnemos_client, "write_turn") as mock_write:
            srv._persist(message, outcome="delivered",
                         store=srv.message_store, tenant_id="tenant-x")
            mock_write.assert_called_once()
            mnemos_session = mock_write.call_args[0][0]
            assert mnemos_session == "tenant-x:conv-h4-001"

    def test_load_context_uses_tenant_prefixed_session_id(self, env_isolated,
                                                          tmp_path, monkeypatch):
        """load_context prefixes the Mnemos session_id with tenant_id."""
        monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "h4b.jsonl"))
        for mod in list(sys.modules):
            if mod.startswith("a2a_orchestrator"):
                monkeypatch.delitem(sys.modules, mod, raising=False)
        import a2a_orchestrator.config as config_mod
        importlib.reload(config_mod)
        import a2a_orchestrator.server as srv
        importlib.reload(srv)
        srv.registry.load()
        srv.session_store.clear()
        srv.message_store = srv.MessageStore(path=tmp_path / "h4b.jsonl")
        srv._default_ctx.message_store = srv.message_store

        turn_body = {
            "content": json.dumps({"message_id": "msg-h4test0002"}),
        }
        with patch.object(srv.mnemos_client, "get_turn",
                          return_value=turn_body) as mock_get:
            srv.load_context(
                session_id="conv-h4-002",
                turn_id="turn-001",
                tenant_id="tenant-y",
            )
            mock_get.assert_called_once()
            mnemos_session = mock_get.call_args[0][0]
            assert mnemos_session == "tenant-y:conv-h4-002"

    def test_cross_tenant_cannot_read_other_tenant_mnemos(self, env_isolated,
                                                           tmp_path, monkeypatch):
        """Tenant A cannot read tenant B's Mnemos turns.

        Because the session_id is prefixed with tenant_id, a call from
        tenant-a with tenant-b's session_id will query
        "tenant-a:<session>" — not "tenant-b:<session>" — so it gets
        a different (non-existent) turn.
        """
        monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "h4c.jsonl"))
        for mod in list(sys.modules):
            if mod.startswith("a2a_orchestrator"):
                monkeypatch.delitem(sys.modules, mod, raising=False)
        import a2a_orchestrator.config as config_mod
        importlib.reload(config_mod)
        import a2a_orchestrator.server as srv
        importlib.reload(srv)
        srv.registry.load()
        srv.session_store.clear()
        srv.message_store = srv.MessageStore(path=tmp_path / "h4c.jsonl")
        srv._default_ctx.message_store = srv.message_store

        # Tenant B wrote a turn with session "conv-shared".
        # Tenant A tries to read it using the same session_id.
        captured_sessions: list[str] = []

        def fake_get_turn(session_id, turn_id, mode="summary"):
            captured_sessions.append(session_id)
            # Only return data if the session matches tenant-b's prefix.
            if session_id.startswith("tenant-b:"):
                return {"content": json.dumps({
                    "message_id": "msg-secret0001",
                    "from": "agent-b",
                })}
            raise srv.MnemosUnavailableError("not found")

        with patch.object(srv.mnemos_client, "get_turn",
                          side_effect=fake_get_turn):
            # Tenant A tries to read tenant B's session.
            result = srv.load_context(
                session_id="conv-shared",
                turn_id="turn-001",
                tenant_id="tenant-a",
            )
        # The Mnemos call used tenant-a's prefix, so it got "not found".
        assert captured_sessions == ["tenant-a:conv-shared"]
        assert result["ok"] is False


# --------------------------------------------------------------------------- #
# M1: WebSocket tenant isolation
# --------------------------------------------------------------------------- #

class TestM1WebSocketTenantIsolation:
    """WS subscribers are scoped by composite key tenant_id:session_id."""

    def test_composite_key_with_tenant(self):
        from a2a_orchestrator.ws_server import WebSocketServer
        key = WebSocketServer._composite_key("tenant-a", "session-1")
        assert key == "tenant-a:session-1"

    def test_composite_key_without_tenant_backward_compat(self):
        from a2a_orchestrator.ws_server import WebSocketServer
        key = WebSocketServer._composite_key("", "session-1")
        assert key == "session-1"

    @pytest.mark.asyncio
    async def test_tenant_isolation_subscribers(self):
        """Tenant A's broadcast does not reach tenant B's subscriber."""
        import asyncio

        import websockets
        from a2a_orchestrator.ws_server import WebSocketServer
        server = WebSocketServer(port=18803)
        await server.start_async()
        try:
            async with websockets.connect("ws://127.0.0.1:18803") as ws_a, \
                       websockets.connect("ws://127.0.0.1:18803") as ws_b:
                # Tenant A subscribes to session-1.
                await ws_a.send(json.dumps({
                    "action": "subscribe", "session_id": "s1",
                    "tenant_id": "tenant-a",
                }))
                await ws_a.recv()
                # Tenant B subscribes to the same session_id.
                await ws_b.send(json.dumps({
                    "action": "subscribe", "session_id": "s1",
                    "tenant_id": "tenant-b",
                }))
                await ws_b.recv()

                # Broadcast to tenant-a — should only reach ws_a.
                count = await server.broadcast("s1", {"type": "test"},
                                              tenant_id="tenant-a")
                assert count == 1
                ev = await asyncio.wait_for(ws_a.recv(), timeout=2.0)
                assert json.loads(ev)["type"] == "test"
                # ws_b should NOT receive anything — verify with timeout.
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(ws_b.recv(), timeout=0.5)
        finally:
            server.stop()

    def test_broadcast_event_passes_tenant_id(self):
        """broadcast_event forwards tenant_id to broadcast_sync."""
        from a2a_orchestrator import ws_server as ws_mod

        class FakeServer:
            def __init__(self):
                self.last_tenant = None

            def broadcast_sync(self, session_id, event, tenant_id=""):
                self.last_tenant = tenant_id
                return 0

        fake = FakeServer()
        ws_mod._ws_server = fake  # type: ignore[attr-defined]
        try:
            ws_mod.broadcast_event("s1", "a2a_delivered", {"x": 1},
                                   tenant_id="tenant-z")
            assert fake.last_tenant == "tenant-z"
        finally:
            ws_mod._ws_server = None  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# M2: JSONL fallback file permissions
# --------------------------------------------------------------------------- #

class TestM2FilePermissions:
    """JSONL fallback file must be created with 0o600 permissions."""

    def test_file_created_with_owner_only_permissions(self, tmp_path):
        from a2a_orchestrator.persistence import MessageStore
        path = tmp_path / "m2_test.jsonl"
        store = MessageStore(path=path)
        store.append({"message_id": "msg-m2test001", "test": True})
        assert path.exists()
        # On POSIX, check the permission bits.
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    def test_existing_file_permissions_not_changed(self, tmp_path):
        """If the file already exists, _ensure_dir doesn't override perms."""
        from a2a_orchestrator.persistence import MessageStore
        path = tmp_path / "m2_existing.jsonl"
        # Create with 0o644 (world-readable).
        path.write_text("")
        os.chmod(path, 0o644)
        store = MessageStore(path=path)
        store.append({"message_id": "msg-m2test002"})
        mode = path.stat().st_mode & 0o777
        # Pre-existing file keeps its 0o644.
        assert mode == 0o644


# --------------------------------------------------------------------------- #
# M3: Challenge consumed on failed registration
# --------------------------------------------------------------------------- #

class TestM3ChallengeConsumedOnFailure:
    """Challenge must be consumed immediately after signature verification."""

    def test_challenge_consumed_on_duplicate_registration(self, reg_service):
        """If registration fails at the duplicate check, the challenge is gone."""
        from a2a_orchestrator.registration import RegistrationRequest
        from a2a_orchestrator.signing import generate_keypair, sign_message

        agent_id = "agent-dup-test"
        kp = generate_keypair(agent_id)
        card = {
            "id": agent_id,
            "name": "Dup Agent",
            "version": "0.7.0",
            "plugin": "test-plugin",
            "agent_file": f"{agent_id}.agent.md",
            "capabilities": ["test"],
            "routing": {"accepts_routes_from": [], "routing_keywords": ["t"]},
        }
        # First registration succeeds.
        nonce = reg_service.create_challenge(agent_id)
        sig = sign_message({"nonce": nonce, "agent_id": agent_id}, kp.private_key)
        req = RegistrationRequest(agent_card=card, public_key=kp.public_key_b64,
                                  challenge_signature=sig)
        result = reg_service.register(req)
        assert result["ok"] is True

        # Second registration with the SAME challenge — should fail because
        # the challenge was consumed, NOT because of duplicate alone.
        # We need a fresh challenge for the duplicate to be the failure.
        nonce2 = reg_service.create_challenge(agent_id)
        sig2 = sign_message({"nonce": nonce2, "agent_id": agent_id}, kp.private_key)
        req2 = RegistrationRequest(agent_card=card, public_key=kp.public_key_b64,
                                   challenge_signature=sig2)
        result2 = reg_service.register(req2)
        # Fails because agent is already registered (duplicate).
        assert result2["ok"] is False
        assert "already registered" in result2["reason"]

        # M3 fix: the challenge for nonce2 must be consumed — a replay
        # with the same nonce must fail at signature verification.
        req3 = RegistrationRequest(agent_card=card, public_key=kp.public_key_b64,
                                   challenge_signature=sig2)
        result3 = reg_service.register(req3)
        assert result3["ok"] is False
        assert "challenge verification failed" in result3["reason"]

    def test_challenge_consumed_on_card_validation_failure(self, reg_service):
        """If card validation fails, the challenge is still consumed."""
        from a2a_orchestrator.registration import RegistrationRequest
        from a2a_orchestrator.signing import generate_keypair, sign_message

        agent_id = "agent-badcard-test"
        kp = generate_keypair(agent_id)
        # Invalid card — missing required fields.
        bad_card = {"id": agent_id, "name": "Bad"}
        nonce = reg_service.create_challenge(agent_id)
        sig = sign_message({"nonce": nonce, "agent_id": agent_id}, kp.private_key)
        req = RegistrationRequest(agent_card=bad_card, public_key=kp.public_key_b64,
                                  challenge_signature=sig)
        result = reg_service.register(req)
        assert result["ok"] is False
        assert "validation failed" in result["reason"]

        # Replay — challenge must be gone.
        req2 = RegistrationRequest(agent_card=bad_card, public_key=kp.public_key_b64,
                                   challenge_signature=sig)
        result2 = reg_service.register(req2)
        assert result2["ok"] is False
        assert "challenge verification failed" in result2["reason"]


# --------------------------------------------------------------------------- #
# L1: Security headers on web server
# --------------------------------------------------------------------------- #

class TestL1SecurityHeaders:
    """Web server responses must include security headers."""

    def test_security_headers_present(self, env_isolated, tmp_path, monkeypatch):
        monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "l1.jsonl"))
        for mod in list(sys.modules):
            if mod.startswith("a2a_orchestrator"):
                monkeypatch.delitem(sys.modules, mod, raising=False)
        import a2a_orchestrator.config as config_mod
        importlib.reload(config_mod)
        import a2a_orchestrator.server as srv
        importlib.reload(srv)
        srv.registry.load()
        srv.session_store.clear()
        srv.message_store = srv.MessageStore(path=tmp_path / "l1.jsonl")
        srv._default_ctx.message_store = srv.message_store
        from a2a_orchestrator.web_server import create_app
        from fastapi.testclient import TestClient
        app = create_app(server_module=srv)
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


# --------------------------------------------------------------------------- #
# L2: JSONL fallback log rotation / size limits
# --------------------------------------------------------------------------- #

class TestL2LogRotation:
    """JSONL fallback file must rotate when it exceeds the size limit."""

    def test_rotation_when_file_exceeds_max_bytes(self, tmp_path):
        from a2a_orchestrator.persistence import MessageStore
        path = tmp_path / "l2_rotate.jsonl"
        # Very small limit so rotation triggers quickly.
        store = MessageStore(path=path, max_bytes=512)
        # Write enough messages to exceed 512 bytes.
        for i in range(50):
            store.append({"message_id": f"msg-l2rot{i:04d}", "data": "x" * 50})
        # The original file should have been rotated to .1.
        rotated = path.with_suffix(path.suffix + ".1")
        assert rotated.exists(), "Rotated file should exist"
        # The current file should exist and be smaller than the limit
        # (or empty if rotation just happened).
        assert path.exists()

    def test_rotation_disabled_when_max_bytes_zero(self, tmp_path):
        from a2a_orchestrator.persistence import MessageStore
        path = tmp_path / "l2_norotate.jsonl"
        store = MessageStore(path=path, max_bytes=0)
        for i in range(50):
            store.append({"message_id": f"msg-l2nor{i:04d}", "data": "x" * 50})
        rotated = path.with_suffix(path.suffix + ".1")
        assert not rotated.exists(), "Rotation should be disabled when max_bytes=0"

    def test_default_max_bytes_is_positive(self):
        from a2a_orchestrator.persistence import DEFAULT_MAX_JSONL_BYTES
        assert DEFAULT_MAX_JSONL_BYTES > 0


# --------------------------------------------------------------------------- #
# L3: Rate limiting on registration challenges
# --------------------------------------------------------------------------- #

class TestL3ChallengeRateLimit:
    """create_challenge must rate-limit rapid calls from the same agent."""

    def test_first_two_challenges_allowed(self, reg_service):
        """The first two challenges for an agent are allowed (overwrite)."""
        n1 = reg_service.create_challenge("agent-rl-test")
        n2 = reg_service.create_challenge("agent-rl-test")
        assert n1 != n2

    def test_third_rapid_challenge_rejected(self, reg_service):
        """A third challenge within the rate-limit window is rejected."""
        reg_service.create_challenge("agent-rl-flood")
        reg_service.create_challenge("agent-rl-flood")
        with pytest.raises(RuntimeError, match="Rate limit"):
            reg_service.create_challenge("agent-rl-flood")

    def test_rate_limit_constants_exist(self):
        from a2a_orchestrator.registration import (
            CHALLENGE_RATE_LIMIT_SECONDS,
            MAX_CHALLENGES_PER_AGENT,
        )
        assert CHALLENGE_RATE_LIMIT_SECONDS > 0
        assert MAX_CHALLENGES_PER_AGENT >= 1
