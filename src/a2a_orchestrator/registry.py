"""Registry: load and cache A2A Agent Cards from ``*.json`` files.

The registry is the read-only source of truth for routing decisions:

* :attr:`cards_by_id` — maps a2a-id (e.g. ``agent-backend``) to its card.
* :attr:`whitelist` — derived map of ``from_id -> set[allowed_to_id]``,
  built from each card's ``routing.accepts_routes_from``.

The class is intentionally small and synchronous. It is constructed once
at MCP server startup and read from many tool calls; no locking is
required because Python dicts are reference-stable per process.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .validation import validate_agent_card

# Default location of agent cards. Overridable for tests and for
# installations where the cards live elsewhere.
DEFAULT_CARDS_DIR = Path("a2a/agents")


class AgentCardRegistry:
    """In-memory registry of Agent Cards loaded from JSON files."""

    def __init__(self, cards_dir: Path | str = DEFAULT_CARDS_DIR) -> None:
        self._cards_dir = Path(cards_dir)
        self._cards: dict[str, dict[str, Any]] = {}
        # Forward index: who can call whom.
        # ``whitelist[from_id] = {to_id, ...}`` — set of A2A ids that ``from_id``
        # is allowed to call. We invert ``accepts_routes_from`` so a single
        # lookup per send_a2a is O(1) instead of O(N).
        self._whitelist: dict[str, set[str]] = {}

    @property
    def cards_dir(self) -> Path:
        return self._cards_dir

    @property
    def cards_by_id(self) -> dict[str, dict[str, Any]]:
        return dict(self._cards)

    def __len__(self) -> int:
        return len(self._cards)

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._cards

    def load(self) -> None:
        """(Re)load every ``*.json`` file in the cards directory.

        Raises:
            FileNotFoundError: if the directory does not exist.
            ValueError: if a card fails JSON-schema validation.
        """
        if not self._cards_dir.is_dir():
            raise FileNotFoundError(
                f"Agent Cards directory not found: {self._cards_dir}. "
                "Set the A2A_CARDS_DIR environment variable to the directory "
                "containing your Agent Card JSON files."
            )

        self._cards = {}
        self._whitelist = {}

        for path in sorted(self._cards_dir.glob("*.json")):
            try:
                card = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Agent Card at {path} is not valid JSON: {exc}"
                ) from exc

            validate_agent_card(card)
            agent_id = card["id"]

            if agent_id in self._cards:
                # Two cards sharing the same id is a generator bug; fail loudly.
                raise ValueError(
                    f"Duplicate Agent Card id {agent_id!r} in {self._cards_dir}"
                )

            self._cards[agent_id] = card

            # Invert accepts_routes_from: any agent that lists ``self`` in its
            # whitelist is allowed to call ``self``. Build the forward index
            # ``self -> {caller}`` for O(1) "is this caller allowed?" checks.
            for caller in card.get("routing", {}).get("accepts_routes_from", []):
                self._whitelist.setdefault(caller, set()).add(agent_id)

    def get(self, agent_id: str) -> dict[str, Any] | None:
        """Return the card for ``agent_id`` or ``None`` if unknown."""
        return self._cards.get(agent_id)

    def allowed_targets(self, from_id: str) -> set[str]:
        """Return the set of A2A ids ``from_id`` is allowed to call.

        Returns an empty set (not None) when ``from_id`` is unknown or
        has no outgoing edges — this is the safe default for R1 checks.
        """
        return set(self._whitelist.get(from_id, set()))

    def max_chain_depth(self, agent_id: str) -> int:
        """Return the per-agent override for the global max chain depth.

        Defaults to 3 (the protocol-wide limit) when a card has no
        ``max_chain_depth`` field set.
        """
        card = self._cards.get(agent_id)
        if card is None:
            return 3
        return int(card.get("max_chain_depth", 3))

    def add_card(self, card: dict[str, Any]) -> None:
        """Add or replace a card at runtime (external agent registration).

        Validates the card against the schema before adding. Does NOT
        write to disk — runtime cards are in-memory only and lost on
        restart unless persisted by the caller.
        """
        validate_agent_card(card)
        agent_id = card["id"]
        self._cards[agent_id] = card
        # Rebuild the whitelist entry for this card.
        for caller in card.get("routing", {}).get("accepts_routes_from", []):
            self._whitelist.setdefault(caller, set()).add(agent_id)

    def remove_card(self, agent_id: str) -> bool:
        """Remove a card from the runtime registry.

        Returns ``True`` if the card was present and removed, ``False``
        if it was not found. Does NOT delete the file on disk.
        """
        if agent_id not in self._cards:
            return False
        del self._cards[agent_id]
        # Clean up whitelist entries that pointed to this agent.
        for callers in self._whitelist.values():
            callers.discard(agent_id)
        return True

    def list_agents(self) -> list[dict[str, Any]]:
        """Return all loaded cards as a list (sorted by id).

        Used by the CLI ``agents`` command and the MCP tool.
        """
        return [self._cards[k] for k in sorted(self._cards)]
