"""Unit tests for R5 destructive-action gate (a2a_orchestrator.destructive)."""
from __future__ import annotations

import pytest
from a2a_orchestrator.destructive import (
    ConsentDenied,
    ConsentRequest,
    default_consent_provider,
    is_destructive,
    request_consent,
)


class TestIsDestructive:
    def test_destructive_intent_is_destructive(self):
        assert is_destructive("destructive-action-request") is True

    @pytest.mark.parametrize("intent", [
        "handoff",
        "request-info",
        "share-finding",
        "request-review",
        "request-implementation",
        "request-documentation",
        "",
        "unknown",
    ])
    def test_other_intents_not_destructive(self, intent):
        assert is_destructive(intent) is False


class TestRequestConsent:
    def test_provider_returns_true_returns_true(self):
        provider = lambda req: True  # noqa: E731
        result = request_consent(
            from_id="agent-a",
            to_id="agent-b",
            summary="Dropping the production table.",
            key_decisions=["Drop table orders"],
            open_questions=["Confirm?"],
            provider=provider,
        )
        assert result is True

    def test_provider_returns_false_raises_consent_denied(self):
        provider = lambda req: False  # noqa: E731
        with pytest.raises(ConsentDenied):
            request_consent(
                from_id="agent-a",
                to_id="agent-b",
                summary="Dropping the production table.",
                key_decisions=["Drop table orders"],
                open_questions=["Confirm?"],
                provider=provider,
            )

    def test_default_consent_provider_returns_false(self):
        """Fail-closed: the default provider denies everything."""
        req = ConsentRequest(
            action_kind="drop-table",
            risk_summary="Drops the orders table",
            requester="agent-a",
            target="agent-b",
            estimated_impact="high",
        )
        assert default_consent_provider(req) is False

    def test_default_provider_raises_consent_denied(self):
        """Using the default provider (fail-closed) raises ConsentDenied."""
        with pytest.raises(ConsentDenied):
            request_consent(
                from_id="agent-a",
                to_id="agent-b",
                summary="Dropping the production table.",
                key_decisions=["Drop table orders"],
                open_questions=["Confirm?"],
                # provider defaults to default_consent_provider
            )
