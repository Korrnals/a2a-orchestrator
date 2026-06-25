# Testing

Test coverage for the **a2a-orchestrator** MCP server — e2e protocol
tests and unit tests.

## E2E MCP Protocol Tests

19 tests covering all 11 MCP tools and 6 routing rules, run through the
MCP stdio protocol.

| # | Test | Result |
| --- | --- | --- |
| 1 | `get_metrics` (empty) | ✅ |
| 2 | `list_tenants` | ✅ |
| 3 | `get_chain_status` (empty session) | ✅ |
| 4 | `send_a2a` (SSE→DBA, deliver) | ✅ |
| 5 | `get_chain_status` (after send) | ✅ |
| 6 | `load_context` (by message_id) | ✅ |
| 7 | `search_messages` | ✅ |
| 8 | `send_a2a` R2 loop detection | ✅ |
| 9 | `create_saga` | ✅ |
| 10 | `get_saga_status` | ✅ |
| 11 | `create_registration_challenge` | ✅ |
| 12 | `send_a2a` with `saga_id` | ✅ |
| 13 | `send_a2a` non-existent saga (`SAGA_NOT_FOUND`) | ✅ |
| 14 | `send_a2a` R1 whitelist (non-existent target) | ✅ |
| 15 | `send_a2a` R1 unknown sender | ✅ |
| 16 | `send_a2a` R5 destructive without consent | ✅ |
| 17 | `send_a2a` R3 chain depth limit | ✅ |
| 18 | `unregister_agent` (non-existent) | ✅ |
| 19 | `get_metrics` (after activity) | ✅ |

**Result: 19/19 passed**

## Unit Tests

278 tests covering all modules:

- routing (R1–R6)
- session management
- saga pattern
- signing (Ed25519)
- WebSocket streaming
- search
- web server (REST API)
- registration
- multi-tenant isolation
- security fixes (path traversal, timing attacks, file permissions)

### Run

```bash
PYTHONPATH=src python3 -m pytest tests/ -q
```

### Run e2e only

```bash
PYTHONPATH=src python3 -m pytest tests/e2e/ -q
```

## See also

- [Routing Rules](routing-rules.md) — R1–R6 explained
- [Architecture](architecture.md) — module layout
- [Security](security.md) — security model and hardening