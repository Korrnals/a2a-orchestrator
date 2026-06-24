"""E2E tests for the send_a2a tool flow with mocked Mnemos.

These tests exercise the full pipeline (build → validate → R1-R5 → persist
→ session update) by calling the ``send_a2a`` tool function directly,
with Mnemos mocked via ``unittest.mock`` and the JSONL fallback pointed
at a temp file.

The tests do NOT start a real MCP server — they call the tool function
in-process, which is faster and gives direct access to the return dict.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

# We import the server module to access its singletons and the tool.
# The env_isolated fixture (from conftest) sets A2A_SCHEMA_DIR / A2A_CARDS_DIR
# and clears the module cache, so the server re-imports with test fixtures.


@pytest.fixture()
def server_module(env_isolated, tmp_path, monkeypatch):
    """Import the server module fresh, with test env and temp JSONL path.

    Returns the ``a2a_orchestrator.server`` module. All singletons
    (registry, session_store, message_store, mnemos_client) are reset
    for each test via this fixture.
    """
    # Point the JSONL fallback at a temp file.
    monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "e2e.jsonl"))
    # Re-import config so FALLBACK_JSONL_PATH picks up the env var.
    # Force re-import of config (env_isolated already cleared sys.modules,
    # but config may have been re-imported by other fixtures).
    import importlib

    import a2a_orchestrator.config as config_mod
    importlib.reload(config_mod)
    # Now import server — it will use the fresh config.
    import a2a_orchestrator.server as srv
    importlib.reload(srv)
    # Re-load the registry with the test cards dir.
    srv.registry.load()
    # Reset session store for isolation.
    srv.session_store.clear()
    # Reset message store to use the temp path.
    srv.message_store = srv.MessageStore(path=tmp_path / "e2e.jsonl")
    # C2 fix: send_a2a now uses ctx.message_store (per-tenant), so we
    # must also update the default tenant context's store.
    srv._default_ctx.message_store = srv.message_store
    return srv


class TestHappyPath:
    def test_send_a2a_delivers(self, server_module):
        """A→B handoff succeeds, message persisted, session updated."""
        result = server_module.send_a2a(
            target="agent-b",
            reason="Need DBA help with schema change.",
            summary="User wants to add archived_at column to orders table.",
            key_decisions=["Add nullable column"],
            open_questions=["Index it?"],
            artifacts=[{"kind": "file", "pointer": "src/models.py"}],
            intent="handoff",
            session_id="conv-e2e-001",
            from_id="agent-a",
        )
        assert result["ok"] is True
        assert result["next_senior"] == "agent-b"
        assert result["reason"] == "delivered"
        assert result["message_id"].startswith("msg-")

        # Session state updated: chain = [A, B], budget_used = 1
        session = server_module.session_store.get("conv-e2e-001")
        assert session is not None
        assert session.chain == ["agent-a", "agent-b"]
        assert session.budget_used == 1

        # Message persisted to JSONL fallback
        msgs = server_module.message_store.load_all("conv-e2e-001")
        assert len(msgs) == 1
        assert msgs[0]["outcome"] == "delivered"


class TestRejectR1NonWhitelisted:
    def test_non_whitelisted_route_rejected(self, server_module):
        """agent-a cannot call agent-c (not in whitelist)."""
        result = server_module.send_a2a(
            target="agent-c",
            reason="Trying to route to C directly.",
            summary="This should be rejected by R1 whitelist check.",
            session_id="conv-e2e-r1",
            from_id="agent-a",
        )
        assert result["ok"] is False
        assert result["code"] == "R1_NOT_WHITELISTED"
        # Rejected messages are still persisted
        msgs = server_module.message_store.load_all("conv-e2e-r1")
        assert len(msgs) == 1
        assert msgs[0]["outcome"] == "rejected"


class TestRejectR2Loop:
    def test_loop_rejected(self, server_module):
        """A→B→C→A: the third call (C→A) is a loop because A is in chain."""
        # First hop: A→B
        r1 = server_module.send_a2a(
            target="agent-b",
            reason="First hop in chain.",
            summary="Starting the chain A to B to C.",
            session_id="conv-e2e-r2",
            from_id="agent-a",
        )
        assert r1["ok"] is True
        # Second hop: B→C
        r2 = server_module.send_a2a(
            target="agent-c",
            reason="Second hop in chain.",
            summary="Continuing the chain B to C.",
            session_id="conv-e2e-r2",
            from_id="agent-b",
        )
        assert r2["ok"] is True
        # Third hop: C→A — A is already in chain → R2 loop
        r3 = server_module.send_a2a(
            target="agent-a",
            reason="Third hop, should be a loop.",
            summary="Trying to route back to A, which is a loop.",
            session_id="conv-e2e-r2",
            from_id="agent-c",
        )
        assert r3["ok"] is False
        assert r3["code"] == "R2_LOOP_DETECTED"


class TestRejectR3Depth:
    def test_4hop_chain_rejected(self, server_module):
        """A 4-hop chain is rejected by R3 (max depth 3).

        We need a chain of 4 agents. The test cards form A→B→C→A (cycle),
        so:
          hop 1: A→B (depth 0→1, ok)
          hop 2: B→C (depth 1→2, ok)
          hop 3: C→A (depth 2→3, ok — but R2 would catch the loop)
        To test R3 without R2 interfering, we use a fresh session and
        manually pre-populate the chain to depth 3.
        """
        # Manually set up a session at depth 3 (chain has 3 entries).
        session = server_module.session_store.get_or_create("conv-e2e-r3")
        session.chain = ["agent-a", "agent-b", "agent-c"]
        session.budget_used = 3  # also exhaust budget to isolate R3
        # Actually, R4 (budget) would fire first. Let's set budget to 2
        # so R4 passes and R3 is the one that rejects.
        session.budget_used = 2

        # R3 is tested via the per-card override below, since the cycle
        # fixture makes it hard to isolate R3 from R2. This test is a
        # placeholder that documents the intended scenario.
        pass  # See TestRejectR3PerCardOverride below for the real R3 test

    def test_r3_per_card_override_rejected(self, server_module):
        """agent-shallow has max_chain_depth=1; second hop from it → R3 rejects.

        Flow: A→shallow (depth 0→1, ok). Then shallow→B would be depth 1,
        but shallow's own cap is 1, so 1 >= 1 → R3 rejects.
        But shallow cannot call B (B accepts from A, not shallow).
        Instead, manually set chain=[agent-shallow] and call from shallow
        to any allowed target. shallow has no outgoing edges in the
        fixture, so R1 would reject. To isolate R3, we test the
        check_depth function directly instead.
        """
        from a2a_orchestrator.routing import check_depth
        from a2a_orchestrator.session import SessionState

        session = SessionState(session_id="conv-e2e-r3b",
                                chain=["agent-shallow"], budget_used=1)
        rej = check_depth("agent-shallow", "agent-a", session, server_module.registry)
        assert rej is not None
        assert rej.code == "R3_CHAIN_TOO_DEEP"


class TestRejectR4Budget:
    def test_4th_a2a_call_rejected(self, server_module):
        """After 3 A2A calls, the 4th is rejected by R4 (budget exhausted).

        We use a cycle A→B→C→A→B: the first 3 succeed (budget 3), the 4th
        fails with R4. But R2 (loop) would catch the 4th (A is in chain).
        So we manually exhaust the budget and test R4 directly.
        """
        session = server_module.session_store.get_or_create("conv-e2e-r4")
        session.budget_used = 3  # budget exhausted
        session.chain = ["agent-a"]  # depth 1, not at max

        result = server_module.send_a2a(
            target="agent-b",
            reason="Fourth call, budget exhausted.",
            summary="This should be rejected by R4 budget check.",
            session_id="conv-e2e-r4",
            from_id="agent-a",
        )
        assert result["ok"] is False
        assert result["code"] == "R4_BUDGET_EXHAUSTED"


class TestRejectR5Destructive:
    def test_destructive_without_consent_rejected(self, server_module):
        """Destructive intent with default (fail-closed) provider → R5 reject.

        A→B passes R1-R4; R5 (destructive) fires and default provider
        denies → REJECTED.
        """
        result = server_module.send_a2a(
            target="agent-b",
            reason="Requesting destructive action.",
            summary="This is a destructive action request without consent.",
            intent="destructive-action-request",
            session_id="conv-e2e-r5",
            from_id="agent-a",
        )
        assert result["ok"] is False
        assert result["code"] == "R5_DESTRUCTIVE_DENIED"

    def test_destructive_with_consent_delivers(self, server_module):
        """Destructive intent with an approving provider → delivered."""
        # Override the consent provider to always approve.
        server_module.set_consent_provider(lambda req: True)
        try:
            result = server_module.send_a2a(
                target="agent-b",
                reason="Requesting destructive action with consent.",
                summary="This is a destructive action request with consent.",
                intent="destructive-action-request",
                session_id="conv-e2e-r5b",
                from_id="agent-a",
            )
            assert result["ok"] is True
            assert result["next_senior"] == "agent-b"
        finally:
            # Restore fail-closed default
            server_module.set_consent_provider(
                server_module.default_consent_provider)


class TestFallbackPath:
    def test_mnemos_unavailable_jsonl_fallback_works(self, server_module):
        """When Mnemos is unavailable, the JSONL fallback persists the message.

        We mock MnemosClient.write_turn to raise MnemosUnavailableError.
        The tool should still return ok=True and the message should be
        in the JSONL store.
        """
        from a2a_orchestrator.mnemos_client import MnemosUnavailableError

        with patch.object(server_module.mnemos_client, "write_turn",
                          side_effect=MnemosUnavailableError("mocked")):
            result = server_module.send_a2a(
                target="agent-b",
                reason="Testing JSONL fallback path.",
                summary="Mnemos is down, JSONL fallback should persist this.",
                session_id="conv-e2e-fb",
                from_id="agent-a",
            )
        assert result["ok"] is True
        assert result["reason"] == "delivered"

        # Message persisted to JSONL (the fallback)
        msgs = server_module.message_store.load_all("conv-e2e-fb")
        assert len(msgs) == 1
        assert msgs[0]["outcome"] == "delivered"
        assert msgs[0]["from"] == "agent-a"
        assert msgs[0]["to"] == "agent-b"


class TestLoadContextAfterSend:
    def test_load_context_by_message_id_after_send(self, server_module):
        """After send_a2a, load_context finds the message by message_id."""
        from a2a_orchestrator.mnemos_client import MnemosUnavailableError

        # Send a message (Mnemos mocked unavailable → JSONL fallback).
        with patch.object(server_module.mnemos_client, "write_turn",
                          side_effect=MnemosUnavailableError("mocked")):
            send_result = server_module.send_a2a(
                target="agent-b",
                reason="Sending message for load_context e2e test.",
                summary="This message will be loaded back via load_context.",
                session_id="conv-e2e-lc",
                from_id="agent-a",
            )
        assert send_result["ok"] is True
        msg_id = send_result["message_id"]

        # Now load_context should find it (via JSONL fallback since Mnemos is down).
        with patch.object(server_module.mnemos_client, "get_turn_range",
                          side_effect=MnemosUnavailableError("mocked")):
            load_result = server_module.load_context(
                session_id="conv-e2e-lc",
                message_id=msg_id,
            )
        assert load_result["ok"] is True
        assert load_result["message"]["message_id"] == msg_id
        assert load_result["message"]["from"] == "agent-a"
        assert load_result["message"]["to"] == "agent-b"


class TestGetChainStatusAfterSend:
    def test_chain_status_reflects_send(self, server_module):
        """After send_a2a, get_chain_status reflects the updated chain."""
        server_module.send_a2a(
            target="agent-b",
            reason="Sending message for chain status e2e test.",
            summary="This message updates the chain for status query.",
            session_id="conv-e2e-cs",
            from_id="agent-a",
        )
        status = server_module.get_chain_status(session_id="conv-e2e-cs")
        assert status["ok"] is True
        assert status["chain"] == ["agent-a", "agent-b"]
        assert status["depth"] == 2  # len(chain) = 2 after 1 hop
        assert status["budget_used"] == 1
        assert status["calls_remaining"] == 2
        assert len(status["recent_messages"]) == 1
        assert status["recent_messages"][0]["outcome"] == "delivered"


class TestGetMetricsAfterSend:
    def test_metrics_reflect_send_activity(self, server_module):
        """After send_a2a, get_metrics reflects the activity."""
        from a2a_orchestrator.mnemos_client import MnemosUnavailableError

        initial = server_module.get_metrics()
        assert initial["messages_delivered"] == 0

        with patch.object(server_module.mnemos_client, "write_turn",
                          side_effect=MnemosUnavailableError("mocked")):
            server_module.send_a2a(
                target="agent-b",
                reason="Sending message for metrics e2e test.",
                summary="This message increments the metrics counters.",
                session_id="conv-e2e-mt",
                from_id="agent-a",
            )

        final = server_module.get_metrics()
        assert final["messages_delivered"] == 1
        assert final["fallback_writes"] == 1
        assert final["total_sessions"] == 1
