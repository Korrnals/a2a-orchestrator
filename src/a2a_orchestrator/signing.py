"""Ed25519 signed messages — cryptographic auth between agents.

When agents are distributed (not all in the same trusted workspace),
messages need cryptographic verification. Each agent has an Ed25519
keypair. Messages are signed by the sender; the orchestrator verifies
the signature against the sender's public key (from their Agent Card
or a runtime KeyStore).

Backward compatibility: if the sender's Agent Card has no
``public_key`` field, signature verification is skipped entirely
(trust-by-construction, as before).

Canonical JSON
--------------
Signing requires a deterministic byte representation. We use
``canonical_json``: sorted keys, no whitespace, no non-ASCII escapes
(``ensure_ascii=False`` so UTF-8 bytes are stable across platforms).
"""
from __future__ import annotations

import base64
import json
import threading
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def canonical_json(data: dict[str, Any]) -> str:
    """Return deterministic JSON for signing.

    Sorted keys, no extra whitespace, non-ASCII preserved as UTF-8.
    This ensures the same dict always produces the same signature
    regardless of insertion order or platform.

    .. warning::
       ``ensure_ascii=False`` means non-ASCII characters (e.g. Cyrillic,
       CJK, emoji) are encoded as raw UTF-8 bytes, not ``\\uXXXX``
       escapes. This is **required** for cross-platform signature
       stability: different JSON libraries escape non-ASCII differently,
       but UTF-8 bytes are identical everywhere. Both the signer and
       verifier must use the same ``canonical_json`` function (L5).
    """
    return json.dumps(data, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _b64encode(data: bytes) -> str:
    """Base64-encode bytes to a str (standard alphabet, no newlines)."""
    return base64.b64encode(data).decode("ascii")


def _b64decode(data: str) -> bytes:
    """Base64-decode a str to bytes."""
    return base64.b64decode(data.encode("ascii"))


@dataclass
class KeyPair:
    """An Ed25519 keypair for an agent.

    Attributes:
        agent_id: The A2A id this keypair belongs to.
        private_key: Ed25519 private key (for signing).
        public_key: Ed25519 public key (for verification).
    """

    agent_id: str
    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey

    @property
    def public_key_b64(self) -> str:
        """Return the public key as a base64 string (for Agent Cards)."""
        raw = self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return _b64encode(raw)

    @property
    def private_key_b64(self) -> str:
        """Return the private key as a base64 string (for storage)."""
        raw = self.private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return _b64encode(raw)


def generate_keypair(agent_id: str) -> KeyPair:
    """Generate a new Ed25519 keypair for ``agent_id``."""
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    return KeyPair(agent_id=agent_id, private_key=private, public_key=public)


def load_public_key(public_key_b64: str) -> Ed25519PublicKey:
    """Load an Ed25519 public key from a base64 string."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey as _Ed25519PublicKey,
    )

    raw = _b64decode(public_key_b64)
    return _Ed25519PublicKey.from_public_bytes(raw)


def load_private_key(private_key_b64: str) -> Ed25519PrivateKey:
    """Load an Ed25519 private key from a base64 string."""
    raw = _b64decode(private_key_b64)
    return Ed25519PrivateKey.from_private_bytes(raw)


def sign_message(message: dict[str, Any], private_key: Ed25519PrivateKey) -> str:
    """Sign the canonical JSON of ``message`` and return base64 signature.

    The ``signature`` field itself is excluded from the signed payload
    (it can't sign itself). All other fields are included.
    """
    # Remove signature field if present — it's not part of the signed data.
    msg_copy = {k: v for k, v in message.items() if k != "signature"}
    payload = canonical_json(msg_copy).encode("utf-8")
    sig = private_key.sign(payload)
    return _b64encode(sig)


def verify_message(
    message: dict[str, Any],
    signature: str,
    public_key: Ed25519PublicKey,
) -> bool:
    """Verify a signature against the canonical JSON of ``message``.

    Returns ``True`` if the signature is valid, ``False`` otherwise.

    Only :class:`InvalidSignature` and :class:`ValueError` are caught
    and treated as a normal ``False`` result (H2 fix). Other exceptions
    (``TypeError``, ``KeyError``, etc.) propagate — they indicate a
    programming error, not a bad signature.
    """
    msg_copy = {k: v for k, v in message.items() if k != "signature"}
    payload = canonical_json(msg_copy).encode("utf-8")
    try:
        public_key.verify(_b64decode(signature), payload)
        return True
    except (InvalidSignature, ValueError):
        # H2 fix: only catch InvalidSignature (bad signature) and
        # ValueError (bad base64). Let TypeError/KeyError propagate.
        return False


class KeyStore:
    """Thread-safe store of agent public keys for verification.

    Keys are loaded from Agent Cards (``public_key`` field) or added
    at runtime via :meth:`add_key` (used by external agent registration).
    """

    def __init__(self) -> None:
        self._keys: dict[str, Ed25519PublicKey] = {}
        self._lock = threading.Lock()

    def add_key(self, agent_id: str, public_key_b64: str) -> None:
        """Add or replace a public key for ``agent_id``."""
        with self._lock:
            self._keys[agent_id] = load_public_key(public_key_b64)

    def get_key(self, agent_id: str) -> Ed25519PublicKey | None:
        """Return the public key for ``agent_id``, or ``None``."""
        with self._lock:
            return self._keys.get(agent_id)

    def remove_key(self, agent_id: str) -> bool:
        """Remove the key for ``agent_id``. Returns ``True`` if it existed."""
        with self._lock:
            return self._keys.pop(agent_id, None) is not None

    def has_key(self, agent_id: str) -> bool:
        """Return ``True`` if a public key is registered for ``agent_id``."""
        with self._lock:
            return agent_id in self._keys

    def load_from_registry(self, registry: Any) -> None:
        """Load public keys from an ``AgentCardRegistry``.

        Scans every card for a ``public_key`` field and registers it.
        Cards without ``public_key`` are skipped (trust-by-construction).
        """
        with self._lock:
            for card in registry.list_agents():
                pk = card.get("public_key")
                if pk:
                    self._keys[card["id"]] = load_public_key(pk)

    def __len__(self) -> int:
        with self._lock:
            return len(self._keys)

    def clear(self) -> None:
        """Drop all keys — used by tests."""
        with self._lock:
            self._keys.clear()
