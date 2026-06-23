"""Unit tests for JSON-schema validation (a2a_orchestrator.validation)."""
from __future__ import annotations

import pytest
from a2a_orchestrator.validation import ValidationError, validate_a2a_message, validate_agent_card

# --------------------------------------------------------------------------- #
# Agent Card validation
# --------------------------------------------------------------------------- #

class TestValidateAgentCard:
    def test_valid_card_no_exception(self, env_isolated):
        from a2a_orchestrator.validation import _AGENT_CARD_VALIDATOR  # noqa: F401
        card = {
            "id": "agent-test-agent",
            "name": "Test",
            "version": "0.6.0",
            "plugin": "test-plugin",
            "agent_file": "test-agent.agent.md",
            "capabilities": ["test-cap"],
            "routing": {
                "accepts_routes_from": [],
                "routing_keywords": ["test"],
            },
            "tags": [],
        }
        validate_agent_card(card)  # should not raise

    def test_invalid_card_missing_required_field(self, env_isolated):
        from a2a_orchestrator.validation import _AGENT_CARD_VALIDATOR  # noqa: F401
        card = {
            "id": "agent-test-agent",
            # missing name, version, plugin, agent_file, capabilities, routing
        }
        with pytest.raises(ValidationError):
            validate_agent_card(card)


# --------------------------------------------------------------------------- #
# A2A message validation
# --------------------------------------------------------------------------- #

class TestValidateA2AMessage:
    def test_valid_message_no_exception(self, env_isolated, valid_message):
        from a2a_orchestrator.validation import _A2A_MESSAGE_VALIDATOR  # noqa: F401
        validate_a2a_message(valid_message)  # should not raise

    def test_invalid_message_missing_required_field(self, env_isolated):
        from a2a_orchestrator.validation import _A2A_MESSAGE_VALIDATOR  # noqa: F401
        msg = {
            "schema_version": "0.7.0",
            # missing message_id, session_id, from, to, intent, payload, routing_meta
        }
        with pytest.raises(ValidationError):
            validate_a2a_message(msg)

    def test_invalid_message_bad_schema_version(self, env_isolated, valid_message):
        from a2a_orchestrator.validation import _A2A_MESSAGE_VALIDATOR  # noqa: F401
        msg = dict(valid_message)
        msg["schema_version"] = "99.0.0"  # const is 0.7.0
        with pytest.raises(ValidationError):
            validate_a2a_message(msg)

    def test_invalid_message_bad_intent(self, env_isolated, valid_message):
        from a2a_orchestrator.validation import _A2A_MESSAGE_VALIDATOR  # noqa: F401
        msg = dict(valid_message)
        msg["intent"] = "not-a-valid-intent"
        with pytest.raises(ValidationError):
            validate_a2a_message(msg)

    def test_invalid_message_short_reason(self, env_isolated, valid_message):
        from a2a_orchestrator.validation import _A2A_MESSAGE_VALIDATOR  # noqa: F401
        msg = dict(valid_message)
        msg["reason"] = "short"  # minLength 10
        with pytest.raises(ValidationError):
            validate_a2a_message(msg)

    def test_invalid_message_short_summary(self, env_isolated, valid_message):
        from a2a_orchestrator.validation import _A2A_MESSAGE_VALIDATOR  # noqa: F401
        msg = dict(valid_message)
        msg["payload"] = {"summary": "too short"}  # minLength 20
        with pytest.raises(ValidationError):
            validate_a2a_message(msg)
