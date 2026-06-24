# Changelog

All notable changes to a2a-orchestrator are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/),
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.9.0] - 2026-06-24

### Added
- `create_saga` MCP tool — create sagas for long-lived dialog state (was internal only)
- 11 new tests for loop detection, registration race, target depth cap, metrics codes

### Fixed
- Schema: allow directory prefix in `agent_file` pattern (e.g. `agents/foo.agent.md`)
- M1: `_registration_services` cache race condition — added thread-safe double-checked locking
- M2: `check_depth` now enforces target's `max_chain_depth`, not just sender's
- M3: Missing rejection codes (`R6_SIGNATURE_INVALID`, `SAGA_NOT_FOUND`, `SAGA_BUDGET_EXHAUSTED`) in metrics initial dict
- L1: Documented that `A2A_SCHEMA_VERSION` (0.7.0) ≠ package version (intentional)
- L2: Removed dead code `R5_DESTRUCTIVE_PENDING` constant
- L3: `load_context` turn_id fallback no longer returns wrong message — returns `{ok: False}` instead
- L4: `conftest.py` agent_file pattern aligned with embedded schema (directory prefix)

### Changed
- 241 tests (was 230), ruff clean, mypy clean (20 files)
- Code review: 0 critical, 0 high, 3 medium, 4 low — all fixed



### Added
- Project renamed from `gcw-orchestrator` to `a2a-orchestrator`
- MIT License
- `.gitignore`, `CONTRIBUTING.md`, `CHANGELOG.md`

### Changed
- Package name: `gcw_orchestrator` → `a2a_orchestrator` (pending)

## [0.1.0] - 2026-06-24

### Added
- MCP server with `send_a2a` tool
- 5 routing checks (R1 whitelist, R2 loop, R3 depth, R4 budget, R5 destructive)
- Agent Card registry (loads `a2a/agents/*.json`)
- Per-session chain/depth/budget state (LRU, thread-safe)
- Mnemos REST client (5 endpoints, retry/backoff)
- JSONL file fallback (Mnemos unavailable → local persistence)
- JSON-schema validation for Agent Cards and A2A messages
- 80 unit + e2e tests
- `pyproject.toml` (hatchling build backend)
