"""R1-R4 routing gates.

The protocol defines 5 checks (see the A2A protocol spec §4).
R5 (destructive action) lives in :mod:`.destructive` because it requires
user-consent I/O. R1-R4 are pure functions over the registry, the
session state, and the proposed message — they never touch I/O and can
be unit-tested without any fixture.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .registry import AgentCardRegistry
from .session import MAX_CHAIN_DEPTH, SessionState

# Stable error codes for REJECT outcomes. The MCP client maps these to
# the visible UI message; the numeric prefix is preserved in logs.
R1_NOT_WHITELISTED = "R1_NOT_WHITELISTED"
R2_LOOP_DETECTED = "R2_LOOP_DETECTED"
R3_CHAIN_TOO_DEEP = "R3_CHAIN_TOO_DEEP"
R4_BUDGET_EXHAUSTED = "R4_BUDGET_EXHAUSTED"
R6_SIGNATURE_INVALID = "R6_SIGNATURE_INVALID"


@dataclass(frozen=True)
class Rejection:
    """A pure data class describing a REJECT outcome.

    The orchestrator wraps this in a tool response (with ``isError=True``);
    persistence code maps it to the Mnemos ``outcome`` enum.
    """

    code: str
    message: str

    def to_dict(self) -> dict:
        return {"ok": False, "code": self.code, "reason": self.message}


def check_whitelist(
    from_id: str,
    to_id: str,
    registry: AgentCardRegistry,
) -> Rejection | None:
    """R1: ``to_id`` must be reachable from ``from_id`` in the whitelist.

    A REJECT is returned if the sender is not in the registry (no card
    means no routes), or the target is not in the sender's allowed set.
    """
    if from_id not in registry:
        return Rejection(
            R1_NOT_WHITELISTED,
            f"Sender {from_id!r} is not registered in the Agent Card registry",
        )
    if to_id not in registry:
        return Rejection(
            R1_NOT_WHITELISTED,
            f"Target {to_id!r} is not registered in the Agent Card registry",
        )
    if to_id not in registry.allowed_targets(from_id):
        return Rejection(
            R1_NOT_WHITELISTED,
            (
                f"Agent {from_id!r} is not authorized to route to "
                f"{to_id!r}. Check the receiver's accepts_routes_from."
            ),
        )
    return None


def check_loop(
    to_id: str,
    session: SessionState,
) -> Rejection | None:
    """R2: target must not already be upstream in the current chain.

    A loop exists when the same A2A id appears twice in ``session.chain``.
    We reject the *target* being already in the chain — the *sender* is
    always in the chain (it sent the previous message) and its presence
    is normal.
    """
    if to_id in session.chain:
        return Rejection(
            R2_LOOP_DETECTED,
            (
                f"Loop detected: {to_id!r} is already upstream of you in "
                "this chain. Ask the user to clarify."
            ),
        )
    return None


def check_depth(
    from_id: str,
    to_id: str,
    session: SessionState,
    registry: AgentCardRegistry,
) -> Rejection | None:
    """R3: chain depth must not exceed the per-target cap (≤ 3 by default).

    The "next hop" depth is ``session.depth()``: depth 0 for the first
    message, 1 for the second, etc. We compare against the *minimum* of
    the protocol-wide ceiling and the per-card overrides of both the
    sender and the target.

    M2 fix: previously this only checked the sender's ``max_chain_depth``.
    Now it also checks the target's — if the target declares
    ``max_chain_depth=1``, it should reject being at depth 2+.
    """
    next_depth = session.depth()
    # Per-protocol the cap is applied to the *receiver*, but the receiver
    # is not yet known to ``session`` — we use the protocol-wide cap for
    # the global check, then we apply the per-card caps below.
    if next_depth >= MAX_CHAIN_DEPTH:
        return Rejection(
            R3_CHAIN_TOO_DEEP,
            (
                f"Chain too deep (depth {next_depth}, max {MAX_CHAIN_DEPTH}). "
                "Stop routing and answer the user."
            ),
        )
    # Per-card override for the sender. Some agents (e.g. tech writer)
    # declare ``max_chain_depth=5`` to allow long chains; others set 1
    # to forbid being deep. We apply the sender's own override here so
    # that an agent that has declared "never deep" is protected.
    sender_cap = registry.max_chain_depth(from_id)
    if next_depth >= sender_cap:
        return Rejection(
            R3_CHAIN_TOO_DEEP,
            (
                f"Sender {from_id!r} declared max_chain_depth={sender_cap}; "
                f"current depth {next_depth} would exceed it."
            ),
        )
    # M2 fix: also check the target's per-card override. If the target
    # declares ``max_chain_depth=1``, it should reject being at depth 1+.
    target_cap = registry.max_chain_depth(to_id)
    if next_depth >= target_cap:
        return Rejection(
            R3_CHAIN_TOO_DEEP,
            (
                f"Target {to_id!r} declared max_chain_depth={target_cap}; "
                f"current depth {next_depth} would exceed it."
            ),
        )
    return None


def check_budget(session: SessionState) -> Rejection | None:
    """R4: A2A call must not exceed the per-conversation budget (3)."""
    if session.calls_remaining() <= 0:
        return Rejection(
            R4_BUDGET_EXHAUSTED,
            (
                f"Budget exhausted ({session.budget_used} A2A calls used "
                f"of {session.budget_used + session.calls_remaining()}). "
                "Stop routing and answer the user."
            ),
        )
    return None


def check_signature(
    from_id: str,
    message: dict[str, Any],
    signature: str,
    registry: AgentCardRegistry,
    key_store: Any | None = None,
) -> Rejection | None:
    """R6: verify the message signature if the sender has a public key.

    This rule only fires when the sender's Agent Card (or the runtime
    KeyStore) has a ``public_key`` for ``from_id``. If no key is
    registered, verification is skipped (backward compat,
    trust-by-construction).

    Args:
        from_id: The sending agent's A2A id.
        message: The A2A message dict (without the signature field).
        signature: The base64 signature string (may be empty).
        registry: The Agent Card registry (checked for ``public_key``).
        key_store: Optional runtime KeyStore with additional keys.

    Returns:
        ``None`` if verification passes or is skipped; a ``Rejection``
        with ``R6_SIGNATURE_INVALID`` if the key exists but the
        signature is missing or invalid.
    """
    from .signing import verify_message

    # Determine if the sender has a public key.
    public_key_b64: str | None = None

    # Check the runtime KeyStore first (external agents registered at
    # runtime may not be in the file-based registry).
    if key_store is not None and key_store.has_key(from_id):
        # KeyStore has the key object directly — we can verify.
        if not signature:
            return Rejection(
                R6_SIGNATURE_INVALID,
                f"Agent {from_id!r} has a registered public key but the "
                "message has no signature. Signing is required.",
            )
        public_key = key_store.get_key(from_id)
        if public_key is None:
            return Rejection(
                R6_SIGNATURE_INVALID,
                f"Agent {from_id!r} key lookup failed unexpectedly.",
            )
        if not verify_message(message, signature, public_key):
            return Rejection(
                R6_SIGNATURE_INVALID,
                f"Signature verification failed for agent {from_id!r}. "
                "The message may have been tampered with or the key is wrong.",
            )
        return None

    # Check the Agent Card registry for a public_key field.
    card = registry.get(from_id)
    if card is not None:
        public_key_b64 = card.get("public_key")

    if not public_key_b64:
        # No public key registered → skip verification (backward compat).
        return None

    if not signature:
        return Rejection(
            R6_SIGNATURE_INVALID,
            f"Agent {from_id!r} has a public_key in its Agent Card but the "
            "message has no signature. Signing is required.",
        )

    from .signing import load_public_key

    try:
        public_key = load_public_key(public_key_b64)
    except Exception:
        return Rejection(
            R6_SIGNATURE_INVALID,
            f"Agent {from_id!r} has an invalid public_key in its Agent Card.",
        )

    if not verify_message(message, signature, public_key):
        return Rejection(
            R6_SIGNATURE_INVALID,
            f"Signature verification failed for agent {from_id!r}. "
            "The message may have been tampered with or the key is wrong.",
        )

    return None


def check_all(
    from_id: str,
    to_id: str,
    session: SessionState,
    registry: AgentCardRegistry,
) -> Rejection | None:
    """Apply R1 → R2 → R3 → R4 in order and return the first failure.

    Per the protocol spec the fast checks (whitelist) run first so a
    misconfigured agent fails before any state is mutated.

    .. note::
       This function only applies R1-R4 (the pure, I/O-free checks).
       R5 (destructive-action consent) and R6 (signature verification)
       are **excluded** because:

       * **R5** requires user-consent I/O (``request_consent``), which
         is not available in a pure routing gate. It is checked
         separately in :func:`server.send_a2a` after R1-R4 pass.
       * **R6** requires the message dict (for canonical JSON) and the
         KeyStore, which are not arguments to this function. It is
         checked separately via :func:`check_signature`.

       The name ``check_all`` is retained for API compatibility; it
       means "all I/O-free routing checks", not "all 6 checks".
    """
    for gate in (
        lambda: check_whitelist(from_id, to_id, registry),
        lambda: check_loop(to_id, session),
        lambda: check_depth(from_id, to_id, session, registry),
        lambda: check_budget(session),
    ):
        rejection = gate()
        if rejection is not None:
            return rejection
    return None
