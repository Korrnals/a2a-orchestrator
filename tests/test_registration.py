"""Unit tests for external agent registration (a2a_orchestrator.registration)."""
from __future__ import annotations

import time

from a2a_orchestrator.registration import RegistrationRequest
from a2a_orchestrator.signing import generate_keypair, sign_message


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


# Note: reg_service fixture is now defined in conftest.py (shared with
# test_security_fixes.py).


class TestCreateChallenge:
    def test_create_challenge_returns_nonce(self, reg_service):
        nonce = reg_service.create_challenge("agent-new")
        assert nonce.startswith("challenge-")
        assert len(nonce) > 10

    def test_challenge_overwrites_previous(self, reg_service):
        n1 = reg_service.create_challenge("agent-new")
        n2 = reg_service.create_challenge("agent-new")
        assert n1 != n2


class TestFullRegistrationFlow:
    def test_full_flow_register_and_verify(self, reg_service):
        """Challenge → sign → register → agent in registry → send works."""
        agent_id = "agent-external-1"
        kp = generate_keypair(agent_id)
        card = _make_card(agent_id, accepts_from=["agent-a"])

        # Step 1: create challenge.
        nonce = reg_service.create_challenge(agent_id)

        # Step 2: sign the challenge.
        signed_payload = {"nonce": nonce, "agent_id": agent_id}
        sig = sign_message(signed_payload, kp.private_key)

        # Step 3: register.
        request = RegistrationRequest(
            agent_card=card,
            public_key=kp.public_key_b64,
            challenge_signature=sig,
        )
        result = reg_service.register(request)
        assert result["ok"] is True
        assert result["agent_id"] == agent_id

        # Verify the agent is in the registry.
        assert agent_id in reg_service._registry
        # Verify the key is in the key store.
        assert reg_service._key_store.has_key(agent_id)

    def test_invalid_signature_rejected(self, reg_service):
        """Registration with a wrong signature is rejected."""
        agent_id = "agent-external-2"
        kp = generate_keypair(agent_id)
        card = _make_card(agent_id)

        reg_service.create_challenge(agent_id)

        # Sign with a DIFFERENT key.
        wrong_kp = generate_keypair("agent-wrong")
        signed_payload = {"nonce": "challenge-wrong", "agent_id": agent_id}
        sig = sign_message(signed_payload, wrong_kp.private_key)

        request = RegistrationRequest(
            agent_card=card,
            public_key=kp.public_key_b64,
            challenge_signature=sig,
        )
        result = reg_service.register(request)
        assert result["ok"] is False
        assert "verification failed" in result["reason"]

    def test_expired_challenge_rejected(self, reg_service):
        """An expired challenge is rejected."""
        agent_id = "agent-external-3"
        kp = generate_keypair(agent_id)
        card = _make_card(agent_id)

        nonce = reg_service.create_challenge(agent_id)

        # Manually expire the challenge by backdating it.
        with reg_service._lock:
            challenge = reg_service._challenges.get(agent_id)
            if challenge:
                challenge.expires_at = time.time() - 1

        signed_payload = {"nonce": nonce, "agent_id": agent_id}
        sig = sign_message(signed_payload, kp.private_key)

        request = RegistrationRequest(
            agent_card=card,
            public_key=kp.public_key_b64,
            challenge_signature=sig,
        )
        result = reg_service.register(request)
        assert result["ok"] is False

    def test_duplicate_agent_id_rejected(self, reg_service):
        """Registering an already-registered agent is rejected."""
        agent_id = "agent-a"  # already in the test cards
        kp = generate_keypair(agent_id)
        card = _make_card(agent_id, accepts_from=["agent-c"])

        nonce = reg_service.create_challenge(agent_id)
        signed_payload = {"nonce": nonce, "agent_id": agent_id}
        sig = sign_message(signed_payload, kp.private_key)

        request = RegistrationRequest(
            agent_card=card,
            public_key=kp.public_key_b64,
            challenge_signature=sig,
        )
        result = reg_service.register(request)
        assert result["ok"] is False
        assert "already registered" in result["reason"]


class TestUnregister:
    def test_unregister_removes_agent(self, reg_service):
        """After unregister, the agent is no longer in the registry."""
        agent_id = "agent-external-4"
        kp = generate_keypair(agent_id)
        card = _make_card(agent_id, accepts_from=["agent-a"])

        nonce = reg_service.create_challenge(agent_id)
        signed_payload = {"nonce": nonce, "agent_id": agent_id}
        sig = sign_message(signed_payload, kp.private_key)

        reg_service.register(RegistrationRequest(
            agent_card=card,
            public_key=kp.public_key_b64,
            challenge_signature=sig,
        ))

        # Unregister.
        removed = reg_service.unregister(agent_id)
        assert removed is True
        assert agent_id not in reg_service._registry
        assert not reg_service._key_store.has_key(agent_id)

    def test_unregister_nonexistent(self, reg_service):
        """Unregistering an unknown agent returns False."""
        assert reg_service.unregister("agent-nonexistent") is False


class TestVerifyRegistration:
    def test_verify_without_committing(self, reg_service):
        """verify_registration checks the signature without modifying the registry."""
        agent_id = "agent-external-5"
        kp = generate_keypair(agent_id)
        card = _make_card(agent_id)

        nonce = reg_service.create_challenge(agent_id)
        signed_payload = {"nonce": nonce, "agent_id": agent_id}
        sig = sign_message(signed_payload, kp.private_key)

        request = RegistrationRequest(
            agent_card=card,
            public_key=kp.public_key_b64,
            challenge_signature=sig,
        )
        assert reg_service.verify_registration(request) is True
        # Agent should NOT be in the registry yet.
        assert agent_id not in reg_service._registry
