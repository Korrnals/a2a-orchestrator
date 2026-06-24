"""Tests for code review fixes (C1, C2, H1, H2, L5, M1-M3, loop detection).

Each test maps to a specific finding from the code review:

* **C1** — saga budget double-counting: 6 calls in a saga all pass.
* **C2** — message store tenant isolation: tenant B cannot load_context
  or search_messages from tenant A.
* **H1** — WebSocket binds to 127.0.0.1 by default; auth token check.
* **H2** — verify_message lets TypeError/KeyError propagate (only
  InvalidSignature and ValueError are caught).
* **L5** — canonical_json with non-ASCII content produces stable
  signatures.
* **Loop detection** — smoke test scenario: R2 fires with valid reason.
* **M1** — _registration_services cache race (thread safety).
* **M2** — check_depth enforces target's max_chain_depth.
* **M3** — all rejection codes present in metrics initial dict.
"""
from __future__ import annotations

import json
import threading
from unittest.mock import patch

import pytest

# --------------------------------------------------------------------------- #
# C1: Saga budget double-counting — 6 calls in a saga all pass
# --------------------------------------------------------------------------- #

class TestC1SagaBudgetNoDoubleCounting:
    """Verify that each A2A call in a saga consumes exactly 1 budget."""

    @pytest.fixture()
    def server_module(self, env_isolated, tmp_path, monkeypatch):
        """Import the server module fresh with test env."""
        monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "c1.jsonl"))
        import importlib

        import a2a_orchestrator.config as config_mod
        importlib.reload(config_mod)
        import a2a_orchestrator.server as srv
        importlib.reload(srv)
        srv.registry.load()
        srv.session_store.clear()
        srv.message_store = srv.MessageStore(path=tmp_path / "c1.jsonl")
        srv._default_ctx.message_store = srv.message_store
        srv.metrics.reset()
        return srv

    def test_saga_six_calls_all_pass(self, server_module):
        """C1: with SAGA_MAX_BUDGET=6, all 6 calls should pass (not just 3).

        Before the fix, record_call incremented budget by 1 and add_chain
        incremented it again → 2 budget per call → only 3 calls possible.
        After the fix, add_chain does not increment budget, so 6 calls
        fit within the budget of 6.
        """
        from a2a_orchestrator.saga import SAGA_MAX_BUDGET

        assert SAGA_MAX_BUDGET == 6, "SAGA_MAX_BUDGET should be 6 (MAX_BUDGET*2)"

        srv = server_module
        # Create a saga.
        saga = srv.saga_store.create_saga(root_session_id="conv-c1")
        saga_id = saga.saga_id

        # We need 6 successful A2A calls within the saga. Each call needs
        # a fresh session (to avoid per-session R2 loop / R3 depth / R4
        # budget limits), but the same saga_id.
        # Chain: A→B, B→C, C→A (fresh session), A→B (fresh), B→C (fresh), C→A (fresh)
        routes = [
            ("agent-a", "agent-b", "conv-c1-s1"),
            ("agent-b", "agent-c", "conv-c1-s2"),
            # C→A: agent-a accepts from agent-c (per conftest cards).
            ("agent-c", "agent-a", "conv-c1-s3"),
            ("agent-a", "agent-b", "conv-c1-s4"),
            ("agent-b", "agent-c", "conv-c1-s5"),
            ("agent-c", "agent-a", "conv-c1-s6"),
        ]

        for i, (from_id, target, sid) in enumerate(routes):
            result = srv.send_a2a(
                target=target,
                reason=f"Saga call {i+1} of 6 for budget test.",
                summary=f"Sending A2A message {i+1} within saga for C1 test.",
                session_id=sid,
                from_id=from_id,
                saga_id=saga_id,
            )
            assert result["ok"] is True, (
                f"Call {i+1} ({from_id}→{target}) should pass but got: {result}"
            )

        # Verify saga budget_used is exactly 6 (not 12).
        saga = srv.saga_store.get_saga(saga_id)
        assert saga is not None
        assert saga.budget_used == 6, (
            f"Saga budget_used should be 6 (one per call), got {saga.budget_used}"
        )
        assert saga.calls_remaining() == 0

    def test_saga_seventh_call_rejected(self, server_module):
        """C1: the 7th call in a saga with budget=6 is rejected."""
        srv = server_module
        saga = srv.saga_store.create_saga(root_session_id="conv-c1b")
        saga_id = saga.saga_id

        routes = [
            ("agent-a", "agent-b", "conv-c1b-s1"),
            ("agent-b", "agent-c", "conv-c1b-s2"),
            ("agent-c", "agent-a", "conv-c1b-s3"),
            ("agent-a", "agent-b", "conv-c1b-s4"),
            ("agent-b", "agent-c", "conv-c1b-s5"),
            ("agent-c", "agent-a", "conv-c1b-s6"),
        ]
        for from_id, target, sid in routes:
            result = srv.send_a2a(
                target=target,
                reason="Saga call for budget exhaustion test.",
                summary="Sending A2A message within saga to exhaust budget.",
                session_id=sid,
                from_id=from_id,
                saga_id=saga_id,
            )
            assert result["ok"] is True

        # 7th call should be rejected with SAGA_BUDGET_EXHAUSTED.
        result = srv.send_a2a(
            target="agent-b",
            reason="Seventh saga call should be rejected.",
            summary="This call exceeds the saga budget of 6.",
            session_id="conv-c1b-s7",
            from_id="agent-a",
            saga_id=saga_id,
        )
        assert result["ok"] is False
        assert result["code"] == "SAGA_BUDGET_EXHAUSTED"


# --------------------------------------------------------------------------- #
# C2: Message store tenant isolation
# --------------------------------------------------------------------------- #

class TestC2TenantIsolation:
    """Verify that tenant B cannot load_context or search_messages from tenant A."""

    @pytest.fixture()
    def server_module(self, env_isolated, tmp_path, monkeypatch):
        """Import the server module fresh with test env."""
        monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "c2.jsonl"))
        import importlib

        import a2a_orchestrator.config as config_mod
        importlib.reload(config_mod)
        import a2a_orchestrator.server as srv
        importlib.reload(srv)
        srv.registry.load()
        srv.session_store.clear()
        # Reset default tenant's message store.
        from a2a_orchestrator.persistence import MessageStore
        store = MessageStore(path=tmp_path / "c2.jsonl")
        srv.message_store = store
        srv._default_ctx.message_store = store
        srv.metrics.reset()
        return srv

    def test_tenant_b_cannot_load_context_from_tenant_a(self, server_module):
        """C2: a message sent in tenant A is not visible via load_context in tenant B."""
        srv = server_module

        # Tenant A sends a message.
        result_a = srv.send_a2a(
            target="agent-b",
            reason="Tenant A secret message for isolation test.",
            summary="This message should only be visible to tenant A.",
            session_id="conv-c2-tenant-a",
            from_id="agent-a",
            tenant_id="default",
        )
        assert result_a["ok"] is True
        msg_id = result_a["message_id"]

        # Tenant B tries to load_context for that message_id.
        result_b = srv.load_context(
            session_id="conv-c2-tenant-a",
            message_id=msg_id,
            tenant_id="tenant-b",
        )
        assert result_b["ok"] is False, (
            "Tenant B should NOT be able to load tenant A's message"
        )
        assert result_b["message"] is None

    def test_tenant_b_cannot_search_messages_from_tenant_a(self, server_module):
        """C2: search_messages in tenant B does not return tenant A's messages."""
        srv = server_module

        # Tenant A sends a message with a unique keyword.
        srv.send_a2a(
            target="agent-b",
            reason="Tenant A unique keyword ZQX for search isolation.",
            summary="This message contains unique keyword ZQX for tenant A.",
            session_id="conv-c2-search-a",
            from_id="agent-a",
            tenant_id="default",
        )

        # Tenant B searches for that keyword.
        result_b = srv.search_messages(
            query="ZQX",
            tenant_id="tenant-b",
        )
        assert result_b["ok"] is True
        assert result_b["count"] == 0, (
            "Tenant B search should NOT find tenant A's messages"
        )

    def test_tenant_a_can_load_own_message(self, server_module):
        """C2: tenant A can still load its own messages (sanity check)."""
        srv = server_module

        result_a = srv.send_a2a(
            target="agent-b",
            reason="Tenant A message for self-load test.",
            summary="This message should be loadable by tenant A itself.",
            session_id="conv-c2-self",
            from_id="agent-a",
            tenant_id="default",
        )
        assert result_a["ok"] is True
        msg_id = result_a["message_id"]

        result = srv.load_context(
            session_id="conv-c2-self",
            message_id=msg_id,
            tenant_id="default",
        )
        assert result["ok"] is True
        assert result["message"] is not None


# --------------------------------------------------------------------------- #
# H1: WebSocket binds to 127.0.0.1 by default + auth token
# --------------------------------------------------------------------------- #

class TestH1WebSocketBindAddress:
    """Verify that the WS server defaults to 127.0.0.1 and supports auth."""

    def test_default_bind_host_is_localhost(self):
        """H1: WebSocketServer defaults to 127.0.0.1, not 0.0.0.0."""
        from a2a_orchestrator.ws_server import WebSocketServer
        server = WebSocketServer(port=19999)
        assert server.bind_host == "127.0.0.1"

    def test_custom_bind_host(self):
        """H1: bind_host can be overridden."""
        from a2a_orchestrator.ws_server import WebSocketServer
        server = WebSocketServer(port=19998, bind_host="0.0.0.0")
        assert server.bind_host == "0.0.0.0"

    @pytest.mark.asyncio
    async def test_auth_token_rejects_wrong_token(self):
        """H1: when auth_token is set, a wrong token is rejected."""

        import websockets
        from a2a_orchestrator.ws_server import WebSocketServer

        server = WebSocketServer(port=19997, auth_token="secret-token")
        await server.start_async()
        try:
            async with websockets.connect("ws://127.0.0.1:19997") as ws:
                await ws.send(json.dumps({
                    "action": "subscribe",
                    "session_id": "s1",
                    "auth_token": "wrong-token",
                }))
                resp = await ws.recv()
                parsed = json.loads(resp)
                assert parsed["ok"] is False
                assert "auth_token" in parsed["reason"]
        finally:
            server.stop()

    @pytest.mark.asyncio
    async def test_auth_token_accepts_correct_token(self):
        """H1: when auth_token is set, the correct token is accepted."""

        import websockets
        from a2a_orchestrator.ws_server import WebSocketServer

        server = WebSocketServer(port=19996, auth_token="secret-token")
        await server.start_async()
        try:
            async with websockets.connect("ws://127.0.0.1:19996") as ws:
                await ws.send(json.dumps({
                    "action": "subscribe",
                    "session_id": "s1",
                    "auth_token": "secret-token",
                }))
                resp = await ws.recv()
                parsed = json.loads(resp)
                assert parsed["ok"] is True
        finally:
            server.stop()

    @pytest.mark.asyncio
    async def test_no_auth_token_by_default(self):
        """H1: without auth_token configured, subscribe works without token."""

        import websockets
        from a2a_orchestrator.ws_server import WebSocketServer

        server = WebSocketServer(port=19995)
        await server.start_async()
        try:
            async with websockets.connect("ws://127.0.0.1:19995") as ws:
                await ws.send(json.dumps({
                    "action": "subscribe",
                    "session_id": "s1",
                }))
                resp = await ws.recv()
                parsed = json.loads(resp)
                assert parsed["ok"] is True
        finally:
            server.stop()


# --------------------------------------------------------------------------- #
# H2: verify_message exception propagation
# --------------------------------------------------------------------------- #

class TestH2VerifyMessageExceptionPropagation:
    """Verify that verify_message only catches InvalidSignature and ValueError."""

    def test_type_error_propagates(self):
        """H2: passing a non-dict message raises AttributeError, not returns False.

        Before the fix, ``except Exception`` swallowed this. Now only
        ``InvalidSignature`` and ``ValueError`` are caught, so the
        ``AttributeError`` from ``str.items()`` propagates.
        """
        from a2a_orchestrator.signing import generate_keypair, verify_message

        kp = generate_keypair("agent-test")
        # Passing a string instead of a dict → AttributeError should propagate.
        with pytest.raises(AttributeError):
            verify_message("not-a-dict", "fake-sig", kp.public_key)  # type: ignore[arg-type]

    def test_key_error_propagates(self):
        """H2: a non-string signature raises AttributeError, not returns False.

        Before the fix, ``except Exception`` swallowed this. Now the
        ``AttributeError`` from ``int.encode()`` propagates.
        """
        from a2a_orchestrator.signing import generate_keypair, verify_message

        kp = generate_keypair("agent-test")
        msg = {"from": "agent-a", "reason": "test message here"}
        # Passing a non-string signature (int) → AttributeError in _b64decode.
        with pytest.raises(AttributeError):
            verify_message(msg, 12345, kp.public_key)  # type: ignore[arg-type]

    def test_invalid_signature_returns_false(self):
        """H2: a genuinely invalid signature returns False (not raises)."""
        from a2a_orchestrator.signing import generate_keypair, sign_message, verify_message

        kp1 = generate_keypair("agent-a")
        kp2 = generate_keypair("agent-b")
        msg = {"from": "agent-a", "reason": "test message here"}
        sig = sign_message(msg, kp1.private_key)
        # Verify with wrong key → InvalidSignature → returns False.
        assert verify_message(msg, sig, kp2.public_key) is False

    def test_bad_base64_returns_false(self):
        """H2: a non-base64 signature string raises ValueError → returns False."""
        from a2a_orchestrator.signing import generate_keypair, verify_message

        kp = generate_keypair("agent-test")
        msg = {"from": "agent-a", "reason": "test message here"}
        # "not-base64!" is invalid base64 → ValueError in _b64decode → False.
        assert verify_message(msg, "not-base64!!!", kp.public_key) is False


# --------------------------------------------------------------------------- #
# L5: canonical_json with non-ASCII content
# --------------------------------------------------------------------------- #

class TestL5CanonicalJsonNonAscii:
    """Verify that non-ASCII content produces stable signatures across platforms."""

    def test_cyrillic_content_stable_signature(self):
        """L5: a message with Cyrillic text signs and verifies correctly."""
        from a2a_orchestrator.signing import generate_keypair, sign_message, verify_message

        kp = generate_keypair("agent-test")
        # Intentionally non-ASCII (Cyrillic) to test ensure_ascii=False.
        msg = {
            "from": "agent-a",
            "to": "agent-b",
            "reason": "Передача данных между агентами",
            "payload": {"summary": "Тестовое сообщение с кириллицей"},  # noqa: RUF001
        }
        sig = sign_message(msg, kp.private_key)
        assert verify_message(msg, sig, kp.public_key) is True

    def test_emoji_content_stable_signature(self):
        """L5: a message with emoji signs and verifies correctly."""
        from a2a_orchestrator.signing import generate_keypair, sign_message, verify_message

        kp = generate_keypair("agent-test")
        msg = {
            "from": "agent-a",
            "to": "agent-b",
            "reason": "Message with emoji 🎉 and CJK 中文",
        }
        sig = sign_message(msg, kp.private_key)
        assert verify_message(msg, sig, kp.public_key) is True

    def test_non_ascii_not_escaped(self):
        """L5: canonical_json preserves non-ASCII as UTF-8, not \\uXXXX."""
        from a2a_orchestrator.signing import canonical_json

        result = canonical_json({"msg": "héllo"})
        # ensure_ascii=False means the character is raw UTF-8, not escaped.
        assert "héllo" in result
        assert "\\u" not in result


# --------------------------------------------------------------------------- #
# Loop detection — exact smoke test scenario (CRITICAL BUG fix)
# --------------------------------------------------------------------------- #

class TestLoopDetectionSmokeScenario:
    """Reproduce the smoke test that failed due to a too-short reason.

    The original smoke test used ``reason='Loop test'`` (9 chars), which
    failed schema validation (minLength=10) before R2 could fire. With a
    valid reason (≥10 chars), R2 correctly detects the loop.

    The code is correct: schema validation must precede routing checks.
    The smoke test itself had a bug (too-short reason). These tests
    document the correct behaviour.
    """

    @pytest.fixture()
    def server_module(self, env_isolated, tmp_path, monkeypatch):
        monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "loop.jsonl"))
        import importlib

        import a2a_orchestrator.config as config_mod
        importlib.reload(config_mod)
        import a2a_orchestrator.server as srv
        importlib.reload(srv)
        srv.registry.load()
        srv.session_store.clear()
        srv.message_store = srv.MessageStore(path=tmp_path / "loop.jsonl")
        srv._default_ctx.message_store = srv.message_store
        srv.metrics.reset()
        return srv

    def test_loop_detected_with_valid_reason(self, server_module):
        """A→B→C→A: the third hop (C→A) is a loop because A is in chain.

        The test fixture cards form a cycle: A accepts from C, B accepts
        from A, C accepts from B. So A→B→C→A is the valid route, and the
        third hop (C→A) triggers R2 because A is already upstream.
        """
        sid = "smoke-loop-001"

        # 1. A→B: should deliver
        r1 = server_module.send_a2a(
            target="agent-b",
            reason="Testing loop detection first hop.",
            summary="Testing A2A routing for loop detection smoke test.",
            from_id="agent-a",
            session_id=sid,
            intent="handoff",
        )
        assert r1["ok"] is True
        assert r1["next_senior"] == "agent-b"

        # 2. B→C: should deliver
        r2 = server_module.send_a2a(
            target="agent-c",
            reason="Testing loop detection second hop.",
            summary="Continuing the chain B to C for loop test.",
            from_id="agent-b",
            session_id=sid,
            intent="handoff",
        )
        assert r2["ok"] is True

        # 3. C→A (same chain): should be R2_LOOP_DETECTED (A is upstream)
        r3 = server_module.send_a2a(
            target="agent-a",
            reason="Loop test with valid reason.",
            summary="Should be rejected by R2 loop detection now.",
            from_id="agent-c",
            session_id=sid,
            intent="handoff",
        )
        assert r3["ok"] is False
        assert r3["code"] == "R2_LOOP_DETECTED"

    def test_short_reason_fails_schema_not_r2(self, server_module):
        """A reason < 10 chars fails schema validation, not R2.

        This documents the original smoke test bug: the reason 'Loop test'
        (9 chars) is too short for the schema (minLength=10), so the
        message is rejected as SCHEMA_INVALID before R2 runs. This is
        correct behaviour — schema validation must precede routing checks.

        We use the A→B→C→A cycle: after two hops, C→A with a short reason
        should fail schema validation, not R2.
        """
        sid = "smoke-schema-001"

        # First two hops succeed
        r1 = server_module.send_a2a(
            target="agent-b",
            reason="First hop for schema test.",
            summary="Setting up chain for schema validation test.",
            from_id="agent-a",
            session_id=sid,
        )
        assert r1["ok"] is True

        r2 = server_module.send_a2a(
            target="agent-c",
            reason="Second hop for schema test.",
            summary="Continuing chain to set up loop scenario.",
            from_id="agent-b",
            session_id=sid,
        )
        assert r2["ok"] is True

        # Third hop C→A with short reason → SCHEMA_INVALID, not R2
        r3 = server_module.send_a2a(
            target="agent-a",
            reason="Loop test",  # 9 chars < 10 minLength
            summary="Should be rejected by schema validation.",
            from_id="agent-c",
            session_id=sid,
        )
        assert r3["ok"] is False
        assert r3["code"] == "SCHEMA_INVALID"


# --------------------------------------------------------------------------- #
# M1: _registration_services cache race (thread safety)
# --------------------------------------------------------------------------- #

class TestM1RegistrationServiceCacheRace:
    """Verify that concurrent first-access for the same tenant doesn't race."""

    @pytest.fixture()
    def server_module(self, env_isolated, tmp_path, monkeypatch):
        monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "m1.jsonl"))
        import importlib

        import a2a_orchestrator.config as config_mod
        importlib.reload(config_mod)
        import a2a_orchestrator.server as srv
        importlib.reload(srv)
        srv.registry.load()
        srv.session_store.clear()
        srv.message_store = srv.MessageStore(path=tmp_path / "m1.jsonl")
        srv._default_ctx.message_store = srv.message_store
        srv.metrics.reset()
        return srv

    def test_concurrent_access_same_tenant_returns_same_instance(
        self, server_module,
    ):
        """Multiple threads requesting the same tenant get the same service."""
        tenant_id = "tenant-m1-race"
        results: list[object] = []
        results_lock = threading.Lock()
        barrier = threading.Barrier(8)

        def worker() -> None:
            barrier.wait()  # Synchronise start to maximise race window
            svc = server_module._resolve_registration_service(tenant_id)
            with results_lock:
                results.append(svc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 8
        # All threads must get the exact same instance
        first = results[0]
        assert all(r is first for r in results)

    def test_different_tenants_get_different_instances(self, server_module):
        """Different tenants get different RegistrationService instances."""
        svc_a = server_module._resolve_registration_service("tenant-a")
        svc_b = server_module._resolve_registration_service("tenant-b")
        assert svc_a is not svc_b

    def test_default_tenant_returns_module_level_service(self, server_module):
        """Default tenant returns the module-level registration_service."""
        svc = server_module._resolve_registration_service("default")
        assert svc is server_module.registration_service


# --------------------------------------------------------------------------- #
# M2: check_depth enforces target's max_chain_depth
# --------------------------------------------------------------------------- #

class TestM2TargetDepthCap:
    """Verify that check_depth also checks the target's max_chain_depth."""

    @pytest.fixture()
    def registry(self, cards_dir):
        from a2a_orchestrator.registry import AgentCardRegistry

        reg = AgentCardRegistry(cards_dir=cards_dir)
        reg.load()
        return reg

    def test_target_depth_cap_rejects(self, registry):
        """Target with max_chain_depth=1 rejects being at depth 1+.

        agent-shallow has max_chain_depth=1. If we try to route to it
        at depth 1 (chain has 1 entry), the target cap should reject.
        """
        from a2a_orchestrator.routing import R3_CHAIN_TOO_DEEP, check_depth
        from a2a_orchestrator.session import SessionState

        session = SessionState(session_id="s1", chain=["agent-a"])
        assert session.depth() == 1
        rej = check_depth("agent-a", "agent-shallow", session, registry)
        assert rej is not None
        assert rej.code == R3_CHAIN_TOO_DEEP
        assert "agent-shallow" in rej.message
        assert "max_chain_depth=1" in rej.message

    def test_sender_cap_still_works(self, registry):
        """Sender's max_chain_depth is still enforced (regression check)."""
        from a2a_orchestrator.routing import R3_CHAIN_TOO_DEEP, check_depth
        from a2a_orchestrator.session import SessionState

        # agent-shallow as sender at depth 1 → sender cap rejects
        session = SessionState(session_id="s1", chain=["agent-shallow"])
        rej = check_depth("agent-shallow", "agent-a", session, registry)
        assert rej is not None
        assert rej.code == R3_CHAIN_TOO_DEEP

    def test_normal_route_passes_both_caps(self, registry):
        """Neither sender nor target has a restrictive cap → passes."""
        from a2a_orchestrator.routing import check_depth
        from a2a_orchestrator.session import SessionState

        session = SessionState(session_id="s1", chain=["agent-a"])
        rej = check_depth("agent-a", "agent-b", session, registry)
        assert rej is None


# --------------------------------------------------------------------------- #
# M3: all rejection codes in metrics initial dict
# --------------------------------------------------------------------------- #

class TestM3MetricsRejectionCodes:
    """Verify that all rejection codes are present in the initial dict."""

    def test_all_rejection_codes_in_initial_dict(self):
        from a2a_orchestrator.metrics import Metrics

        m = Metrics()
        snapshot = m.snapshot()
        by_rule = snapshot["rejections_by_rule"]

        expected_codes = {
            "R1_NOT_WHITELISTED",
            "R2_LOOP_DETECTED",
            "R3_CHAIN_TOO_DEEP",
            "R4_BUDGET_EXHAUSTED",
            "R5_DESTRUCTIVE_DENIED",
            "R6_SIGNATURE_INVALID",
            "SCHEMA_INVALID",
            "SAGA_NOT_FOUND",
            "SAGA_BUDGET_EXHAUSTED",
        }
        assert expected_codes.issubset(set(by_rule.keys()))
        # All start at zero
        assert all(v == 0 for v in by_rule.values())

    def test_reset_clears_all_rejection_codes(self):
        from a2a_orchestrator.metrics import Metrics

        m = Metrics()
        # Record some rejections
        m.record_rejected("R2_LOOP_DETECTED")
        m.record_rejected("SAGA_NOT_FOUND")
        m.record_rejected("SAGA_BUDGET_EXHAUSTED")
        m.record_rejected("R6_SIGNATURE_INVALID")
        snap = m.snapshot()
        assert snap["rejections_by_rule"]["R2_LOOP_DETECTED"] == 1
        assert snap["rejections_by_rule"]["SAGA_NOT_FOUND"] == 1
        assert snap["rejections_by_rule"]["SAGA_BUDGET_EXHAUSTED"] == 1
        assert snap["rejections_by_rule"]["R6_SIGNATURE_INVALID"] == 1

        # Reset → all back to zero
        m.reset()
        snap = m.snapshot()
        by_rule = snap["rejections_by_rule"]
        assert all(v == 0 for v in by_rule.values())
        # The keys must still be present after reset
        expected_codes = {
            "R1_NOT_WHITELISTED",
            "R2_LOOP_DETECTED",
            "R3_CHAIN_TOO_DEEP",
            "R4_BUDGET_EXHAUSTED",
            "R5_DESTRUCTIVE_DENIED",
            "R6_SIGNATURE_INVALID",
            "SCHEMA_INVALID",
            "SAGA_NOT_FOUND",
            "SAGA_BUDGET_EXHAUSTED",
        }
        assert expected_codes.issubset(set(by_rule.keys()))

    def test_saga_rejection_codes_tracked_in_metrics(
        self, tmp_path, env_isolated, monkeypatch,
    ):
        """SAGA_NOT_FOUND is tracked in metrics after a send_a2a rejection."""
        monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "m3.jsonl"))
        import importlib

        import a2a_orchestrator.config as config_mod
        importlib.reload(config_mod)
        import a2a_orchestrator.server as srv
        importlib.reload(srv)
        srv.registry.load()
        srv.session_store.clear()
        srv.message_store = srv.MessageStore(path=tmp_path / "m3.jsonl")
        srv._default_ctx.message_store = srv.message_store
        srv.metrics.reset()

        # SAGA_NOT_FOUND: send_a2a with a non-existent saga_id
        with patch.object(srv.mnemos_client, "write_turn",
                          return_value={"turn_id": "t1"}):
            result = srv.send_a2a(
                target="agent-b",
                reason="Testing saga not found rejection.",
                summary="This should be rejected because saga does not exist.",
                from_id="agent-a",
                session_id="conv-m3-saga",
                saga_id="nonexistent-saga",
            )
        assert result["ok"] is False
        assert result["code"] == "SAGA_NOT_FOUND"

        snap = srv.metrics.snapshot()
        assert snap["rejections_by_rule"]["SAGA_NOT_FOUND"] == 1
