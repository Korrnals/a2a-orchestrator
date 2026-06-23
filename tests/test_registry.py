"""Unit tests for AgentCardRegistry (a2a_orchestrator.registry)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from a2a_orchestrator.registry import AgentCardRegistry


def _write_card(path: Path, card: dict) -> None:
    path.write_text(json.dumps(card), encoding="utf-8")


class TestRegistryLoad:
    def test_load_from_temp_dir(self, cards_dir):
        reg = AgentCardRegistry(cards_dir=cards_dir)
        reg.load()
        assert len(reg) == 4
        assert "agent-a" in reg
        assert "agent-b" in reg
        assert "agent-c" in reg

    def test_duplicate_id_raises_value_error(self, tmp_path):
        d = tmp_path / "agents"
        d.mkdir()
        card = {
            "id": "agent-dup",
            "name": "Dup",
            "version": "0.6.0",
            "plugin": "test-plugin",
            "agent_file": "dup.agent.md",
            "capabilities": ["test"],
            "routing": {"accepts_routes_from": [], "routing_keywords": ["t"]},
            "tags": [],
        }
        _write_card(d / "card1.json", card)
        _write_card(d / "card2.json", card)
        reg = AgentCardRegistry(cards_dir=d)
        with pytest.raises(ValueError, match="Duplicate Agent Card id"):
            reg.load()

    def test_invalid_json_raises_value_error(self, tmp_path):
        d = tmp_path / "agents"
        d.mkdir()
        (d / "bad.json").write_text("{not valid json", encoding="utf-8")
        reg = AgentCardRegistry(cards_dir=d)
        with pytest.raises(ValueError, match="not valid JSON"):
            reg.load()

    def test_missing_dir_raises_file_not_found(self, tmp_path):
        reg = AgentCardRegistry(cards_dir=tmp_path / "nonexistent")
        with pytest.raises(FileNotFoundError):
            reg.load()


class TestRegistryAllowedTargets:
    def test_allowed_targets_returns_correct_set(self, cards_dir):
        reg = AgentCardRegistry(cards_dir=cards_dir)
        reg.load()
        # B accepts from A, and shallow accepts from A → A can call both.
        assert reg.allowed_targets("agent-a") == {"agent-b",
                                                       "agent-shallow"}
        # C accepts from B → B's allowed_targets includes C.
        assert reg.allowed_targets("agent-b") == {"agent-c"}
        # A accepts from C → C's allowed_targets includes A.
        assert reg.allowed_targets("agent-c") == {"agent-a"}
        # Unknown agent → empty set
        assert reg.allowed_targets("agent-unknown") == set()


class TestRegistryMaxChainDepth:
    def test_default_max_chain_depth(self, cards_dir):
        reg = AgentCardRegistry(cards_dir=cards_dir)
        reg.load()
        # Cards without max_chain_depth → default 3
        assert reg.max_chain_depth("agent-a") == 3
        assert reg.max_chain_depth("agent-b") == 3

    def test_per_card_override(self, cards_dir):
        reg = AgentCardRegistry(cards_dir=cards_dir)
        reg.load()
        # agent-shallow has max_chain_depth=1
        assert reg.max_chain_depth("agent-shallow") == 1

    def test_unknown_agent_returns_default(self, cards_dir):
        reg = AgentCardRegistry(cards_dir=cards_dir)
        reg.load()
        assert reg.max_chain_depth("agent-unknown") == 3
