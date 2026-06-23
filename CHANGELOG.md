# Changelog

All notable changes to a2a-orchestrator are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/),
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
