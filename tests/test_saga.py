"""Unit tests for the saga pattern (a2a_orchestrator.saga)."""
from __future__ import annotations

from a2a_orchestrator.saga import (
    SAGA_ABANDONED,
    SAGA_ACTIVE,
    SAGA_COMPLETED,
    SAGA_MAX_BUDGET,
    SagaStore,
)


class TestSagaState:
    def test_create_saga(self):
        store = SagaStore()
        saga = store.create_saga(root_session_id="conv-001", metadata={"task": "migration"})
        assert saga.saga_id.startswith("saga-")
        assert saga.root_session_id == "conv-001"
        assert saga.status == SAGA_ACTIVE
        assert saga.chains == []
        assert saga.budget_used == 0
        assert saga.metadata == {"task": "migration"}
        assert saga.calls_remaining() == SAGA_MAX_BUDGET

    def test_saga_to_dict(self):
        store = SagaStore()
        saga = store.create_saga("conv-001")
        d = saga.to_dict()
        assert d["saga_id"] == saga.saga_id
        assert d["status"] == SAGA_ACTIVE
        assert d["budget_used"] == 0
        assert d["max_budget"] == SAGA_MAX_BUDGET
        assert d["calls_remaining"] == SAGA_MAX_BUDGET


class TestSagaAddChain:
    def test_add_chain(self):
        store = SagaStore()
        saga = store.create_saga("conv-001")
        updated = store.add_chain(saga.saga_id, ["agent-a", "agent-b"])
        assert updated is not None
        assert len(updated.chains) == 1
        assert updated.chains[0] == ["agent-a", "agent-b"]
        # add_chain no longer increments budget_used (C1 fix: record_call is
        # the sole budget incrementer to avoid double-counting).
        assert updated.budget_used == 0

    def test_add_multiple_chains(self):
        store = SagaStore()
        saga = store.create_saga("conv-001")
        store.add_chain(saga.saga_id, ["agent-a", "agent-b"])
        store.add_chain(saga.saga_id, ["agent-b", "agent-c"])
        saga = store.get_saga(saga.saga_id)
        assert saga is not None
        assert len(saga.chains) == 2
        # add_chain does not increment budget; only record_call does.
        assert saga.budget_used == 0

    def test_add_chain_to_nonexistent_saga(self):
        store = SagaStore()
        result = store.add_chain("saga-nonexistent", ["agent-a", "agent-b"])
        assert result is None


class TestSagaBudget:
    def test_budget_tracking_across_chains(self):
        store = SagaStore()
        saga = store.create_saga("conv-001")
        for _i in range(SAGA_MAX_BUDGET):
            assert store.record_call(saga.saga_id) is True
        # Budget exhausted
        assert store.record_call(saga.saga_id) is False
        saga = store.get_saga(saga.saga_id)
        assert saga.calls_remaining() == 0

    def test_record_call_nonexistent_saga(self):
        store = SagaStore()
        assert store.record_call("saga-nonexistent") is False


class TestSagaComplete:
    def test_complete_saga(self):
        store = SagaStore()
        saga = store.create_saga("conv-001")
        assert store.complete_saga(saga.saga_id) is True
        saga = store.get_saga(saga.saga_id)
        assert saga.status == SAGA_COMPLETED

    def test_complete_nonexistent(self):
        store = SagaStore()
        assert store.complete_saga("saga-nonexistent") is False

    def test_add_chain_to_completed_saga_fails(self):
        store = SagaStore()
        saga = store.create_saga("conv-001")
        store.complete_saga(saga.saga_id)
        result = store.add_chain(saga.saga_id, ["agent-a"])
        assert result is None


class TestSagaAbandon:
    def test_abandon_saga(self):
        store = SagaStore()
        saga = store.create_saga("conv-001")
        assert store.abandon_saga(saga.saga_id, "user cancelled") is True
        saga = store.get_saga(saga.saga_id)
        assert saga.status == SAGA_ABANDONED
        assert saga.abandon_reason == "user cancelled"

    def test_abandon_nonexistent(self):
        store = SagaStore()
        assert store.abandon_saga("saga-nonexistent", "test") is False


class TestSagaNotFound:
    def test_get_saga_not_found(self):
        store = SagaStore()
        assert store.get_saga("saga-nonexistent") is None


class TestSagaList:
    def test_list_all_sagas(self):
        store = SagaStore()
        store.create_saga("conv-001")
        store.create_saga("conv-002")
        assert len(store.list_sagas()) == 2

    def test_list_by_status(self):
        store = SagaStore()
        s1 = store.create_saga("conv-001")
        s2 = store.create_saga("conv-002")
        store.complete_saga(s1.saga_id)
        active = store.list_sagas(status=SAGA_ACTIVE)
        completed = store.list_sagas(status=SAGA_COMPLETED)
        assert len(active) == 1
        assert active[0].saga_id == s2.saga_id
        assert len(completed) == 1
        assert completed[0].saga_id == s1.saga_id


class TestSagaLRUEviction:
    def test_eviction_drops_oldest(self):
        store = SagaStore(max_sagas=3)
        s1 = store.create_saga("conv-001")
        s2 = store.create_saga("conv-002")
        s3 = store.create_saga("conv-003")
        s4 = store.create_saga("conv-004")  # triggers eviction
        assert store.get_saga(s1.saga_id) is None  # evicted
        assert store.get_saga(s2.saga_id) is not None
        assert store.get_saga(s3.saga_id) is not None
        assert store.get_saga(s4.saga_id) is not None
