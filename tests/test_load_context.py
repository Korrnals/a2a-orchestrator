"""Tests for the load_context MCP tool (a2a_orchestrator.server)."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest


@pytest.fixture()
def server_module(env_isolated, tmp_path, monkeypatch):
    """Import the server module fresh, with test env and temp JSONL path."""
    monkeypatch.setenv("A2A_FALLBACK_JSONL", str(tmp_path / "lc.jsonl"))
    import importlib

    import a2a_orchestrator.config as config_mod
    importlib.reload(config_mod)
    import a2a_orchestrator.server as srv
    importlib.reload(srv)
    srv.registry.load()
    srv.session_store.clear()
    srv.message_store = srv.MessageStore(path=tmp_path / "lc.jsonl")
    # C2 fix: send_a2a now uses ctx.message_store (per-tenant).
    srv._default_ctx.message_store = srv.message_store
    srv.metrics.reset()
    return srv


class TestLoadContextByTurnId:
    def test_load_by_turn_id_mnemos_available(self, server_module):
        """Load by turn_id when Mnemos is available → returns message."""
        turn_body = {
            "role": "a2a_message",
            "content": json.dumps({
                "message_id": "msg-test00000001",
                "from": "agent-a",
                "to": "agent-b",
                "payload": {"summary": "Test summary for load_context."},
            }),
        }
        with patch.object(server_module.mnemos_client, "get_turn",
                          return_value=turn_body):
            result = server_module.load_context(
                session_id="conv-lc-001",
                turn_id="turn-001",
                mode="summary",
            )
        assert result["ok"] is True
        assert result["message"]["message_id"] == "msg-test00000001"
        assert result["message"]["from"] == "agent-a"

    def test_load_by_turn_id_mode_full(self, server_module):
        """Load with mode=full passes mode to Mnemos client."""
        turn_body = {
            "content": json.dumps({"message_id": "msg-test00000002"}),
        }
        with patch.object(server_module.mnemos_client, "get_turn",
                          return_value=turn_body) as mock_get:
            result = server_module.load_context(
                session_id="conv-lc-002",
                turn_id="turn-002",
                mode="full",
            )
        assert result["ok"] is True
        # Verify mode was passed
        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs.get("mode") == "full" or "full" in str(call_kwargs)


class TestLoadContextByMessageId:
    def test_load_by_message_id_mnemos_available(self, server_module):
        """Load by message_id (no turn_id) → searches Mnemos turns."""
        range_resp = {
            "turns": [
                {"content": json.dumps({"message_id": "msg-other001"})},
                {"content": json.dumps({
                    "message_id": "msg-target01",
                    "from": "agent-a",
                    "to": "agent-b",
                    "payload": {"summary": "Found the target message."},
                })},
            ],
        }
        with patch.object(server_module.mnemos_client, "get_turn_range",
                          return_value=range_resp):
            result = server_module.load_context(
                session_id="conv-lc-003",
                message_id="msg-target01",
            )
        assert result["ok"] is True
        assert result["message"]["message_id"] == "msg-target01"

    def test_load_by_message_id_not_found_in_mnemos(self, server_module):
        """Message_id not found in Mnemos turns → returns not found."""
        range_resp = {"turns": [
            {"content": json.dumps({"message_id": "msg-other002"})}
        ]}
        with patch.object(server_module.mnemos_client, "get_turn_range",
                          return_value=range_resp):
            result = server_module.load_context(
                session_id="conv-lc-004",
                message_id="msg-nonexistent",
            )
        assert result["ok"] is False
        assert result["message"] is None


class TestLoadContextFallback:
    def test_fallback_to_jsonl_when_mnemos_unavailable(self, server_module):
        """When Mnemos is unavailable, fall back to JSONL store."""
        from a2a_orchestrator.mnemos_client import MnemosUnavailableError

        # First, send a message to populate the JSONL store.
        with patch.object(server_module.mnemos_client, "write_turn",
                          side_effect=MnemosUnavailableError("mocked")):
            send_result = server_module.send_a2a(
                target="agent-b",
                reason="Populating JSONL for fallback test.",
                summary="This message goes to JSONL because Mnemos is down.",
                session_id="conv-lc-005",
                from_id="agent-a",
            )
        assert send_result["ok"] is True
        msg_id = send_result["message_id"]

        # Now load_context with Mnemos unavailable → should find in JSONL.
        with patch.object(server_module.mnemos_client, "get_turn_range",
                          side_effect=MnemosUnavailableError("mocked")):
            result = server_module.load_context(
                session_id="conv-lc-005",
                message_id=msg_id,
            )
        assert result["ok"] is True
        assert result["message"]["message_id"] == msg_id
        assert "JSONL" in result["reason"]

    def test_not_found_returns_ok_false(self, server_module):
        """Neither Mnemos nor JSONL has the message → ok=False."""
        from a2a_orchestrator.mnemos_client import MnemosUnavailableError

        with patch.object(server_module.mnemos_client, "get_turn_range",
                          side_effect=MnemosUnavailableError("mocked")):
            result = server_module.load_context(
                session_id="conv-nonexistent",
                message_id="msg-doesnotexist",
            )
        assert result["ok"] is False
        assert result["message"] is None
        assert "not found" in result["reason"].lower()


class TestLoadContextEdgeCases:
    def test_empty_turn_id_and_message_id(self, server_module):
        """Both turn_id and message_id empty → not found."""
        result = server_module.load_context(
            session_id="conv-lc-006",
            turn_id="",
            message_id="",
        )
        assert result["ok"] is False
        assert result["message"] is None

    def test_content_is_dict_not_string(self, server_module):
        """When Mnemos returns content as a dict (not JSON string)."""
        turn_body = {
            "content": {"message_id": "msg-dict001", "from": "agent-a"},
        }
        with patch.object(server_module.mnemos_client, "get_turn",
                          return_value=turn_body):
            result = server_module.load_context(
                session_id="conv-lc-007",
                turn_id="turn-007",
            )
        assert result["ok"] is True
        assert result["message"]["message_id"] == "msg-dict001"
