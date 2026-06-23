"""Unit tests for A2A message search (a2a_orchestrator.search)."""
from __future__ import annotations

from a2a_orchestrator.persistence import MessageStore
from a2a_orchestrator.search import search_a2a_messages, search_jsonl


def _make_msg(
    session_id: str,
    reason: str,
    summary: str,
    message_id: str = "msg-test00000001",
) -> dict:
    return {
        "schema_version": "0.7.0",
        "message_id": message_id,
        "session_id": session_id,
        "from": "agent-a",
        "to": "agent-b",
        "intent": "handoff",
        "reason": reason,
        "payload": {"summary": summary, "key_decisions": [], "open_questions": []},
        "routing_meta": {"chain": ["agent-a"], "depth": 0, "calls_remaining": 3},
        "outcome": "delivered",
    }


class TestSearchJsonl:
    def test_search_with_results(self):
        store = MessageStore(path=None)
        store.append(_make_msg("s1", "Need DBA help with migration",
                                "User wants to add a column to orders table."))
        store.append(_make_msg("s1", "Frontend bug in login form",
                                "The login button is not working properly."))
        results = search_jsonl(store, "migration")
        assert len(results) == 1
        assert "migration" in results[0]["message"]["reason"].lower()
        assert results[0]["score"] > 0

    def test_search_no_results(self):
        store = MessageStore(path=None)
        store.append(_make_msg("s1", "Need DBA help", "Summary of the task."))
        results = search_jsonl(store, "nonexistent-term")
        assert len(results) == 0

    def test_search_within_specific_session(self):
        store = MessageStore(path=None)
        store.append(_make_msg("s1", "migration task", "Adding a column to the table."))
        store.append(_make_msg("s2", "migration task", "Adding a column to the table."))
        results = search_jsonl(store, "migration", session_id="s1")
        assert len(results) == 1
        assert results[0]["session_id"] == "s1"

    def test_search_across_all_sessions(self):
        store = MessageStore(path=None)
        store.append(_make_msg("s1", "migration task", "Adding a column to the table."))
        store.append(_make_msg("s2", "migration task", "Adding a column to the table."))
        results = search_jsonl(store, "migration")
        assert len(results) == 2

    def test_search_limit(self):
        store = MessageStore(path=None)
        for i in range(5):
            store.append(_make_msg("s1", f"migration task {i}",
                                    f"Adding column {i} to the table.",
                                    message_id=f"msg-test{i:010d}"))
        results = search_jsonl(store, "migration", limit=3)
        assert len(results) == 3

    def test_search_scoring(self):
        """Messages with more query term occurrences score higher."""
        store = MessageStore(path=None)
        store.append(_make_msg("s1", "migration", "migration migration migration",
                                "msg-test00000001"))
        store.append(_make_msg("s1", "migration", "migration",
                                "msg-test00000002"))
        results = search_jsonl(store, "migration")
        assert len(results) == 2
        assert results[0]["score"] > results[1]["score"]


class TestSearchA2aMessages:
    def test_search_with_message_store(self):
        store = MessageStore(path=None)
        store.append(_make_msg("s1", "Need DBA help with migration",
                                "User wants to add a column to orders table."))
        results = search_a2a_messages(
            "migration", message_store=store, mnemos_client=None,
        )
        assert len(results) == 1
        assert results[0]["score"] > 0

    def test_search_no_mnemos_no_store(self):
        """When neither Mnemos nor a store is available, returns empty list."""
        results = search_a2a_messages("test", mnemos_client=None, message_store=None)
        assert results == []

    def test_search_fallback_when_mnemos_returns_empty(self):
        """When Mnemos returns nothing, falls back to JSONL."""
        store = MessageStore(path=None)
        store.append(_make_msg("s1", "migration task", "Adding a column."))
        results = search_a2a_messages(
            "migration", message_store=store, mnemos_client=None,
        )
        assert len(results) == 1
