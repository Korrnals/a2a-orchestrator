"""Unit tests for multi-tenant isolation (a2a_orchestrator.tenant)."""
from __future__ import annotations

import json

from a2a_orchestrator.tenant import DEFAULT_TENANT, TenantContext, TenantManager


def _make_card(agent_id: str, accepts_from: list[str] | None = None) -> dict:
    return {
        "id": agent_id,
        "name": f"Agent: {agent_id}",
        "version": "0.7.0",
        "plugin": "test-plugin",
        "agent_file": f"{agent_id}.agent.md",
        "capabilities": ["test"],
        "routing": {
            "accepts_routes_from": accepts_from or [],
            "routing_keywords": ["test"],
        },
    }


class TestTenantManager:
    def test_default_tenant_created_automatically(self, cards_dir):
        """The default tenant is created on first access."""
        mgr = TenantManager(default_cards_dir=cards_dir)
        ctx = mgr.get_or_create(DEFAULT_TENANT)
        assert ctx.tenant_id == DEFAULT_TENANT
        assert len(ctx.registry) > 0  # cards loaded

    def test_get_or_create_creates_new_tenant(self, cards_dir, tmp_path):
        """A new tenant gets its own cards directory."""
        # Create a separate cards dir for tenant-b.
        tenant_b_cards = tmp_path / "tenant-b-agents"
        tenant_b_cards.mkdir()
        (tenant_b_cards / "agent-x.json").write_text(
            json.dumps(_make_card("agent-x", accepts_from=["agent-y"]))
        )
        (tenant_b_cards / "agent-y.json").write_text(
            json.dumps(_make_card("agent-y", accepts_from=["agent-x"]))
        )

        mgr = TenantManager(default_cards_dir=cards_dir)
        ctx_b = mgr.get_or_create("tenant-b", cards_dir=tenant_b_cards)
        assert ctx_b.tenant_id == "tenant-b"
        assert "agent-x" in ctx_b.registry
        assert "agent-y" in ctx_b.registry
        # Default tenant should NOT have agent-x.
        ctx_default = mgr.get_or_create(DEFAULT_TENANT)
        assert "agent-x" not in ctx_default.registry

    def test_tenant_isolation(self, cards_dir, tmp_path):
        """Agents in tenant A are not visible in tenant B."""
        tenant_a_cards = tmp_path / "tenant-a"
        tenant_a_cards.mkdir()
        (tenant_a_cards / "agent-special.json").write_text(
            json.dumps(_make_card("agent-special", accepts_from=["agent-a"]))
        )

        tenant_b_cards = tmp_path / "tenant-b"
        tenant_b_cards.mkdir()
        (tenant_b_cards / "agent-other.json").write_text(
            json.dumps(_make_card("agent-other", accepts_from=["agent-a"]))
        )

        mgr = TenantManager(default_cards_dir=cards_dir)
        ctx_a = mgr.get_or_create("tenant-a", cards_dir=tenant_a_cards)
        ctx_b = mgr.get_or_create("tenant-b", cards_dir=tenant_b_cards)

        assert "agent-special" in ctx_a.registry
        assert "agent-special" not in ctx_b.registry
        assert "agent-other" in ctx_b.registry
        assert "agent-other" not in ctx_a.registry

    def test_list_tenants(self, cards_dir):
        mgr = TenantManager(default_cards_dir=cards_dir)
        mgr.get_or_create(DEFAULT_TENANT)
        mgr.get_or_create("tenant-x", cards_dir=cards_dir)
        tenants = mgr.list_tenants()
        assert DEFAULT_TENANT in tenants
        assert "tenant-x" in tenants

    def test_remove_tenant(self, cards_dir):
        mgr = TenantManager(default_cards_dir=cards_dir)
        mgr.get_or_create("tenant-temp", cards_dir=cards_dir)
        assert mgr.remove_tenant("tenant-temp") is True
        assert mgr.get("tenant-temp") is None
        assert mgr.remove_tenant("tenant-temp") is False

    def test_tenant_stats(self, cards_dir):
        mgr = TenantManager(default_cards_dir=cards_dir)
        mgr.get_or_create(DEFAULT_TENANT)
        stats = mgr.tenant_stats()
        assert len(stats) >= 1
        assert stats[0]["tenant_id"] == DEFAULT_TENANT
        assert "agents" in stats[0]
        assert "active_sessions" in stats[0]


class TestTenantContext:
    def test_tenant_context_has_all_stores(self):
        ctx = TenantContext(tenant_id="test")
        assert ctx.registry is not None
        assert ctx.session_store is not None
        assert ctx.message_store is not None
        assert ctx.metrics is not None
        assert ctx.saga_store is not None
        assert ctx.key_store is not None

    def test_tenant_session_isolation(self, cards_dir):
        """Sessions in tenant A are not visible in tenant B."""
        mgr = TenantManager(default_cards_dir=cards_dir)
        ctx_a = mgr.get_or_create(DEFAULT_TENANT)
        ctx_b = mgr.get_or_create("tenant-b", cards_dir=cards_dir)

        # Create a session in tenant A.
        ctx_a.session_store.get_or_create("conv-isolated")
        assert ctx_a.session_store.get("conv-isolated") is not None
        # Tenant B should NOT have this session.
        assert ctx_b.session_store.get("conv-isolated") is None


class TestDefaultTenantBackwardCompat:
    def test_no_tenant_id_uses_default(self, cards_dir):
        """When no tenant_id is provided, the default tenant is used."""
        mgr = TenantManager(default_cards_dir=cards_dir)
        ctx = mgr.get_or_create(DEFAULT_TENANT)
        assert ctx.tenant_id == DEFAULT_TENANT
        # The default tenant should have the test cards loaded.
        assert "agent-a" in ctx.registry
