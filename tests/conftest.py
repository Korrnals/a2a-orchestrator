"""Shared pytest fixtures for a2a-orchestrator tests.

The fixtures here isolate the tests from the real repo layout by
pointing ``A2A_SCHEMA_DIR`` / ``A2A_CARDS_DIR`` at temp directories with
minimal valid schemas and cards. This makes tests hermetic — they do
not depend on any external repo being checked out.

The schemas use universal patterns (``^[a-z][a-z0-9-]*$``) so they work
with any kebab-case agent id, not just GCW-prefixed ones.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# --------------------------------------------------------------------------- #
# Minimal schemas (mirrors a2a_orchestrator/schemas/*.schema.json but trimmed)
# --------------------------------------------------------------------------- #

AGENT_CARD_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "A2A Agent Card",
    "type": "object",
    "required": ["id", "name", "version", "plugin", "agent_file",
                 "capabilities", "routing"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
        "name": {"type": "string"},
        "version": {"type": "string",
                    "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+(-[a-z0-9.-]+)?$"},
        "plugin": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
        # L4 fix: pattern must match the embedded schema (allows directory
        # prefix, e.g. "gcw-it-team/senior-dba.agent.md").
        "agent_file": {"type": "string",
                       "pattern": r"^([a-z][a-z0-9-]*/)*[a-z][a-z0-9-]*\.agent\.md$"},
        "description": {"type": "string"},
        "model_tier": {"type": "string"},
        "tool_profile": {"type": "string"},
        "capabilities": {
            "type": "array", "minItems": 1,
            "items": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
        },
        "routing": {
            "type": "object",
            "required": ["accepts_routes_from", "routing_keywords"],
            "additionalProperties": False,
            "properties": {
                "accepts_routes_from": {
                    "type": "array",
                    "items": {"type": "string",
                              "pattern": "^[a-z][a-z0-9-]*$"},
                },
                "routing_keywords": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
            },
        },
        "tags": {"type": "array", "items": {"type": "string"}},
        "max_chain_depth": {"type": "integer", "minimum": 0, "maximum": 5},
        "public_key": {"type": "string"},
        "tenant_id": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
    },
}

A2A_MESSAGE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "A2A Message",
    "type": "object",
    "required": ["schema_version", "message_id", "session_id", "from", "to",
                 "intent", "payload", "routing_meta"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "string", "const": "0.7.0"},
        "message_id": {"type": "string", "pattern": "^msg-[a-z0-9-]{8,}$"},
        "session_id": {"type": "string"},
        "from": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
        "signature": {"type": "string"},
        "tenant_id": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
        "to": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
        "intent": {
            "type": "string",
            "enum": ["handoff", "request-info", "share-finding",
                     "request-review", "request-implementation",
                     "request-documentation", "destructive-action-request"],
        },
        "reason": {"type": "string", "minLength": 10, "maxLength": 500},
        "payload": {
            "type": "object",
            "required": ["summary"],
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string", "minLength": 20, "maxLength": 2000},
                "key_decisions": {"type": "array", "items": {"type": "string"}},
                "open_questions": {"type": "array", "items": {"type": "string"}},
                "artifacts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["kind", "pointer"],
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": ["file", "diff", "test-result",
                                         "metric", "log", "memory-turn"],
                            },
                            "pointer": {"type": "string"},
                        },
                    },
                },
            },
        },
        "routing_meta": {
            "type": "object",
            "required": ["chain", "depth", "calls_remaining"],
            "additionalProperties": False,
            "properties": {
                "chain": {
                    "type": "array",
                    "items": {"type": "string",
                              "pattern": "^[a-z][a-z0-9-]*$"},
                },
                "depth": {"type": "integer", "minimum": 0, "maximum": 5},
                "calls_remaining": {"type": "integer", "minimum": 0, "maximum": 10},
                "parent_message_id": {"type": ["string", "null"]},
                "saga_id": {"type": "string"},
            },
        },
    },
}


def _make_card(
    agent_id: str,
    *,
    accepts_from: list[str] | None = None,
    max_chain_depth: int | None = None,
) -> dict[str, Any]:
    """Build a minimal valid Agent Card for tests."""
    card: dict[str, Any] = {
        "id": agent_id,
        "name": f"Agent: {agent_id.replace('-', ' ').title()}",
        "version": "0.6.0",
        "plugin": "test-plugin",
        "agent_file": f"{agent_id}.agent.md",
        "description": f"Test agent {agent_id}",
        "capabilities": ["test-cap"],
        "routing": {
            "accepts_routes_from": accepts_from or [],
            "routing_keywords": ["test"],
        },
        "tags": [],
    }
    if max_chain_depth is not None:
        card["max_chain_depth"] = max_chain_depth
    return card


@pytest.fixture()
def schemas_dir(tmp_path: Path) -> Path:
    """Create a temp dir with both schema files and return its path."""
    d = tmp_path / "schemas"
    d.mkdir()
    (d / "agent-card.schema.json").write_text(
        json.dumps(AGENT_CARD_SCHEMA), encoding="utf-8")
    (d / "a2a-message.schema.json").write_text(
        json.dumps(A2A_MESSAGE_SCHEMA), encoding="utf-8")
    return d


@pytest.fixture()
def cards_dir(tmp_path: Path) -> Path:
    """Create a temp dir with a few test Agent Cards and return its path."""
    d = tmp_path / "agents"
    d.mkdir()
    # Build a cycle: A→B→C→A.
    # accepts_routes_from is on the RECEIVER's card: B accepts from A,
    # C accepts from B, A accepts from C.
    for agent_id, accepts in [
        ("agent-a", ["agent-c"]),  # A accepts routes from C
        ("agent-b", ["agent-a"]),  # B accepts routes from A
        ("agent-c", ["agent-b"]),  # C accepts routes from B
        # A card with a per-card max_chain_depth override of 1.
        # agent-shallow accepts routes from A (so A can call shallow).
        ("agent-shallow", ["agent-a"]),
    ]:
        card = _make_card(agent_id, accepts_from=accepts)
        if agent_id == "agent-shallow":
            card["max_chain_depth"] = 1
        (d / f"{agent_id}.json").write_text(
            json.dumps(card), encoding="utf-8")
    return d


@pytest.fixture()
def reg_service(cards_dir):
    """Create a RegistrationService with a loaded registry.

    Shared fixture so both test_registration.py and test_security_fixes.py
    can use it without duplicating the setup.
    """
    from a2a_orchestrator.registration import RegistrationService
    from a2a_orchestrator.registry import AgentCardRegistry
    from a2a_orchestrator.signing import KeyStore
    reg = AgentCardRegistry(cards_dir=cards_dir)
    reg.load()
    store = KeyStore()
    return RegistrationService(registry=reg, key_store=store)


@pytest.fixture()
def env_isolated(schemas_dir: Path, cards_dir: Path,
                  monkeypatch: pytest.MonkeyPatch) -> None:
    """Set env vars so config resolves to the temp schemas/cards dirs.

    Also clears any pre-existing module-level config caches by removing
    the already-imported ``a2a_orchestrator.config`` module so it re-resolves
    on next import.
    """
    monkeypatch.setenv("A2A_SCHEMA_DIR", str(schemas_dir))
    monkeypatch.setenv("A2A_CARDS_DIR", str(cards_dir))
    # Force re-import of config + validation (they cache at import time).
    for mod in list(sys.modules):
        if mod.startswith("a2a_orchestrator"):
            monkeypatch.delitem(sys.modules, mod, raising=False)


@pytest.fixture()
def valid_message() -> dict[str, Any]:
    """Return a minimal valid A2A message dict."""
    return {
        "schema_version": "0.7.0",
        "message_id": "msg-test00000001",
        "session_id": "conv-test-001",
        "from": "agent-a",
        "to": "agent-b",
        "intent": "handoff",
        "reason": "Need DBA help with schema.",
        "payload": {
            "summary": "User wants to add a column to the orders table.",
            "key_decisions": ["Add nullable column"],
            "open_questions": ["Index it?"],
            "artifacts": [{"kind": "file", "pointer": "src/models.py"}],
        },
        "routing_meta": {
            "chain": ["agent-a"],
            "depth": 0,
            "calls_remaining": 3,
            "parent_message_id": None,
        },
    }
