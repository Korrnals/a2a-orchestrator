"""R5: destructive action gate.

A2A messages whose ``intent`` is ``"destructive-action-request"`` are a
distinct category: the orchestrator must obtain **explicit user
consent** before delivering them. This is the only routing rule that
needs I/O — and even in tests we can stub it via a callable.

Design notes:

* Consent is **explicit per-message**. There is no implicit "yes from a
  previous turn" carryover — destructive intent is rare enough that
  re-asking is cheap and safe.
* Consent is **synchronous in the MCP call**. The agent is blocked
  until the user replies; this is intentional, because A2A is itself
  synchronous from the agent's perspective.
* When consent is denied, the message is persisted with
  ``outcome="rejected"`` and ``rejection_reason="destructive_denied"``
  so Mnemos has a complete audit trail.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

# Stable error code, separate from R1-R4 so the UI can render a different
# message ("The agent wanted to do X. Approve?") instead of a generic
# "routing failed" notice.
R5_DESTRUCTIVE_DENIED = "R5_DESTRUCTIVE_DENIED"
# R5_DESTRUCTIVE_PENDING was removed (L2 fix): it was dead code, never
# referenced anywhere. If a future async consent flow needs a "pending"
# state, re-introduce it with a clear usage site.

# Intent value defined in schemas/a2a-message.schema.json.
DESTRUCTIVE_INTENT = "destructive-action-request"


class ConsentDenied(Exception):
    """Raised when the user explicitly rejects a destructive action."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ConsentRequest:
    """Structured request for user consent, sent to the consent provider.

    The MCP UI layer (or a CLI wrapper) renders this; the provider
    returns either ``True`` (approved) or ``False`` (denied). The
    ``risk_summary`` should fit one screen — the human is busy.
    """

    action_kind: str
    risk_summary: str
    requester: str  # A2A id of the agent asking
    target: str  # A2A id of the agent who would act
    estimated_impact: str


# A consent provider is anything callable that takes a ConsentRequest
# and returns a boolean. Real implementations will use VS Code's UI;
# tests pass a simple lambda.
ConsentProvider = Callable[[ConsentRequest], bool]


class ConsentProviderProtocol(Protocol):
    """Type hint for the consent provider callable (kept for readability)."""

    def __call__(self, request: ConsentRequest) -> bool: ...


def default_consent_provider(request: ConsentRequest) -> bool:
    """Fail-closed default: deny any destructive request when no UI is wired.

    Returning ``False`` here is the safe default — better to refuse and
    require the operator to plug in a real provider than to silently
    allow every destructive action in headless / CI environments.
    """
    return False


def is_destructive(intent: str) -> bool:
    """Return True iff this intent requires R5 user consent."""
    return intent == DESTRUCTIVE_INTENT


def request_consent(
    *,
    from_id: str,
    to_id: str,
    summary: str,
    key_decisions: list[str],
    open_questions: list[str],
    provider: ConsentProvider = default_consent_provider,
) -> bool:
    """Ask the user via ``provider`` whether to allow a destructive A2A.

    Returns ``True`` only when the user explicitly approves. On denial
    raises :class:`ConsentDenied` so the caller can map it to a clean
    REJECT response.
    """
    request = ConsentRequest(
        action_kind="a2a:destructive-action-request",
        risk_summary=summary,
        requester=from_id,
        target=to_id,
        estimated_impact="; ".join(key_decisions + open_questions) or "(no detail)",
    )
    approved = bool(provider(request))
    if not approved:
        raise ConsentDenied(
            "User denied consent for destructive A2A from "
            f"{from_id!r} to {to_id!r}. Do not retry — answer the user instead."
        )
    return True
