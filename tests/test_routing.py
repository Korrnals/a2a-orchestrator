"""Unit tests for R1-R4 routing gates (a2a_orchestrator.routing)."""
from __future__ import annotations

import pytest
from a2a_orchestrator.registry import AgentCardRegistry
from a2a_orchestrator.routing import (
    R1_NOT_WHITELISTED,
    R2_LOOP_DETECTED,
    R3_CHAIN_TOO_DEEP,
    R4_BUDGET_EXHAUSTED,
    check_all,
    check_budget,
    check_depth,
    check_loop,
    check_whitelist,
)
from a2a_orchestrator.session import MAX_CHAIN_DEPTH, SessionState


@pytest.fixture()
def registry(cards_dir):
    reg = AgentCardRegistry(cards_dir=cards_dir)
    reg.load()
    return reg


# --------------------------------------------------------------------------- #
# R1: Whitelist
# --------------------------------------------------------------------------- #

class TestR1Whitelist:
    def test_unknown_sender_rejected(self, registry):
        rej = check_whitelist("agent-unknown", "agent-b", registry)
        assert rej is not None
        assert rej.code == R1_NOT_WHITELISTED

    def test_unknown_target_rejected(self, registry):
        rej = check_whitelist("agent-a", "agent-unknown", registry)
        assert rej is not None
        assert rej.code == R1_NOT_WHITELISTED

    def test_non_whitelisted_target_rejected(self, registry):
        # agent-a can only call agent-b (B accepts from A).
        # agent-a cannot call agent-c (C accepts from B, not A).
        rej = check_whitelist("agent-a", "agent-c", registry)
        assert rej is not None
        assert rej.code == R1_NOT_WHITELISTED

    def test_whitelisted_passes(self, registry):
        # B accepts routes from A → A can call B.
        rej = check_whitelist("agent-a", "agent-b", registry)
        assert rej is None


# --------------------------------------------------------------------------- #
# R2: Loop
# --------------------------------------------------------------------------- #

class TestR2Loop:
    def test_target_in_chain_rejected(self):
        session = SessionState(session_id="s1", chain=["agent-a",
                                                        "agent-b"])
        rej = check_loop("agent-a", session)
        assert rej is not None
        assert rej.code == R2_LOOP_DETECTED

    def test_target_not_in_chain_passes(self):
        session = SessionState(session_id="s1", chain=["agent-a"])
        rej = check_loop("agent-b", session)
        assert rej is None


# --------------------------------------------------------------------------- #
# R3: Depth
# --------------------------------------------------------------------------- #

class TestR3Depth:
    def test_depth_at_max_rejected(self, registry):
        # chain has MAX_CHAIN_DEPTH entries → depth == MAX_CHAIN_DEPTH
        chain = ["agent-a", "agent-b", "agent-c"]
        session = SessionState(session_id="s1", chain=chain)
        assert session.depth() == MAX_CHAIN_DEPTH
        rej = check_depth("agent-a", "agent-b", session, registry)
        assert rej is not None
        assert rej.code == R3_CHAIN_TOO_DEEP

    def test_per_card_override_rejected(self, registry):
        # agent-shallow has max_chain_depth=1; depth 1 >= 1 → reject
        session = SessionState(session_id="s1", chain=["agent-shallow"])
        assert session.depth() == 1
        rej = check_depth("agent-shallow", "agent-a", session, registry)
        assert rej is not None
        assert rej.code == R3_CHAIN_TOO_DEEP

    def test_normal_depth_passes(self, registry):
        session = SessionState(session_id="s1", chain=["agent-a"])
        assert session.depth() == 1
        rej = check_depth("agent-a", "agent-b", session, registry)
        assert rej is None


# --------------------------------------------------------------------------- #
# R4: Budget
# --------------------------------------------------------------------------- #

class TestR4Budget:
    def test_budget_exhausted_rejected(self):
        session = SessionState(session_id="s1", budget_used=3)
        rej = check_budget(session)
        assert rej is not None
        assert rej.code == R4_BUDGET_EXHAUSTED

    def test_budget_remaining_passes(self):
        session = SessionState(session_id="s1", budget_used=0)
        rej = check_budget(session)
        assert rej is None


# --------------------------------------------------------------------------- #
# check_all: short-circuit
# --------------------------------------------------------------------------- #

class TestCheckAll:
    def test_r1_fails_short_circuits(self, registry):
        """When R1 fails, R2/R3/R4 are not checked."""
        session = SessionState(session_id="s1", chain=["agent-a"],
                               budget_used=3)
        # R1 fails (unknown sender), R4 would also fail — but R1 wins.
        rej = check_all("agent-unknown", "agent-b", session, registry)
        assert rej is not None
        assert rej.code == R1_NOT_WHITELISTED

    def test_r2_fails_when_r1_passes(self, registry):
        session = SessionState(session_id="s1", chain=["agent-a",
                                                        "agent-b"])
        # R1 passes (a→b allowed), R2 fails (b already in chain)
        rej = check_all("agent-a", "agent-b", session, registry)
        assert rej is not None
        assert rej.code == R2_LOOP_DETECTED

    def test_all_pass_returns_none(self, registry):
        # A can call B (B accepts from A), B not in chain, depth ok, budget ok.
        session = SessionState(session_id="s1", chain=["agent-a"])
        rej = check_all("agent-a", "agent-b", session, registry)
        assert rej is None
