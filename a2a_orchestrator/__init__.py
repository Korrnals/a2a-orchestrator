"""A2A orchestrator (MCP server).

This package implements the MCP server described in the A2A protocol
spec. It exposes MCP tools for routing messages between agents,
performing the 5 routing checks (R1-R5) defined by the protocol, and
persisting each message to either Mnemos (REST) or a local JSONL
fallback file.

The package is **universal** — it works with any kebab-case agent id,
not just GCW-prefixed ones. Agent Cards and schemas are embedded in
the package itself, so no external repo checkout is required.

Module layout:

* :mod:`a2a_orchestrator.validation` — JSON-schema validators for
  Agent Cards and A2A messages.
* :mod:`a2a_orchestrator.registry` — Loads and caches Agent Card JSON
  files from a configurable directory.
* :mod:`a2a_orchestrator.session` — Per-conversation chain/depth/budget
  state.
* :mod:`a2a_orchestrator.routing` — R1 (whitelist), R2 (loop), R3
  (depth), R4 (budget) gates.
* :mod:`a2a_orchestrator.destructive` — R5 (destructive-action user
  consent).
* :mod:`a2a_orchestrator.persistence` — In-memory + JSONL store for
  messages.
* :mod:`a2a_orchestrator.mnemos_client` — REST client for Mnemos with
  retry/backoff.
* :mod:`a2a_orchestrator.metrics` — Thread-safe counters for
  observability.
* :mod:`a2a_orchestrator.server` — FastMCP entry point and MCP tools.
* :mod:`a2a_orchestrator.cli` — CLI wrapper (send/list/status/agents/
  serve).

Wire-format version: 0.7.0 (see ``schemas/a2a-message.schema.json``).
"""
from __future__ import annotations

__all__ = [
    "A2A_SCHEMA_VERSION",
]

# Wire-format version pinned to a2a-message.schema.json. Bump on breaking change.
A2A_SCHEMA_VERSION = "0.7.0"
