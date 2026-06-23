"""Unit tests for Ed25519 signed messages (a2a_orchestrator.signing)."""
from __future__ import annotations

import copy

from a2a_orchestrator.signing import (
    KeyStore,
    canonical_json,
    generate_keypair,
    load_public_key,
    sign_message,
    verify_message,
)


class TestCanonicalJson:
    def test_sorted_keys(self):
        data = {"b": 2, "a": 1, "c": 3}
        result = canonical_json(data)
        assert result == '{"a":1,"b":2,"c":3}'

    def test_no_whitespace(self):
        data = {"key": "value"}
        result = canonical_json(data)
        assert " " not in result

    def test_deterministic(self):
        data1 = {"b": 2, "a": 1}
        data2 = {"a": 1, "b": 2}
        assert canonical_json(data1) == canonical_json(data2)

    def test_unicode_preserved(self):
        data = {"msg": "héllo"}
        result = canonical_json(data)
        assert "héllo" in result


class TestKeypairGeneration:
    def test_generate_keypair(self):
        kp = generate_keypair("agent-test")
        assert kp.agent_id == "agent-test"
        assert kp.private_key is not None
        assert kp.public_key is not None

    def test_public_key_b64_roundtrip(self):
        kp = generate_keypair("agent-test")
        b64 = kp.public_key_b64
        restored = load_public_key(b64)
        # Verify that the restored key can verify a signature.
        msg = {"test": "data"}
        sig = sign_message(msg, kp.private_key)
        assert verify_message(msg, sig, restored) is True


class TestSignVerify:
    def test_sign_and_verify(self):
        kp = generate_keypair("agent-test")
        msg = {"from": "agent-a", "to": "agent-b", "reason": "test message"}
        sig = sign_message(msg, kp.private_key)
        assert verify_message(msg, sig, kp.public_key) is True

    def test_tampered_message_fails(self):
        kp = generate_keypair("agent-test")
        msg = {"from": "agent-a", "to": "agent-b", "reason": "original"}
        sig = sign_message(msg, kp.private_key)
        tampered = copy.deepcopy(msg)
        tampered["reason"] = "tampered"
        assert verify_message(tampered, sig, kp.public_key) is False

    def test_wrong_key_fails(self):
        kp1 = generate_keypair("agent-a")
        kp2 = generate_keypair("agent-b")
        msg = {"test": "data"}
        sig = sign_message(msg, kp1.private_key)
        assert verify_message(msg, sig, kp2.public_key) is False

    def test_signature_excluded_from_signed_data(self):
        """The signature field itself must not be part of the signed data."""
        kp = generate_keypair("agent-test")
        msg = {"from": "agent-a", "signature": "old-sig", "data": "test"}
        sig = sign_message(msg, kp.private_key)
        # Verify with the signature field present — it should still verify
        # because the signature field is excluded from the signed payload.
        msg_with_sig = {**msg, "signature": sig}
        assert verify_message(msg_with_sig, sig, kp.public_key) is True


class TestKeyStore:
    def test_add_and_get_key(self):
        store = KeyStore()
        kp = generate_keypair("agent-a")
        store.add_key("agent-a", kp.public_key_b64)
        assert store.has_key("agent-a") is True
        pk = store.get_key("agent-a")
        assert pk is not None

    def test_remove_key(self):
        store = KeyStore()
        kp = generate_keypair("agent-a")
        store.add_key("agent-a", kp.public_key_b64)
        assert store.remove_key("agent-a") is True
        assert store.has_key("agent-a") is False
        assert store.remove_key("agent-a") is False  # already removed

    def test_has_key_false_for_unknown(self):
        store = KeyStore()
        assert store.has_key("agent-unknown") is False

    def test_load_from_registry(self, cards_dir):
        # Add a card with a public_key to the cards dir.
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
        store = KeyStore()
        store.load_from_registry(reg)
        assert store.has_key("agent-signed") is True
