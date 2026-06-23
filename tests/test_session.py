"""Unit tests for session state and store (a2a_orchestrator.session)."""
from __future__ import annotations

from a2a_orchestrator.session import MAX_BUDGET, SessionState, SessionStore

# --------------------------------------------------------------------------- #
# SessionState
# --------------------------------------------------------------------------- #

class TestSessionStateDepth:
    def test_empty_chain_depth_zero(self):
        s = SessionState(session_id="s1")
        assert s.depth() == 0

    def test_single_element_chain_depth_one(self):
        s = SessionState(session_id="s1", chain=["agent-a"])
        assert s.depth() == 1

    def test_two_element_chain_depth_two(self):
        s = SessionState(session_id="s1", chain=["agent-a", "agent-b"])
        assert s.depth() == 2


class TestSessionStateCallsRemaining:
    def test_full_budget_at_start(self):
        s = SessionState(session_id="s1", budget_used=0)
        assert s.calls_remaining() == MAX_BUDGET

    def test_partial_budget(self):
        s = SessionState(session_id="s1", budget_used=2)
        assert s.calls_remaining() == 1

    def test_zero_budget(self):
        s = SessionState(session_id="s1", budget_used=MAX_BUDGET)
        assert s.calls_remaining() == 0

    def test_over_budget_clamped_to_zero(self):
        s = SessionState(session_id="s1", budget_used=99)
        assert s.calls_remaining() == 0


class TestSessionStateAppendHop:
    def test_first_hop_chain_starts_with_sender(self):
        s = SessionState(session_id="s1")
        s.append_hop("agent-a", "agent-b")
        assert s.chain == ["agent-a", "agent-b"]
        assert s.budget_used == 1

    def test_second_hop_chain_grows(self):
        s = SessionState(session_id="s1", chain=["agent-a"],
                         budget_used=1)
        s.append_hop("agent-a", "agent-b")
        assert s.chain == ["agent-a", "agent-b"]
        assert s.budget_used == 2

    def test_target_already_in_chain_not_duplicated(self):
        """append_hop should not duplicate a target already in chain."""
        s = SessionState(session_id="s1", chain=["agent-a", "agent-b"])
        s.append_hop("agent-b", "agent-a")
        # agent-a is already in chain → not appended again
        assert s.chain == ["agent-a", "agent-b"]
        assert s.budget_used == 1


# --------------------------------------------------------------------------- #
# SessionStore
# --------------------------------------------------------------------------- #

class TestSessionStore:
    def test_get_or_create_creates_new(self):
        store = SessionStore(max_sessions=10)
        s = store.get_or_create("s1")
        assert s.session_id == "s1"
        assert s.chain == []
        assert len(store) == 1

    def test_get_or_create_returns_existing(self):
        store = SessionStore(max_sessions=10)
        s1 = store.get_or_create("s1")
        s1.append_hop("agent-a", "agent-b")
        s2 = store.get_or_create("s1")
        assert s2 is s1
        assert s2.chain == ["agent-a", "agent-b"]

    def test_lru_eviction_at_capacity(self):
        store = SessionStore(max_sessions=2)
        store.get_or_create("s1")
        store.get_or_create("s2")
        # Adding s3 should evict s1 (the oldest, least recently used)
        store.get_or_create("s3")
        assert len(store) == 2
        assert store.get("s1") is None
        assert store.get("s2") is not None
        assert store.get("s3") is not None

    def test_lru_access_prevents_eviction(self):
        """Accessing a session moves it to the end, preventing eviction."""
        store = SessionStore(max_sessions=2)
        store.get_or_create("s1")
        store.get_or_create("s2")
        # Access s1 → it becomes most recently used
        store.get_or_create("s1")
        # Adding s3 should evict s2 (now the oldest)
        store.get_or_create("s3")
        assert store.get("s1") is not None
        assert store.get("s2") is None
        assert store.get("s3") is not None

    def test_get_returns_none_for_missing(self):
        store = SessionStore()
        assert store.get("nonexistent") is None

    def test_clear_drops_all(self):
        store = SessionStore()
        store.get_or_create("s1")
        store.get_or_create("s2")
        store.clear()
        assert len(store) == 0
