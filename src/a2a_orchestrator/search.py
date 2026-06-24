"""Vector/substring search across A2A messages.

Searches A2A message content for relevant past conversations. Uses
Mnemos's search API when available; falls back to substring search on
the JSONL fallback file when Mnemos is unreachable.

The search is session-scoped (``session_id`` provided) or global
(across all sessions). Results include the message content and a
relevance score.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .mnemos_client import MnemosClient, MnemosUnavailableError
from .persistence import MessageStore

log = logging.getLogger("a2a_orchestrator.search")


def _extract_text(message: dict[str, Any]) -> str:
    """Extract all searchable text from an A2A message.

    Concatenates summary, reason, key_decisions, and open_questions
    into a single lowercase string for substring matching.
    """
    parts: list[str] = []
    parts.append(str(message.get("reason", "")))
    payload = message.get("payload", {})
    if isinstance(payload, dict):
        parts.append(str(payload.get("summary", "")))
        for kd in payload.get("key_decisions", []):
            parts.append(str(kd))
        for oq in payload.get("open_questions", []):
            parts.append(str(oq))
    return " ".join(parts).lower()


def _score_message(message: dict[str, Any], query: str) -> float:
    """Score a message by how well it matches the query.

    Simple TF-style scoring: count query term occurrences in the
    message text. Returns 0.0 if no terms match.
    """
    text = _extract_text(message)
    terms = query.lower().split()
    if not terms:
        return 0.0
    score = 0.0
    for term in terms:
        count = text.count(term)
        score += count
    # Normalise by the number of terms so longer queries don't
    # automatically score higher.
    return score / len(terms) if terms else 0.0


def search_jsonl(
    store: MessageStore,
    query: str,
    session_id: str = "",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Substring search over the JSONL fallback store.

    Args:
        store: The MessageStore to search.
        query: The search query (space-separated terms, AND-ish).
        session_id: If provided, restrict to this session.
        limit: Maximum number of results.

    Returns:
        List of ``{message, score, session_id, message_id}`` dicts,
        sorted by score descending.
    """
    messages = store.load_all(session_id=session_id or None)
    results: list[dict[str, Any]] = []
    for msg in messages:
        score = _score_message(msg, query)
        if score > 0:
            results.append({
                "message": msg,
                "score": round(score, 3),
                "session_id": msg.get("session_id", ""),
                "message_id": msg.get("message_id", ""),
            })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def search_mnemos(
    client: MnemosClient,
    query: str,
    session_id: str = "",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search via Mnemos (if it supports search).

    Currently Mnemos does not expose a dedicated search endpoint for
    A2A turns, so we fetch turns and filter client-side. This is a
    best-effort approach — for large sessions, use the JSONL fallback.

    M3 fix: when ``session_id`` is empty (global search), this function
    returns ``[]`` because the current Mnemos API requires a session id
    to fetch turns (there is no "list all sessions" or "search across
    sessions" endpoint). Global search is JSONL-only — the caller
    should fall through to :func:`search_jsonl` which searches the
    local MessageStore across all sessions.
    """
    results: list[dict[str, Any]] = []
    if session_id:
        try:
            range_resp = client.get_turn_range(
                session_id, from_step=0, to_step=99, mode="summary",
            )
            turns = range_resp.get("turns", []) or range_resp.get("items", [])
            for turn in turns:
                content = turn.get("content") or turn.get("body") or ""
                if isinstance(content, str):
                    try:
                        msg = json.loads(content)
                    except json.JSONDecodeError:
                        continue
                elif isinstance(content, dict):
                    msg = content
                else:
                    continue
                score = _score_message(msg, query)
                if score > 0:
                    results.append({
                        "message": msg,
                        "score": round(score, 3),
                        "session_id": session_id,
                        "message_id": msg.get("message_id", ""),
                    })
        except MnemosUnavailableError:
            return []
    # M3: when session_id is empty, global Mnemos search is not
    # supported by the current API. Return [] so the caller falls
    # through to the JSONL fallback (search_jsonl with session_id="").
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def search_a2a_messages(
    query: str,
    session_id: str = "",
    limit: int = 10,
    *,
    mnemos_client: MnemosClient | None = None,
    message_store: MessageStore | None = None,
) -> list[dict[str, Any]]:
    """Search A2A messages with Mnemos fallback to JSONL.

    Args:
        query: The search query.
        session_id: If provided, search within this session only.
        limit: Maximum number of results.
        mnemos_client: Optional Mnemos client (tries Mnemos first).
        message_store: The JSONL fallback store (used if Mnemos fails
            or is not provided).

    Returns:
        List of result dicts with ``message``, ``score``,
        ``session_id``, ``message_id``.
    """
    # Try Mnemos first if a client is provided.
    if mnemos_client is not None:
        results = search_mnemos(mnemos_client, query, session_id, limit)
        if results:
            return results
        # If Mnemos returned nothing, fall through to JSONL.
        # (MnemosUnavailableError is caught inside search_mnemos → returns [])

    # Fallback: JSONL substring search.
    if message_store is not None:
        return search_jsonl(message_store, query, session_id, limit)

    return []
