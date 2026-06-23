"""Tests for the Metrics class (a2a_orchestrator.metrics)."""
from __future__ import annotations

import threading
from unittest.mock import patch

import pytest


@pytest.fixture()
def server_module(env_isolated, tmp_path, monkeypatch):
    """Import the server module fresh, with test env and temp JSONL path."""
    monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "mt.jsonl"))
    import importlib

    import a2a_orchestrator.config as config_mod
    importlib.reload(config_mod)
    import a2a_orchestrator.server as srv
    importlib.reload(srv)
    srv.registry.load()
    srv.session_store.clear()
    srv.message_store = srv.MessageStore(path=tmp_path / "mt.jsonl")
    # C2 fix: send_a2a now uses ctx.message_store (per-tenant).
    srv._default_ctx.message_store = srv.message_store
    srv.metrics.reset()
    return srv


class TestMetricsCounters:
    def test_initial_state_all_zero(self, server_module):
        """Fresh metrics → all counters at zero."""
        m = server_module.metrics.snapshot()
        assert m["messages_delivered"] == 0
        assert m["messages_rejected"] == 0
        assert m["mnemos_writes"] == 0
        assert m["fallback_writes"] == 0
        assert m["total_sessions"] == 0
        assert all(v == 0 for v in m["rejections_by_rule"].values())

    def test_delivered_increments(self, server_module):
        """Successful send_a2a increments messages_delivered."""
        with patch.object(server_module.mnemos_client, "write_turn",
                          return_value={"turn_id": "t1"}):
            server_module.send_a2a(
                target="agent-b",
                reason="Testing metrics delivery counter.",
                summary="This message should increment the delivered counter.",
                session_id="conv-mt-001",
                from_id="agent-a",
            )
        m = server_module.metrics.snapshot()
        assert m["messages_delivered"] == 1
        assert m["messages_rejected"] == 0

    def test_rejected_increments(self, server_module):
        """Rejected send_a2a increments messages_rejected + rejections_by_rule."""
        server_module.send_a2a(
            target="agent-c",  # A cannot call C (not whitelisted)
            reason="Testing metrics rejection counter.",
            summary="This message should increment the rejected counter.",
            session_id="conv-mt-002",
            from_id="agent-a",
        )
        m = server_module.metrics.snapshot()
        assert m["messages_delivered"] == 0
        assert m["messages_rejected"] == 1
        assert m["rejections_by_rule"]["R1_NOT_WHITELISTED"] == 1

    def test_multiple_rejections_by_rule(self, server_module):
        """Different rejection codes are tracked separately."""
        # R1 rejection (A→C not whitelisted)
        server_module.send_a2a(
            target="agent-c",
            reason="R1 rejection for metrics test.",
            summary="This should be rejected by R1 whitelist check.",
            session_id="conv-mt-r1",
            from_id="agent-a",
        )
        # R4 rejection (budget exhausted)
        session = server_module.session_store.get_or_create("conv-mt-r4")
        session.budget_used = 3
        server_module.send_a2a(
            target="agent-b",
            reason="R4 rejection for metrics test.",
            summary="This should be rejected by R4 budget check.",
            session_id="conv-mt-r4",
            from_id="agent-a",
        )
        m = server_module.metrics.snapshot()
        assert m["messages_rejected"] == 2
        assert m["rejections_by_rule"]["R1_NOT_WHITELISTED"] == 1
        assert m["rejections_by_rule"]["R4_BUDGET_EXHAUSTED"] == 1


class TestMetricsPersistence:
    def test_mnemos_write_incremented(self, server_module):
        """Successful Mnemos write increments mnemos_writes."""
        with patch.object(server_module.mnemos_client, "write_turn",
                          return_value={"turn_id": "t1"}):
            server_module.send_a2a(
                target="agent-b",
                reason="Testing mnemos_writes counter.",
                summary="This message should increment the mnemos_writes counter.",
                session_id="conv-mt-003",
                from_id="agent-a",
            )
        m = server_module.metrics.snapshot()
        assert m["mnemos_writes"] == 1
        assert m["fallback_writes"] == 0

    def test_fallback_write_incremented(self, server_module):
        """Mnemos unavailable → fallback_writes incremented."""
        from a2a_orchestrator.mnemos_client import MnemosUnavailableError

        with patch.object(server_module.mnemos_client, "write_turn",
                          side_effect=MnemosUnavailableError("mocked")):
            server_module.send_a2a(
                target="agent-b",
                reason="Testing fallback_writes counter.",
                summary="This message should increment the fallback_writes counter.",
                session_id="conv-mt-004",
                from_id="agent-a",
            )
        m = server_module.metrics.snapshot()
        assert m["mnemos_writes"] == 0
        assert m["fallback_writes"] == 1


class TestMetricsThreadSafety:
    def test_concurrent_increments(self, server_module):
        """100 threads incrementing delivered counter → no lost updates."""
        errors: list[Exception] = []

        def sender() -> None:
            try:
                server_module.metrics.record_delivered()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=sender) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        m = server_module.metrics.snapshot()
        assert m["messages_delivered"] == 100

    def test_concurrent_mixed_operations(self, server_module):
        """Concurrent mix of delivered/rejected/mnemos → all counted correctly."""
        errors: list[Exception] = []

        def worker() -> None:
            try:
                server_module.metrics.record_delivered()
                server_module.metrics.record_rejected("R1_NOT_WHITELISTED")
                server_module.metrics.record_mnemos_write()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        m = server_module.metrics.snapshot()
        assert m["messages_delivered"] == 50
        assert m["messages_rejected"] == 50
        assert m["rejections_by_rule"]["R1_NOT_WHITELISTED"] == 50
        assert m["mnemos_writes"] == 50


class TestGetMetricsTool:
    def test_get_metrics_returns_snapshot(self, server_module):
        """get_metrics tool returns a dict with all expected keys."""
        result = server_module.get_metrics()
        assert "messages_delivered" in result
        assert "messages_rejected" in result
        assert "rejections_by_rule" in result
        assert "mnemos_writes" in result
        assert "fallback_writes" in result
        assert "active_sessions" in result
        assert "total_sessions" in result

    def test_get_metrics_after_activity(self, server_module):
        """After some activity, get_metrics reflects the counts."""
        with patch.object(server_module.mnemos_client, "write_turn",
                          return_value={"turn_id": "t1"}):
            server_module.send_a2a(
                target="agent-b",
                reason="Testing get_metrics after activity.",
                summary="This message should be reflected in metrics.",
                session_id="conv-mt-005",
                from_id="agent-a",
            )
        result = server_module.get_metrics()
        assert result["messages_delivered"] == 1
        assert result["mnemos_writes"] == 1
        assert result["total_sessions"] == 1
