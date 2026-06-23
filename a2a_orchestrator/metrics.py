"""Thread-safe metrics counters for the A2A orchestrator.

A single :class:`Metrics` instance is created at module level in
:mod:`.server` and updated on every ``send_a2a`` outcome. The
``get_metrics`` MCP tool exposes the counters to clients.

Counters:

* ``messages_delivered`` — total successful send_a2a calls.
* ``messages_rejected`` — total rejected send_a2a calls.
* ``rejections_by_rule`` — dict mapping rejection codes to counts
  (``R1_NOT_WHITELISTED``, ``R2_LOOP_DETECTED``, etc.).
* ``mnemos_writes`` — successful Mnemos persist calls.
* ``fallback_writes`` — JSONL fallback writes (when Mnemos unavailable).
* ``active_sessions`` — current session count (from SessionStore).
* ``total_sessions`` — all-time session count (incremented on each
  new session creation).
"""
from __future__ import annotations

import threading
from typing import Any


class Metrics:
    """Thread-safe metrics counters.

    All methods are thread-safe via a single ``threading.Lock``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, Any] = {
            "messages_delivered": 0,
            "messages_rejected": 0,
            "rejections_by_rule": {
                "R1_NOT_WHITELISTED": 0,
                "R2_LOOP_DETECTED": 0,
                "R3_CHAIN_TOO_DEEP": 0,
                "R4_BUDGET_EXHAUSTED": 0,
                "R5_DESTRUCTIVE_DENIED": 0,
                "SCHEMA_INVALID": 0,
            },
            "mnemos_writes": 0,
            "fallback_writes": 0,
            "active_sessions": 0,
            "total_sessions": 0,
        }

    def record_delivered(self) -> None:
        """Increment messages_delivered counter."""
        with self._lock:
            self._counters["messages_delivered"] += 1

    def record_rejected(self, code: str) -> None:
        """Increment messages_rejected and the specific rejection rule.

        Args:
            code: The rejection code (e.g. ``R1_NOT_WHITELISTED``,
                ``SCHEMA_INVALID``).
        """
        with self._lock:
            self._counters["messages_rejected"] += 1
            by_rule = self._counters["rejections_by_rule"]
            if code in by_rule:
                by_rule[code] += 1
            else:
                # Unknown rejection code — track it dynamically.
                by_rule[code] = by_rule.get(code, 0) + 1

    def record_mnemos_write(self) -> None:
        """Increment mnemos_writes counter (successful Mnemos persist)."""
        with self._lock:
            self._counters["mnemos_writes"] += 1

    def record_fallback_write(self) -> None:
        """Increment fallback_writes counter (JSONL fallback used)."""
        with self._lock:
            self._counters["fallback_writes"] += 1

    def record_session_created(self) -> None:
        """Increment total_sessions counter (new session created)."""
        with self._lock:
            self._counters["total_sessions"] += 1

    def set_active_sessions(self, count: int) -> None:
        """Set the current active session count (from SessionStore)."""
        with self._lock:
            self._counters["active_sessions"] = count

    def snapshot(self) -> dict[str, Any]:
        """Return a copy of all counters (thread-safe)."""
        with self._lock:
            # Deep-copy the nested rejections_by_rule dict.
            result: dict[str, Any] = {}
            for key, val in self._counters.items():
                if isinstance(val, dict):
                    result[key] = dict(val)
                else:
                    result[key] = val
            return result

    def reset(self) -> None:
        """Reset all counters to zero — used by tests."""
        with self._lock:
            self._counters["messages_delivered"] = 0
            self._counters["messages_rejected"] = 0
            for key in self._counters["rejections_by_rule"]:
                self._counters["rejections_by_rule"][key] = 0
            self._counters["mnemos_writes"] = 0
            self._counters["fallback_writes"] = 0
            self._counters["active_sessions"] = 0
            self._counters["total_sessions"] = 0
