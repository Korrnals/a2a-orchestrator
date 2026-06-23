"""Tests for the CLI wrapper (a2a_orchestrator.cli).

The CLI does lazy imports inside command functions (``from .server import
send_a2a``), so we patch the server module's attributes rather than the
CLI module's.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest


@pytest.fixture()
def server_module(env_isolated, tmp_path, monkeypatch):
    """Import the server module fresh, with test env and temp JSONL path."""
    monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "cli.jsonl"))
    import importlib

    import a2a_orchestrator.config as config_mod
    importlib.reload(config_mod)
    import a2a_orchestrator.server as srv
    importlib.reload(srv)
    srv.registry.load()
    srv.session_store.clear()
    srv.message_store = srv.MessageStore(path=tmp_path / "cli.jsonl")
    # C2 fix: send_a2a now uses ctx.message_store (per-tenant), so we
    # must also update the default tenant context's store.
    srv._default_ctx.message_store = srv.message_store
    srv.metrics.reset()
    return srv


@pytest.fixture()
def cli_module(server_module):
    """Import the CLI module fresh (after server is reloaded)."""
    import importlib

    import a2a_orchestrator.cli as cli
    importlib.reload(cli)
    return cli


class TestCliSend:
    def test_send_command_produces_result(self, cli_module, capsys):
        """``send`` command produces same result as MCP tool."""
        with patch("a2a_orchestrator.server.send_a2a",
                   return_value={"ok": True, "message_id": "msg-cli001",
                                 "reason": "delivered", "next_senior": "agent-b"}):
            exit_code = cli_module.main([
                "send", "--from", "agent-a", "--to", "agent-b",
                "--reason", "CLI smoke test handoff.",
                "--summary", "This is a CLI smoke test for the send command.",
                "--session-id", "conv-cli-001",
            ])
        assert exit_code == 0
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["ok"] is True
        assert parsed["message_id"] == "msg-cli001"

    def test_send_command_with_artifacts(self, cli_module, capsys):
        """``send`` with --artifact parses kind:pointer correctly."""
        captured_args: dict = {}

        def fake_send(**kwargs):
            captured_args.update(kwargs)
            return {"ok": True, "message_id": "msg-cli002"}

        with patch("a2a_orchestrator.server.send_a2a", side_effect=fake_send):
            cli_module.main([
                "send", "--from", "agent-a", "--to", "agent-b",
                "--reason", "Testing artifact parsing in CLI.",
                "--summary", "This is a CLI test with artifact arguments.",
                "--artifact", "file:src/models.py",
                "--artifact", "diff:changes.patch",
            ])
        assert captured_args["artifacts"] == [
            {"kind": "file", "pointer": "src/models.py"},
            {"kind": "diff", "pointer": "changes.patch"},
        ]

    def test_send_command_rejected_returns_exit_1(self, cli_module, capsys):
        """Rejected send → exit code 1."""
        with patch("a2a_orchestrator.server.send_a2a",
                   return_value={"ok": False, "code": "R1_NOT_WHITELISTED",
                                 "reason": "not allowed"}):
            exit_code = cli_module.main([
                "send", "--from", "agent-a", "--to", "agent-c",
                "--reason", "This route should be rejected.",
                "--summary", "Testing CLI exit code on rejection.",
            ])
        assert exit_code == 1


class TestCliList:
    def test_list_command_returns_messages(self, cli_module, capsys):
        """``list`` command returns messages from the store."""
        with patch("a2a_orchestrator.server.message_store") as mock_store:
            mock_store.load_recent.return_value = [
                {"message_id": "msg-cli-list1", "outcome": "delivered"},
            ]
            exit_code = cli_module.main([
                "list", "--session-id", "conv-cli-002", "--limit", "5",
            ])
        assert exit_code == 0
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["ok"] is True
        assert parsed["count"] == 1
        assert parsed["messages"][0]["message_id"] == "msg-cli-list1"


class TestCliStatus:
    def test_status_command_returns_chain_status(self, cli_module, capsys):
        """``status`` command returns chain status."""
        with patch("a2a_orchestrator.server.get_chain_status",
                   return_value={"ok": True, "chain": ["agent-a"],
                                 "depth": 1, "budget_used": 1,
                                 "calls_remaining": 2,
                                 "recent_messages": []}):
            exit_code = cli_module.main([
                "status", "--session-id", "conv-cli-003",
            ])
        assert exit_code == 0
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["ok"] is True
        assert parsed["chain"] == ["agent-a"]
        assert parsed["depth"] == 1


class TestCliAgents:
    def test_agents_command_lists_agents(self, cli_module, capsys):
        """``agents`` command lists registered agents."""
        with patch("a2a_orchestrator.server.registry") as mock_reg:
            mock_reg.list_agents.return_value = [
                {"id": "agent-a", "name": "Agent A"},
                {"id": "agent-b", "name": "Agent B"},
            ]
            exit_code = cli_module.main(["agents"])
        assert exit_code == 0
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["ok"] is True
        assert parsed["count"] == 2
        assert parsed["agents"][0]["id"] == "agent-a"


class TestCliMetrics:
    def test_metrics_command_returns_counters(self, cli_module, capsys):
        """``metrics`` command returns metrics counters."""
        with patch("a2a_orchestrator.server.get_metrics",
                   return_value={"messages_delivered": 5,
                                 "messages_rejected": 2}):
            exit_code = cli_module.main(["metrics"])
        assert exit_code == 0
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["messages_delivered"] == 5
        assert parsed["messages_rejected"] == 2


class TestCliNoCommand:
    def test_no_command_prints_help(self, cli_module, capsys):
        """Running with no command prints help and exits 0."""
        exit_code = cli_module.main([])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "usage:" in out.lower() or "available commands" in out.lower()


class TestCliSagaCreate:
    def test_saga_create_command(self, cli_module, capsys):
        """``saga create`` command calls create_saga and returns saga_id."""
        with patch("a2a_orchestrator.server.create_saga",
                   return_value={"ok": True, "saga_id": "saga-cli001",
                                 "reason": "created"}):
            exit_code = cli_module.main([
                "saga", "create",
                "--root-session", "conv-cli-saga",
                "--metadata", '{"task":"migration"}',
            ])
        assert exit_code == 0
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["ok"] is True
        assert parsed["saga_id"] == "saga-cli001"
        assert parsed["reason"] == "created"

    def test_saga_create_command_no_metadata(self, cli_module, capsys):
        """``saga create`` without --metadata works (empty string)."""
        with patch("a2a_orchestrator.server.create_saga",
                   return_value={"ok": True, "saga_id": "saga-cli002",
                                 "reason": "created"}):
            exit_code = cli_module.main([
                "saga", "create",
                "--root-session", "conv-cli-saga-2",
            ])
        assert exit_code == 0
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["ok"] is True

    def test_saga_create_command_failure_exit_1(self, cli_module, capsys):
        """``saga create`` with invalid metadata → exit code 1."""
        with patch("a2a_orchestrator.server.create_saga",
                   return_value={"ok": False, "saga_id": "",
                                 "reason": "metadata is not valid JSON"}):
            exit_code = cli_module.main([
                "saga", "create",
                "--root-session", "conv-cli-saga-3",
                "--metadata", "{bad",
            ])
        assert exit_code == 1
