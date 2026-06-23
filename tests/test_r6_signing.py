"""Unit tests for R6 signature verification in routing (a2a_orchestrator.routing)."""
from __future__ import annotations

from a2a_orchestrator.routing import R6_SIGNATURE_INVALID, check_signature
from a2a_orchestrator.signing import KeyStore, generate_keypair, sign_message


class TestR6SignatureCheck:
    def test_no_public_key_skips_verification(self, cards_dir):
        """When the sender has no public_key in their card, R6 is skipped."""
        from a2a_orchestrator.registry import AgentCardRegistry

        reg = AgentCardRegistry(cards_dir=cards_dir)
        reg.load()
        # agent-a has no public_key in its card.
        msg = {"from": "agent-a", "to": "agent-b", "reason": "test message here"}
        rej = check_signature("agent-a", msg, "", reg, key_store=None)
        assert rej is None  # No rejection — verification skipped.

    def test_valid_signature_passes(self, cards_dir):
        """When the sender has a public_key and provides a valid signature, R6 passes."""
        import json

        from a2a_orchestrator.registry import AgentCardRegistry

        kp = generate_keypair("agent-signed")
        card = {
            "id": "agent-signed",
            "name": "Signed Agent",
            "version": "0.7.0",
            "plugin": "test-plugin",
            "agent_file": "agent-signed.agent.md",
            "capabilities": ["test"],
            "routing": {"accepts_routes_from": ["agent-a"], "routing_keywords": ["test"]},
            "public_key": kp.public_key_b64,
        }
        (cards_dir / "agent-signed.json").write_text(json.dumps(card))

        reg = AgentCardRegistry(cards_dir=cards_dir)
        reg.load()

        msg = {"from": "agent-signed", "to": "agent-b", "reason": "test message here"}
        sig = sign_message(msg, kp.private_key)
        rej = check_signature("agent-signed", msg, sig, reg, key_store=None)
        assert rej is None

    def test_missing_signature_rejected_when_key_present(self, cards_dir):
        """When the sender has a public_key but no signature, R6 rejects."""
        import json

        from a2a_orchestrator.registry import AgentCardRegistry

        kp = generate_keypair("agent-signed")
        card = {
            "id": "agent-signed",
            "name": "Signed Agent",
            "version": "0.7.0",
            "plugin": "test-plugin",
            "agent_file": "agent-signed.agent.md",
            "capabilities": ["test"],
            "routing": {"accepts_routes_from": ["agent-a"], "routing_keywords": ["test"]},
            "public_key": kp.public_key_b64,
        }
        (cards_dir / "agent-signed.json").write_text(json.dumps(card))

        reg = AgentCardRegistry(cards_dir=cards_dir)
        reg.load()

        msg = {"from": "agent-signed", "to": "agent-b", "reason": "test message here"}
        rej = check_signature("agent-signed", msg, "", reg, key_store=None)
        assert rej is not None
        assert rej.code == R6_SIGNATURE_INVALID

    def test_invalid_signature_rejected(self, cards_dir):
        """When the signature is wrong, R6 rejects."""
        import json

        from a2a_orchestrator.registry import AgentCardRegistry

        kp = generate_keypair("agent-signed")
        card = {
            "id": "agent-signed",
            "name": "Signed Agent",
            "version": "0.7.0",
            "plugin": "test-plugin",
            "agent_file": "agent-signed.agent.md",
            "capabilities": ["test"],
            "routing": {"accepts_routes_from": ["agent-a"], "routing_keywords": ["test"]},
            "public_key": kp.public_key_b64,
        }
        (cards_dir / "agent-signed.json").write_text(json.dumps(card))

        reg = AgentCardRegistry(cards_dir=cards_dir)
        reg.load()

        msg = {"from": "agent-signed", "to": "agent-b", "reason": "test message here"}
        rej = check_signature("agent-signed", msg, "invalid-signature", reg, key_store=None)
        assert rej is not None
        assert rej.code == R6_SIGNATURE_INVALID

    def test_key_store_verification(self, cards_dir):
        """R6 can verify via the runtime KeyStore (for registered agents)."""
        from a2a_orchestrator.registry import AgentCardRegistry

        reg = AgentCardRegistry(cards_dir=cards_dir)
        reg.load()

        kp = generate_keypair("agent-external")
        store = KeyStore()
        store.add_key("agent-external", kp.public_key_b64)

        msg = {"from": "agent-external", "to": "agent-b", "reason": "test message here"}
        sig = sign_message(msg, kp.private_key)
        rej = check_signature("agent-external", msg, sig, reg, key_store=store)
        assert rej is None

    def test_key_store_missing_signature_rejected(self, cards_dir):
        """KeyStore has the key but no signature → R6 rejects."""
        from a2a_orchestrator.registry import AgentCardRegistry

        reg = AgentCardRegistry(cards_dir=cards_dir)
        reg.load()

        kp = generate_keypair("agent-external")
        store = KeyStore()
        store.add_key("agent-external", kp.public_key_b64)

        msg = {"from": "agent-external", "to": "agent-b", "reason": "test message here"}
        rej = check_signature("agent-external", msg, "", reg, key_store=store)
        assert rej is not None
        assert rej.code == R6_SIGNATURE_INVALID
