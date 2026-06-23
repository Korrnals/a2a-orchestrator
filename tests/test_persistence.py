"""Unit tests for MessageStore (a2a_orchestrator.persistence)."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from a2a_orchestrator.persistence import MessageStore


@pytest.fixture()
def store(tmp_path: Path) -> MessageStore:
    """MessageStore backed by a temp JSONL file."""
    return MessageStore(path=tmp_path / "messages.jsonl")


def _make_msg(msg_id: str, session_id: str = "s1") -> dict:
    return {
        "message_id": msg_id,
        "session_id": session_id,
        "from": "agent-a",
        "to": "agent-b",
        "outcome": "delivered",
    }


class TestAppendAndLoadRecent:
    def test_append_then_load_recent_returns_it(self, store):
        msg = _make_msg("msg-00000001")
        store.append(msg)
        result = store.load_recent("s1", n=10)
        assert len(result) == 1
        assert result[0]["message_id"] == "msg-00000001"

    def test_load_recent_filters_by_session(self, store):
        store.append(_make_msg("msg-00000001", "s1"))
        store.append(_make_msg("msg-00000002", "s2"))
        store.append(_make_msg("msg-00000003", "s1"))
        result = store.load_recent("s1", n=10)
        assert len(result) == 2
        assert all(m["session_id"] == "s1" for m in result)

    def test_load_recent_returns_last_n(self, store):
        for i in range(5):
            store.append(_make_msg(f"msg-{i:08d}"))
        result = store.load_recent("s1", n=3)
        assert len(result) == 3
        # newest last
        assert result[0]["message_id"] == "msg-00000002"
        assert result[2]["message_id"] == "msg-00000004"

    def test_load_recent_empty_session_returns_empty(self, store):
        store.append(_make_msg("msg-00000001", "s1"))
        assert store.load_recent("nonexistent") == []


class TestAtomicWrite:
    def test_file_exists_after_append(self, store, tmp_path):
        store.append(_make_msg("msg-00000001"))
        assert (tmp_path / "messages.jsonl").is_file()

    def test_file_contains_valid_jsonl(self, store, tmp_path):
        store.append(_make_msg("msg-00000001"))
        store.append(_make_msg("msg-00000002"))
        content = (tmp_path / "messages.jsonl").read_text(encoding="utf-8")
        lines = [line for line in content.strip().split("\n") if line]
        assert len(lines) == 2
        for line in lines:
            parsed = json.loads(line)
            assert parsed["message_id"].startswith("msg-")

    def test_lazy_directory_creation(self, tmp_path):
        """Parent dir is created on first write, not at init."""
        nested = tmp_path / "nested" / "deep" / "messages.jsonl"
        store = MessageStore(path=nested)
        assert not nested.parent.exists()
        store.append(_make_msg("msg-00000001"))
        assert nested.is_file()


class TestLoadAll:
    def test_load_all_no_filter(self, store):
        store.append(_make_msg("msg-00000001", "s1"))
        store.append(_make_msg("msg-00000002", "s2"))
        result = store.load_all()
        assert len(result) == 2

    def test_load_all_filtered_by_session(self, store):
        store.append(_make_msg("msg-00000001", "s1"))
        store.append(_make_msg("msg-00000002", "s2"))
        store.append(_make_msg("msg-00000003", "s1"))
        result = store.load_all(session_id="s1")
        assert len(result) == 2
        assert all(m["session_id"] == "s1" for m in result)


class TestThreadSafety:
    def test_concurrent_appends_dont_corrupt_file(self, tmp_path):
        """100 threads append 10 messages each; file should have 1000 lines."""
        path = tmp_path / "concurrent.jsonl"
        store = MessageStore(path=path)
        errors: list[Exception] = []

        def writer(thread_id: int) -> None:
            try:
                for i in range(10):
                    store.append(_make_msg(
                        f"msg-t{thread_id:02d}-{i:04d}", f"s{thread_id}"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(t,))
                   for t in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Threads raised errors: {errors}"
        # File should have 1000 valid JSON lines
        content = path.read_text(encoding="utf-8")
        lines = [line for line in content.strip().split("\n") if line]
        assert len(lines) == 1000
        # Every line must be valid JSON
        for line in lines:
            json.loads(line)  # raises if corrupt


class TestInMemoryOnly:
    def test_none_path_disables_file(self, tmp_path):
        store = MessageStore(path=None)
        store.append(_make_msg("msg-00000001"))
        assert len(store) == 1
        # No file should be created
        assert not (tmp_path / "messages.jsonl").exists()

    def test_clear_drops_in_memory(self, store):
        store.append(_make_msg("msg-00000001"))
        assert len(store) == 1
        store.clear()
        assert len(store) == 0
