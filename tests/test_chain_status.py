"""Tests for the get_chain_status MCP tool (a2a_orchestrator.server)."""
from __future__ import annotations

import pytest


@pytest.fixture()
def server_module(env_isolated, tmp_path, monkeypatch):
    """Import the server module fresh, with test env and temp JSONL path."""
    monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "cs.jsonl"))
    import importlib

    import a2a_orchestrator.config as config_mod
    importlib.reload(config_mod)
    import a2a_orchestrator.server as srv
    importlib.reload(srv)
    srv.registry.load()
    srv.session_store.clear()
    srv.message_store = srv.MessageStore(path=tmp_path / "cs.jsonl")
    # C2 fix: send_a2a now uses ctx.message_store (per-tenant), so we
    # must also update the default tenant context's store.
    srv._default_ctx.message_store = srv.message_store
    srv.metrics.reset()
    return srv


class TestGetChainStatus:
    def test_empty_session(self, server_module):
        """Session that doesn't exist → empty state with defaults."""
        result = server_module.get_chain_status(session_id="conv-cs-empty")
        assert result["ok"] is True
        assert result["chain"] == []
        assert result["depth"] == 0
        assert result["budget_used"] == 0
        assert result["calls_remaining"] == 3
        assert result["recent_messages"] == []

    def test_after_one_hop(self, server_module):
        """After 1 successful hop → depth=1, budget_used=1, calls_remaining=2."""
        server_module.send_a2a(
            target="agent-b",
            reason="First hop for chain status test.",
            summary="Sending a message to populate chain status.",
            session_id="conv-cs-001",
            from_id="agent-a",
        )
        result = server_module.get_chain_status(session_id="conv-cs-001")
        assert result["ok"] is True
        assert result["chain"] == ["agent-a", "agent-b"]
        assert result["depth"] == 2  # len(chain) = 2 after 1 hop
        assert result["budget_used"] == 1
        assert result["calls_remaining"] == 2
        assert len(result["recent_messages"]) == 1

    def test_after_three_hops(self, server_module):
        """After 3 hops → calls_remaining=0, budget exhausted."""
        # Hop 1: A→B
        server_module.send_a2a(
            target="agent-b",
            reason="First hop in three-hop chain.",
            summary="Starting a three-hop chain for budget test.",
            session_id="conv-cs-002",
            from_id="agent-a",
        )
        # Hop 2: B→C
        server_module.send_a2a(
            target="agent-c",
            reason="Second hop in three-hop chain.",
            summary="Continuing the chain B to C.",
            session_id="conv-cs-002",
            from_id="agent-b",
        )
        # Hop 3: C→A (R2 would catch this as a loop, so use a fresh session
        # for the third hop to avoid loop detection)
        # Actually, let's just manually set budget to 3 to test the status.
        session = server_module.session_store.get("conv-cs-002")
        session.budget_used = 3
        session.chain = ["agent-a", "agent-b", "agent-c"]

        result = server_module.get_chain_status(session_id="conv-cs-002")
        assert result["ok"] is True
        assert result["budget_used"] == 3
        assert result["calls_remaining"] == 0

    def test_recent_messages_returns_last_5(self, server_module):
        """recent_messages returns at most the last 5 messages."""
        session = server_module.session_store.get_or_create("conv-cs-003")
        # Add 7 messages to the session.
        for i in range(7):
            session.record_message({
                "message_id": f"msg-cs-{i:04d}",
                "outcome": "delivered",
                "session_id": "conv-cs-003",
            })
        result = server_module.get_chain_status(session_id="conv-cs-003")
        assert result["ok"] is True
        assert len(result["recent_messages"]) == 5
        # Should be the last 5 (messages 2-6)
        ids = [m["message_id"] for m in result["recent_messages"]]
        assert ids == [f"msg-cs-{i:04d}" for i in range(2, 7)]

    def test_recent_messages_empty_for_new_session(self, server_module):
        """A session with no messages → recent_messages is empty."""
        server_module.session_store.get_or_create("conv-cs-004")
        result = server_module.get_chain_status(session_id="conv-cs-004")
        assert result["ok"] is True
        assert result["recent_messages"] == []
