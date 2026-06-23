"""Per-conversation state for A2A chains.

The MCP server runs many conversations in parallel (one per VS Code
chat, typically). Each conversation has its own chain/depth/budget
counters and a per-message log. The :class:`SessionState` class is the
authoritative source for R2/R3/R4 checks; the :class:`SessionStore`
manages a ``session_id -> SessionState`` map with an eviction policy
to keep memory bounded.

Wire-format constants (``MAX_CHAIN_DEPTH`` and ``MAX_BUDGET``) are pinned
to the protocol spec. ``max_chain_depth`` may be tightened per-target
by the Agent Card's ``max_chain_depth`` field — see
:meth:`AgentCardRegistry.max_chain_depth` — but the global ceiling
``MAX_CHAIN_DEPTH`` is never exceeded.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

# Protocol-wide limits from the A2A protocol spec §5.
# These are hard caps; per-target cards may set ``max_chain_depth`` lower
# (e.g. 1 for "should never be deep in a chain") but never higher.
MAX_CHAIN_DEPTH = 3
MAX_BUDGET = 3  # = MAX_CHAIN_DEPTH; both bound chain length.


@dataclass
class SessionState:
    """Mutable per-conversation state.

    Attributes:
        session_id: Mnemos session id; opaque to the MCP server.
        chain: Ordered list of A2A ids in the chain so far (sender included).
            The next hop's depth is ``len(chain)``. The first A2A call from
            a user prompt starts with ``chain = [<sender>]`` (depth 0).
        budget_used: Number of A2A messages already sent in this conversation.
        messages: Log of every accepted and rejected A2A message for this
            session, in order. Used for the "last 3 hops" UI hint and for
            debugging routing decisions.
        created_at: Unix epoch seconds; used by SessionStore for LRU eviction.
    """

    session_id: str
    chain: list[str] = field(default_factory=list)
    budget_used: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=lambda: time.time())

    def depth(self) -> int:
        """Return the current chain depth: ``len(chain)`` for non-empty chain, 0 otherwise.

        The protocol defines depth for the *receiver* of the next A2A
        message. When the chain is empty, the next message will be the
        first hop, so its receiver has depth 0.
        """
        if not self.chain:
            return 0
        return len(self.chain)

    def calls_remaining(self) -> int:
        """Return the number of A2A hops still allowed in this conversation."""
        return max(0, MAX_BUDGET - self.budget_used)

    def append_hop(self, sender_id: str, target_id: str) -> None:
        """Record that ``sender_id`` just sent a message to ``target_id``.

        The target is appended to the chain if it is not already present —
        for legitimate non-loop chains this is always the case.
        """
        if not self.chain:
            # First hop in this conversation — chain starts with the sender.
            self.chain.append(sender_id)
        if target_id not in self.chain:
            self.chain.append(target_id)
        self.budget_used += 1

    def record_message(self, message: dict[str, Any]) -> None:
        """Append a message to the per-session log (accepted or rejected)."""
        self.messages.append(message)


class SessionStore:
    """Bounded LRU map of ``session_id -> SessionState``.

    VS Code may host many chats in parallel; without eviction, the
    process would grow unboundedly. The default capacity of 256 covers
    a heavy day of usage (each session is at most a few KB) and is
    easily tunable.
    """

    def __init__(self, max_sessions: int = 256) -> None:
        self._max = max_sessions
        self._sessions: OrderedDict[str, SessionState] = OrderedDict()
        self._lock = threading.Lock()

    def get_or_create(self, session_id: str) -> SessionState:
        """Return the state for ``session_id``, creating it if necessary.

        Uses ``OrderedDict.move_to_end`` to implement LRU on access so
        that hot sessions don't get evicted.
        """
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                state = SessionState(session_id=session_id)
                self._sessions[session_id] = state
            else:
                self._sessions.move_to_end(session_id)
            self._evict_if_needed()
            return state

    def get(self, session_id: str) -> SessionState | None:
        """Return the state for ``session_id`` without creating it."""
        with self._lock:
            return self._sessions.get(session_id)

    def _evict_if_needed(self) -> None:
        """Drop the oldest sessions until we are under the capacity limit."""
        while len(self._sessions) > self._max:
            self._sessions.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)

    def clear(self) -> None:
        """Drop all sessions — used by tests."""
        with self._lock:
            self._sessions.clear()
