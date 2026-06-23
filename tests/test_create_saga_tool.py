"""Tests for the create_saga MCP tool (a2a_orchestrator.server).

Covers:
- Creating a saga via the tool returns a saga_id.
- send_a2a with that saga_id is delivered (not SAGA_NOT_FOUND).
- Multiple chains in the same saga track budget correctly.
- Tenant isolation: a saga in tenant A is not visible in tenant B.
- Metadata parsing: valid JSON → dict; invalid JSON → error; empty → {}.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def server_module(env_isolated, tmp_path, monkeypatch):
    """Import the server module fresh, with test env and temp JSONL path."""
    monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "saga.jsonl"))
    import a2a_orchestrator.config as config_mod
    importlib.reload(config_mod)
    import a2a_orchestrator.server as srv
    importlib.reload(srv)
    srv.registry.load()
    srv.session_store.clear()
    srv.message_store = srv.MessageStore(path=tmp_path / "saga.jsonl")
    # C2 fix: send_a2a uses ctx.message_store (per-tenant).
    srv._default_ctx.message_store = srv.message_store
    srv.metrics.reset()
    # Load the same test cards into tenant-b so R1 passes and we can
    # isolate the saga-level behaviour (otherwise R1_NOT_WHITELISTED
    # fires before the saga check).  We recreate tenant-b's registry
    # pointing at the shared cards dir (the TenantManager would
    # otherwise use a non-existent <cards>/tenant-b subdir).
    from a2a_orchestrator.registry import AgentCardRegistry
    ctx_b = srv.tenant_manager.get_or_create("tenant-b")
    ctx_b.registry = AgentCardRegistry(cards_dir=srv.registry.cards_dir)
    ctx_b.registry.load()
    ctx_b.load_keys()
    return srv


# --------------------------------------------------------------------------- #
# Basic creation
# --------------------------------------------------------------------------- #

class TestCreateSaga:
    def test_create_returns_saga_id(self, server_module):
        result = server_module.create_saga(root_session_id="conv-saga-001")
        assert result["ok"] is True
        assert result["saga_id"].startswith("saga-")
        assert result["reason"] == "created"

    def test_create_with_metadata(self, server_module):
        result = server_module.create_saga(
            root_session_id="conv-saga-002",
            metadata='{"task": "migration", "priority": "high"}',
        )
        assert result["ok"] is True
        saga = server_module.get_saga_status(result["saga_id"])
        assert saga["ok"] is True
        assert saga["saga"]["metadata"] == {"task": "migration",
                                            "priority": "high"}
        assert saga["saga"]["root_session_id"] == "conv-saga-002"

    def test_create_empty_metadata(self, server_module):
        result = server_module.create_saga(
            root_session_id="conv-saga-003",
            metadata="",
        )
        assert result["ok"] is True
        saga = server_module.get_saga_status(result["saga_id"])
        assert saga["saga"]["metadata"] == {}

    def test_create_invalid_json_metadata(self, server_module):
        result = server_module.create_saga(
            root_session_id="conv-saga-004",
            metadata="{not valid json",
        )
        assert result["ok"] is False
        assert result["saga_id"] == ""
        assert "not valid JSON" in result["reason"]

    def test_create_non_object_metadata(self, server_module):
        result = server_module.create_saga(
            root_session_id="conv-saga-005",
            metadata='["a", "b"]',
        )
        assert result["ok"] is False
        assert "JSON object" in result["reason"]


# --------------------------------------------------------------------------- #
# Integration with send_a2a
# --------------------------------------------------------------------------- #

class TestSagaWithSendA2A:
    def test_send_a2a_with_saga_id_delivered(self, server_module):
        """send_a2a with a valid saga_id → delivered (not SAGA_NOT_FOUND)."""
        saga = server_module.create_saga(root_session_id="conv-saga-100")
        assert saga["ok"] is True

        result = server_module.send_a2a(
            target="agent-b",
            reason="First hop in saga chain.",
            summary="Sending a message within a saga for delivery test.",
            session_id="conv-saga-100",
            from_id="agent-a",
            saga_id=saga["saga_id"],
        )
        assert result["ok"] is True
        assert result["reason"] == "delivered"

    def test_send_a2a_without_saga_still_fails(self, server_module):
        """send_a2a with a non-existent saga_id → SAGA_NOT_FOUND."""
        result = server_module.send_a2a(
            target="agent-b",
            reason="Hop with a non-existent saga id.",
            summary="This should be rejected because the saga does not exist.",
            session_id="conv-saga-none",
            from_id="agent-a",
            saga_id="saga-doesnotexist",
        )
        assert result["ok"] is False
        assert result["code"] == "SAGA_NOT_FOUND"

    def test_multiple_chains_budget_tracked(self, server_module):
        """Multiple A2A calls in the same saga share the saga budget."""
        saga = server_module.create_saga(root_session_id="conv-saga-budget")
        sid = saga["saga_id"]

        # First chain: A→B (fresh session).
        r1 = server_module.send_a2a(
            target="agent-b",
            reason="First call in saga budget test.",
            summary="First A2A call within the saga to track budget.",
            session_id="conv-saga-budget-1",
            from_id="agent-a",
            saga_id=sid,
        )
        assert r1["ok"] is True

        # Second chain: A→B (fresh session, same saga).
        r2 = server_module.send_a2a(
            target="agent-b",
            reason="Second call in saga budget test.",
            summary="Second A2A call within the same saga.",
            session_id="conv-saga-budget-2",
            from_id="agent-a",
            saga_id=sid,
        )
        assert r2["ok"] is True

        # Saga budget should be 2 now.
        status = server_module.get_saga_status(sid)
        assert status["saga"]["budget_used"] == 2
        assert status["saga"]["calls_remaining"] == 4  # 6 - 2

    def test_saga_budget_exhausted(self, server_module):
        """After 6 calls, the saga budget is exhausted → SAGA_BUDGET_EXHAUSTED."""
        saga = server_module.create_saga(root_session_id="conv-saga-exhaust")
        sid = saga["saga_id"]

        # Make 6 successful calls (the saga max budget).
        for i in range(6):
            r = server_module.send_a2a(
                target="agent-b",
                reason=f"Saga call number {i + 1} of six.",
                summary=f"Call {i + 1} within the saga to exhaust budget.",
                session_id=f"conv-saga-exhaust-{i}",
                from_id="agent-a",
                saga_id=sid,
            )
            assert r["ok"] is True, f"call {i + 1} should succeed: {r}"

        # 7th call → rejected with SAGA_BUDGET_EXHAUSTED.
        r7 = server_module.send_a2a(
            target="agent-b",
            reason="Seventh call should be rejected.",
            summary="This call exceeds the saga budget of six calls.",
            session_id="conv-saga-exhaust-6",
            from_id="agent-a",
            saga_id=sid,
        )
        assert r7["ok"] is False
        assert r7["code"] == "SAGA_BUDGET_EXHAUSTED"


# --------------------------------------------------------------------------- #
# Tenant isolation
# --------------------------------------------------------------------------- #

class TestSagaTenantIsolation:
    def test_saga_not_visible_in_other_tenant(self, server_module):
        """A saga created in tenant A is not found in tenant B."""
        # Create saga in default tenant.
        saga_a = server_module.create_saga(
            root_session_id="conv-tenant-a",
            tenant_id="default",
        )
        assert saga_a["ok"] is True

        # Query in tenant B → not found.
        status_b = server_module.get_saga_status(
            saga_id=saga_a["saga_id"],
            tenant_id="tenant-b",
        )
        assert status_b["ok"] is False
        assert "not found" in status_b["reason"]

    def test_send_a2a_saga_isolated_per_tenant(self, server_module):
        """send_a2a with a saga from tenant A fails in tenant B."""
        saga_a = server_module.create_saga(
            root_session_id="conv-iso-a",
            tenant_id="default",
        )
        assert saga_a["ok"] is True

        # Use that saga_id in tenant B → SAGA_NOT_FOUND.
        result = server_module.send_a2a(
            target="agent-b",
            reason="Cross-tenant saga usage should fail.",
            summary="Attempting to use a saga from tenant A in tenant B.",
            session_id="conv-iso-b",
            from_id="agent-a",
            saga_id=saga_a["saga_id"],
            tenant_id="tenant-b",
        )
        assert result["ok"] is False
        assert result["code"] == "SAGA_NOT_FOUND"

    def test_create_saga_in_non_default_tenant(self, server_module):
        """Creating a saga in a non-default tenant works and is isolated."""
        saga_b = server_module.create_saga(
            root_session_id="conv-tenant-b-create",
            tenant_id="tenant-b",
        )
        assert saga_b["ok"] is True

        # Visible in tenant B.
        status_b = server_module.get_saga_status(
            saga_id=saga_b["saga_id"],
            tenant_id="tenant-b",
        )
        assert status_b["ok"] is True

        # Not visible in default tenant.
        status_default = server_module.get_saga_status(
            saga_id=saga_b["saga_id"],
            tenant_id="default",
        )
        assert status_default["ok"] is False
