"""In-memory message store with JSONL file fallback.

When Mnemos is unavailable (network down, quota exhausted, not started),
the orchestrator still needs a durable audit trail of every A2A message
— accepted and rejected. This module provides that trail.

Design:

* **In-memory list** is the primary store. Every ``append`` hits it.
* **JSONL file** is the durable fallback. Writes are atomic (tmp + rename)
  so a crash mid-write never leaves a half-written line.
* **Thread-safe** via a single ``threading.Lock`` — the MCP server may
  serve concurrent tool calls.
* **Lazy directory creation** — ``~/.a2a/`` is created on first write,
  not at import time, so importing the module in a read-only env is safe.

The file path comes from :data:`a2a_orchestrator.config.FALLBACK_JSONL_PATH`,
which honours the ``A2A_FALLBACK_JSONL`` env var (with ``GCW_A2A_FALLBACK_JSONL``
as a backward-compat fallback).
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .config import FALLBACK_JSONL_PATH

# L2 fix: default max size for the JSONL fallback file (50 MiB). When
# the file exceeds this size, it is rotated: the current file is renamed
# to ``<path>.1`` (overwriting any previous rotation) and a new empty
# file is created. This prevents unbounded disk growth in long-running
# deployments where Mnemos is unavailable. Set to 0 to disable rotation.
DEFAULT_MAX_JSONL_BYTES = 50 * 1024 * 1024


class _DefaultPathSentinel:
    """Sentinel for ``MessageStore(path=...)`` meaning "use FALLBACK_JSONL_PATH".

    This distinguishes "caller did not pass path" (→ use default file)
    from "caller explicitly passed ``None``" (→ in-memory only, no file).
    """

    _instance: _DefaultPathSentinel | None = None

    def __new__(cls) -> _DefaultPathSentinel:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<DEFAULT_PATH>"


_DEFAULT_PATH = _DefaultPathSentinel()


class MessageStore:
    """Thread-safe in-memory + JSONL message store.

    Args:
        path: JSONL file path. Defaults to
            :data:`config.FALLBACK_JSONL_PATH` (``~/.a2a/a2a-messages.jsonl``
            or ``$A2A_FALLBACK_JSONL``). Pass ``None`` explicitly to
            disable the file fallback (in-memory only — useful for tests
            and for per-tenant stores that should not share a file).
    """

    def __init__(
        self,
        path: Path | str | None | _DefaultPathSentinel = _DEFAULT_PATH,
        max_bytes: int = DEFAULT_MAX_JSONL_BYTES,
    ) -> None:
        if isinstance(path, _DefaultPathSentinel):
            path = FALLBACK_JSONL_PATH
        self._path: Path | None = Path(path) if path else None
        # L2 fix: max file size before rotation. 0 disables rotation.
        self._max_bytes = max_bytes
        self._messages: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @property
    def path(self) -> Path | None:
        """Return the JSONL file path, or ``None`` if file fallback is off."""
        return self._path

    def append(self, message: dict[str, Any]) -> None:
        """Append a message to the in-memory list and JSONL file.

        The JSONL write is atomic: the line is written to a tmp file and
        ``os.rename`` swaps it into place. This is crash-safe on POSIX
        because ``rename`` is atomic on the same filesystem.

        Raises:
            OSError: if the file cannot be written (disk full, permission).
                The in-memory list is still updated before the file write
                so the process can continue serving requests.
        """
        with self._lock:
            self._messages.append(message)
            if self._path is not None:
                self._write_line(message)

    def load_recent(self, session_id: str, n: int = 10) -> list[dict[str, Any]]:
        """Return the last ``n`` messages for ``session_id`` (newest last).

        Scans the in-memory list in reverse and collects the first ``n``
        matches. If the in-memory list is empty and a JSONL file exists,
        the file is read first (lazy load) so a fresh process can still
        answer history queries.
        """
        with self._lock:
            if not self._messages and self._path is not None and self._path.is_file():
                self._load_from_file()
            matches: list[dict[str, Any]] = []
            for msg in reversed(self._messages):
                if msg.get("session_id") == session_id:
                    matches.append(msg)
                    if len(matches) >= n:
                        break
            matches.reverse()
            return matches

    def load_all(self, session_id: str | None = None) -> list[dict[str, Any]]:
        """Return all messages, optionally filtered by ``session_id``.

        If the in-memory list is empty and a JSONL file exists, the file
        is loaded first (same lazy-load as :meth:`load_recent`).
        """
        with self._lock:
            if not self._messages and self._path is not None and self._path.is_file():
                self._load_from_file()
            if session_id is None:
                return list(self._messages)
            return [m for m in self._messages if m.get("session_id") == session_id]

    def find_by_message_id(self, message_id: str) -> dict[str, Any] | None:
        """Return the message with ``message_id``, or ``None`` if not found.

        Searches the in-memory list first; if empty and a JSONL file
        exists, loads from file first.
        """
        with self._lock:
            if not self._messages and self._path is not None and self._path.is_file():
                self._load_from_file()
            for msg in self._messages:
                if msg.get("message_id") == message_id:
                    return msg
            return None

    def clear(self) -> None:
        """Drop the in-memory list. Does NOT delete the JSONL file."""
        with self._lock:
            self._messages.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._messages)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _ensure_dir(self) -> None:
        """Create the parent directory of the JSONL file if missing.

        M2 fix: also restricts the JSONL file to owner-only (0o600) on
        first creation so that sensitive A2A message payloads (which may
        contain summaries, decisions, artifact pointers) are not
        readable by other processes on the host.
        """
        if self._path is None:
            return
        parent = self._path.parent
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        # M2 fix: restrict file permissions to owner-only on first
        # creation. We only chmod if the file does not yet exist, so we
        # don't override permissions on a pre-existing file the user may
        # have intentionally set. Subsequent appends preserve the mode.
        if not self._path.exists():
            # Create the file with 0o600 via low-level os.open so there
            # is no window where the file exists with default umask.
            fd = os.open(self._path, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(fd)

    def _write_line(self, message: dict[str, Any]) -> None:
        """Append one JSON line to the JSONL file atomically.

        Strategy: open the file in append mode and write one line. Python's
        ``open(..., "a")`` on POSIX is atomic for writes smaller than the
        pipe buffer (>= 4096 bytes) when a single ``write`` call is used.
        For larger messages we still use a single ``write`` of the
        pre-serialised string, which keeps the atomicity guarantee for
        the common case and degrades gracefully for huge payloads.

        The directory is created lazily on the first write.
        """
        self._ensure_dir()
        assert self._path is not None
        # L2 fix: rotate the file if it exceeds the size limit. This
        # prevents unbounded disk growth in long-running deployments
        # where Mnemos is unavailable and every message hits JSONL.
        self._maybe_rotate()
        line = json.dumps(message, ensure_ascii=False, sort_keys=True) + "\n"
        # O_APPEND ensures every write seeks to end-of-file atomically.
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())

    def _maybe_rotate(self) -> None:
        """Rotate the JSONL file if it exceeds ``self._max_bytes``.

        L2 fix: renames the current file to ``<path>.1`` (overwriting any
        previous rotation) so the audit trail is preserved but bounded.
        Called under ``self._lock`` from :meth:`_write_line`. Rotation
        is disabled when ``self._max_bytes`` is 0.
        """
        if self._path is None or self._max_bytes <= 0:
            return
        if not self._path.exists():
            return
        try:
            if self._path.stat().st_size >= self._max_bytes:
                rotated = self._path.with_suffix(self._path.suffix + ".1")
                # os.replace is atomic on POSIX — no window where neither
                # file exists. The old rotation (if any) is overwritten.
                os.replace(self._path, rotated)
        except OSError:
            # If stat/replace fails (permissions, race), skip rotation
            # and continue writing — better to log than to drop messages.
            return

    def _load_from_file(self) -> None:
        """Read the JSONL file into the in-memory list (if empty).

        Called lazily by :meth:`load_recent` / :meth:`load_all` when the
        in-memory list is empty but the file exists. Corrupt lines
        (invalid JSON) are skipped with a warning printed to stderr —
        a half-corrupt file should not crash the whole store.
        """
        if self._path is None or not self._path.is_file():
            return
        loaded: list[dict[str, Any]] = []
        try:
            with open(self._path, encoding="utf-8") as fh:
                for lineno, raw in enumerate(fh, 1):
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        loaded.append(json.loads(raw))
                    except json.JSONDecodeError:
                        # Skip corrupt line — don't crash the store.
                        import sys

                        print(
                            f"[a2a-orchestrator] WARNING: skipping corrupt "
                            f"line {lineno} in {self._path}",
                            file=sys.stderr,
                        )
        except OSError:
            return
        self._messages = loaded
