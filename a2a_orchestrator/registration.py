"""External agent registration with challenge-response signing.

Agents outside the workspace can register at runtime by submitting
their Agent Card + public key, proving ownership of the corresponding
private key via a challenge-response signature.

Flow:

1. Agent calls ``create_challenge(agent_id)`` → orchestrator generates
   a nonce, stores it with a 5-minute TTL.
2. Agent signs the nonce with their private key.
3. Agent calls ``register(agent_card, public_key, challenge_signature)``.
4. Orchestrator verifies the signature against the nonce, validates the
   Agent Card, and adds the card + key to the runtime registry + KeyStore.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .registry import AgentCardRegistry
from .signing import KeyStore, load_public_key, verify_message
from .validation import validate_agent_card

CHALLENGE_TTL_SECONDS = 300  # 5 minutes
MAX_PENDING_CHALLENGES = 100  # M4 fix: cap total pending challenges.


@dataclass
class Challenge:
    """A pending registration challenge.

    Attributes:
        agent_id: The agent that requested the challenge.
        nonce: The random string the agent must sign.
        created_at: Unix epoch seconds.
        expires_at: Unix epoch seconds (created_at + TTL).
    """

    agent_id: str
    nonce: str
    created_at: float
    expires_at: float

    def is_expired(self, now: float | None = None) -> bool:
        """Return ``True`` if the challenge has expired."""
        return (now or time.time()) > self.expires_at


@dataclass
class RegistrationRequest:
    """A registration submission from an external agent.

    Attributes:
        agent_card: The Agent Card dict to register.
        public_key: Base64 Ed25519 public key.
        challenge_signature: Base64 signature of the challenge nonce.
    """

    agent_card: dict[str, Any]
    public_key: str
    challenge_signature: str


class RegistrationService:
    """Manages external agent registration with challenge-response.

    Args:
        registry: The runtime Agent Card registry to add cards to.
        key_store: The KeyStore to add public keys to.
    """

    def __init__(self, registry: AgentCardRegistry, key_store: KeyStore) -> None:
        self._registry = registry
        self._key_store = key_store
        self._challenges: dict[str, Challenge] = {}
        self._lock = threading.Lock()

    def create_challenge(self, agent_id: str) -> str:
        """Generate a challenge nonce for ``agent_id``.

        Returns the nonce string. The agent must sign this nonce with
        their private key and submit the signature in ``register()``.

        M4 fix: on each call, a global cleanup pass removes all expired
        challenges (across all agent_ids) and the total pending count is
        capped at :data:`MAX_PENDING_CHALLENGES` to prevent unbounded
        memory growth from unique agent_ids.
        """
        nonce = f"challenge-{uuid4().hex[:24]}"
        now = time.time()
        challenge = Challenge(
            agent_id=agent_id,
            nonce=nonce,
            created_at=now,
            expires_at=now + CHALLENGE_TTL_SECONDS,
        )
        with self._lock:
            # M4 fix: global cleanup — remove ALL expired challenges,
            # not just for this agent_id.
            self._cleanup_all_expired()
            # M4 fix: cap total pending challenges. If at the limit,
            # reject new challenges to prevent unbounded memory growth.
            if len(self._challenges) >= MAX_PENDING_CHALLENGES:
                raise RuntimeError(
                    f"Maximum pending challenges ({MAX_PENDING_CHALLENGES}) "
                    "reached. Expire or complete existing challenges first."
                )
            self._challenges[agent_id] = challenge
        return nonce

    def verify_registration(self, request: RegistrationRequest) -> bool:
        """Verify a registration request without committing it.

        Returns ``True`` if the challenge signature is valid and not
        expired, ``False`` otherwise. Does NOT modify the registry.
        """
        agent_id = request.agent_card.get("id", "")
        with self._lock:
            challenge = self._challenges.get(agent_id)
            if challenge is None or challenge.is_expired():
                return False

        try:
            public_key = load_public_key(request.public_key)
        except Exception:
            return False

        # The signature is over the challenge nonce (canonical JSON of
        # a simple dict so verify_message can be reused).
        signed_payload = {"nonce": challenge.nonce, "agent_id": agent_id}
        return verify_message(signed_payload, request.challenge_signature, public_key)

    def register(self, request: RegistrationRequest) -> dict[str, Any]:
        """Verify and register an external agent.

        Returns a dict with ``ok: bool`` and either the registered agent
        id or an error reason.

        H4 fix: the entire register flow (steps 3-6) holds ``self._lock``
        so the registry and key store mutations are atomic with respect
        to concurrent register/unregister calls.
        """
        agent_id = request.agent_card.get("id", "")

        # 1. Verify the challenge signature.
        if not self.verify_registration(request):
            return {"ok": False, "reason": "challenge verification failed "
                    "(invalid signature or expired challenge)"}

        # 2. Validate the Agent Card against the schema.
        try:
            validate_agent_card(request.agent_card)
        except Exception as exc:
            return {"ok": False, "reason": f"agent card validation failed: {exc}"}

        # 3-6. Check for duplicate, add card, add key, consume challenge.
        # H4 fix: hold self._lock for the entire mutation sequence so
        # registry.add_card and key_store.add_key are atomic.
        with self._lock:
            # 3. Check for duplicate (if already registered, reject).
            if agent_id in self._registry:
                return {"ok": False, "reason": f"agent {agent_id!r} is already registered"}

            # 4. Add the card to the runtime registry.
            self._registry.add_card(request.agent_card)

            # 5. Add the public key to the KeyStore.
            self._key_store.add_key(agent_id, request.public_key)

            # 6. Consume the challenge.
            self._challenges.pop(agent_id, None)

        return {"ok": True, "agent_id": agent_id, "reason": "registered successfully"}

    def unregister(self, agent_id: str) -> bool:
        """Remove an externally-registered agent.

        Returns ``True`` if the agent was found and removed.
        """
        removed = self._registry.remove_card(agent_id)
        self._key_store.remove_key(agent_id)
        return removed

    def _cleanup_expired(self, agent_id: str) -> None:
        """Remove expired challenges for ``agent_id`` (call under lock)."""
        challenge = self._challenges.get(agent_id)
        if challenge is not None and challenge.is_expired():
            self._challenges.pop(agent_id, None)

    def _cleanup_all_expired(self) -> None:
        """Remove ALL expired challenges across all agent_ids (call under lock).

        M4 fix: global cleanup pass to prevent unbounded memory growth.
        """
        now = time.time()
        expired_ids = [
            aid for aid, ch in self._challenges.items()
            if ch.is_expired(now)
        ]
        for aid in expired_ids:
            self._challenges.pop(aid, None)

    def clear(self) -> None:
        """Drop all pending challenges — used by tests."""
        with self._lock:
            self._challenges.clear()
