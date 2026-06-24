"""Saga pattern — long-lived dialog state across multiple A2A chains.

A *saga* groups multiple A2A chains that belong to the same logical
task. Without sagas, each A2A message starts a fresh chain with
``depth=0``; with sagas, a multi-step task (where agent B asks agent A
a clarifying question mid-chain) can persist state across chain
boundaries.

Budget tracking is per-saga: the total A2A calls across all chains
within one saga must not exceed ``MAX_BUDGET * 2`` (6 by default).
This is more generous than the per-session budget (3) because sagas
are explicitly designed for longer multi-chain workflows.

Thread-safe via a single ``threading.Lock``. Bounded LRU eviction
(128 sagas default) prevents unbounded memory growth.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .session import MAX_BUDGET

# Sagas allow more total budget than a single chain because they
# intentionally span multiple chains. 2x the per-session budget.
SAGA_MAX_BUDGET = MAX_BUDGET * 2  # 6 by default

SAGA_ACTIVE = "active"
SAGA_COMPLETED = "completed"
SAGA_ABANDONED = "abandoned"


@dataclass
class SagaState:
    """Mutable per-saga state.

    Attributes:
        saga_id: Unique id (``saga-<hex>``).
        root_session_id: The session that started the saga.
        chains: List of chains within this saga. Each chain is a list
            of A2A ids (same shape as ``SessionState.chain``).
        status: ``"active"``, ``"completed"``, or ``"abandoned"``.
        budget_used: Total A2A calls across all chains in this saga.
        created_at: Unix epoch seconds.
        updated_at: Unix epoch seconds (touched on every mutation).
        metadata: Free-form dict set at creation time.
        abandon_reason: Set when status transitions to ``abandoned``.
    """

    saga_id: str
    root_session_id: str
    chains: list[list[str]] = field(default_factory=list)
    status: str = SAGA_ACTIVE
    budget_used: int = 0
    created_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())
    metadata: dict[str, Any] = field(default_factory=dict)
    abandon_reason: str = ""

    def calls_remaining(self) -> int:
        """Return how many more A2A calls this saga can accept."""
        return max(0, SAGA_MAX_BUDGET - self.budget_used)

    def touch(self) -> None:
        """Update the ``updated_at`` timestamp."""
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot of the saga state."""
        return {
            "saga_id": self.saga_id,
            "root_session_id": self.root_session_id,
            "chains": [list(c) for c in self.chains],
            "status": self.status,
            "budget_used": self.budget_used,
            "calls_remaining": self.calls_remaining(),
            "max_budget": SAGA_MAX_BUDGET,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
            "abandon_reason": self.abandon_reason,
        }


class SagaStore:
    """Thread-safe bounded LRU map of ``saga_id -> SagaState``.

    Args:
        max_sagas: Maximum number of sagas to keep in memory. Oldest
            are evicted when the limit is exceeded (LRU).
    """

    def __init__(self, max_sagas: int = 128) -> None:
        self._max = max_sagas
        self._sagas: OrderedDict[str, SagaState] = OrderedDict()
        self._lock = threading.Lock()

    def create_saga(
        self,
        root_session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> SagaState:
        """Create a new saga and return its state.

        Args:
            root_session_id: The session that initiated the saga.
            metadata: Optional free-form metadata dict.
        """
        saga_id = f"saga-{uuid4().hex[:12]}"
        saga = SagaState(
            saga_id=saga_id,
            root_session_id=root_session_id,
            metadata=metadata or {},
        )
        with self._lock:
            self._sagas[saga_id] = saga
            self._evict_if_needed()
        return saga

    def get_saga(self, saga_id: str) -> SagaState | None:
        """Return the saga state for ``saga_id``, or ``None`` if not found."""
        with self._lock:
            saga = self._sagas.get(saga_id)
            if saga is not None:
                self._sagas.move_to_end(saga_id)
            return saga

    def add_chain(self, saga_id: str, chain: list[str]) -> SagaState | None:
        """Append a new chain to the saga.

        Returns the updated saga state, or ``None`` if the saga was not
        found or is no longer active.

        .. note::
           This method does **not** increment ``budget_used``. Budget is
           incremented solely by :meth:`record_call` to avoid
           double-counting (each A2A call in a saga consumes exactly 1
           budget, not 2).
        """
        with self._lock:
            saga = self._sagas.get(saga_id)
            if saga is None or saga.status != SAGA_ACTIVE:
                return None
            saga.chains.append(list(chain))
            saga.touch()
            self._sagas.move_to_end(saga_id)
            return saga

    def record_call(self, saga_id: str) -> bool:
        """Record one A2A call against the saga budget.

        Returns ``True`` if the call is within budget, ``False`` if the
        saga is exhausted, not found, or no longer active.
        """
        with self._lock:
            saga = self._sagas.get(saga_id)
            if saga is None or saga.status != SAGA_ACTIVE:
                return False
            if saga.budget_used >= SAGA_MAX_BUDGET:
                return False
            saga.budget_used += 1
            saga.touch()
            return True

    def complete_saga(self, saga_id: str) -> bool:
        """Mark a saga as completed. Returns ``True`` if the saga was found."""
        with self._lock:
            saga = self._sagas.get(saga_id)
            if saga is None:
                return False
            saga.status = SAGA_COMPLETED
            saga.touch()
            return True

    def abandon_saga(self, saga_id: str, reason: str) -> bool:
        """Mark a saga as abandoned with a reason. Returns ``True`` if found."""
        with self._lock:
            saga = self._sagas.get(saga_id)
            if saga is None:
                return False
            saga.status = SAGA_ABANDONED
            saga.abandon_reason = reason
            saga.touch()
            return True

    def list_sagas(self, status: str = "") -> list[SagaState]:
        """Return all sagas, optionally filtered by status."""
        with self._lock:
            sagas = list(self._sagas.values())
        if status:
            sagas = [s for s in sagas if s.status == status]
        return sagas

    def __len__(self) -> int:
        with self._lock:
            return len(self._sagas)

    def clear(self) -> None:
        """Drop all sagas — used by tests."""
        with self._lock:
            self._sagas.clear()

    def _evict_if_needed(self) -> None:
        """Drop the oldest sagas until under the capacity limit."""
        while len(self._sagas) > self._max:
            self._sagas.popitem(last=False)
