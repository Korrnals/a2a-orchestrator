"""Runtime configuration for the ``a2a-orchestrator`` MCP server.

The package is **universal** — it does not depend on any external repo
checkout. Schemas are embedded in the package itself
(``a2a_orchestrator/schemas/``). Agent Cards are loaded from a
configurable directory (env var or auto-detected).

Override behaviour via environment variables:

* ``A2A_SCHEMA_DIR`` — absolute path to the directory containing
  ``agent-card.schema.json`` and ``a2a-message.schema.json``.
  (Backward compat: ``GCW_SCHEMA_DIR`` is checked as a fallback.)
* ``A2A_CARDS_DIR`` — directory of Agent Card JSON files.
  (Backward compat: ``GCW_CARDS_DIR`` is checked as a fallback.)
* ``A2A_FALLBACK_JSONL`` — path to the JSONL fallback file.
  (Backward compat: ``GCW_A2A_FALLBACK_JSONL`` is checked as a
  fallback.)

Search order for schemas:

1. ``$A2A_SCHEMA_DIR`` (or ``$GCW_SCHEMA_DIR`` for backward compat).
2. Embedded schemas in ``a2a_orchestrator/schemas/`` (default).
3. ``docs/a2a/schemas`` under any parent of the package directory (last
   resort — for in-tree development checkouts).

Search order for cards:

1. ``$A2A_CARDS_DIR`` (or ``$GCW_CARDS_DIR`` for backward compat).
2. ``a2a/agents`` under any parent of the package directory (last
   resort — for in-tree development checkouts).
"""
from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

# Environment-variable knobs. ``None`` means "auto-detect".
# New names (A2A_*) are primary; old names (GCW_*) are backward-compat fallbacks.
ENV_SCHEMA_DIR = "A2A_SCHEMA_DIR"
ENV_SCHEMA_DIR_LEGACY = "GCW_SCHEMA_DIR"
ENV_CARDS_DIR = "A2A_CARDS_DIR"
ENV_CARDS_DIR_LEGACY = "GCW_CARDS_DIR"
ENV_FALLBACK_JSONL = "A2A_FALLBACK_JSONL"
ENV_FALLBACK_JSONL_LEGACY = "GCW_A2A_FALLBACK_JSONL"


def _env_or_legacy(primary: str, legacy: str) -> str | None:
    """Return the primary env var, falling back to the legacy name.

    Checks ``primary`` first; if unset, checks ``legacy``. This provides
    backward compatibility for users who still have the old ``GCW_*``
    env vars set.
    """
    val = os.environ.get(primary)
    if val:
        return val
    return os.environ.get(legacy)


def _candidate_roots(start: Path) -> Iterable[Path]:
    """Yield plausible repo roots by walking up from ``start``.

    The package sits 1-3 levels under the repo root depending on the
    layout. We walk up to 6 levels to cover nested checkouts.
    """
    p = start.resolve()
    for _ in range(6):
        yield p
        p = p.parent


def _find_schema_dir(start: Path) -> Path:
    """Locate the directory that contains the two A2A JSON schemas.

    Search order:

    1. ``$A2A_SCHEMA_DIR`` (or ``$GCW_SCHEMA_DIR``) if set.
    2. Embedded schemas: ``<package_dir>/schemas/``.
    3. ``docs/a2a/schemas`` under any parent of ``start`` (last resort).
    """
    override = _env_or_legacy(ENV_SCHEMA_DIR, ENV_SCHEMA_DIR_LEGACY)
    if override:
        return Path(override)

    # Primary: embedded schemas shipped with the package.
    embedded = start / "schemas"
    if (embedded / "agent-card.schema.json").is_file() and (
        embedded / "a2a-message.schema.json"
    ).is_file():
        return embedded

    # Last resort: walk up looking for docs/a2a/schemas (in-tree dev).
    here = start.resolve()
    for root in _candidate_roots(here):
        candidate = root / "docs" / "a2a" / "schemas"
        if (candidate / "agent-card.schema.json").is_file() and (
            candidate / "a2a-message.schema.json"
        ).is_file():
            return candidate

    raise FileNotFoundError(
        "Could not locate A2A JSON schemas. "
        f"Set the {ENV_SCHEMA_DIR} environment variable to the directory that "
        "contains agent-card.schema.json and a2a-message.schema.json, "
        f"or ensure the embedded schemas exist at {embedded}."
    )


def _find_cards_dir(start: Path) -> Path:
    """Locate the Agent Cards directory.

    Search order:

    1. ``$A2A_CARDS_DIR`` (or ``$GCW_CARDS_DIR``) if set.
    2. ``a2a/agents`` under any parent of ``start`` (last resort).
    """
    override = _env_or_legacy(ENV_CARDS_DIR, ENV_CARDS_DIR_LEGACY)
    if override:
        return Path(override)

    # Last resort: walk up looking for a2a/agents (in-tree dev).
    here = start.resolve()
    for root in _candidate_roots(here):
        candidate = root / "a2a" / "agents"
        if candidate.is_dir():
            return candidate

    # Fallback (will fail at registry.load with a clear message).
    return here / "a2a" / "agents"


def _default_fallback_path() -> Path:
    """Return the default JSONL fallback location for in-memory state.

    Per spec: ``~/.a2a/a2a-messages.jsonl``. Created lazily on first
    write; the parent directory is NOT auto-created to avoid surprising
    the user — let them opt in by setting the env var if they want a
    non-default path.
    """
    override = _env_or_legacy(ENV_FALLBACK_JSONL, ENV_FALLBACK_JSONL_LEGACY)
    if override:
        return Path(override)
    return Path.home() / ".a2a" / "a2a-messages.jsonl"


# Resolved at import time. Tests may monkey-patch these via
# ``monkeypatch.setenv(A2A_SCHEMA_DIR, ...)`` before reloading modules.
_PACKAGE_DIR = Path(__file__).resolve().parent
SCHEMA_DIR: Path = _find_schema_dir(_PACKAGE_DIR)
CARDS_DIR: Path = _find_cards_dir(_PACKAGE_DIR)
FALLBACK_JSONL_PATH: Path = _default_fallback_path()

# Convenience: absolute paths to the two schemas that the wire format
# depends on. These are derived from ``SCHEMA_DIR`` and re-exported so
# :mod:`.validation` can pull them in without re-implementing the search.
AGENT_CARD_SCHEMA_PATH: Path = SCHEMA_DIR / "agent-card.schema.json"
A2A_MESSAGE_SCHEMA_PATH: Path = SCHEMA_DIR / "a2a-message.schema.json"
