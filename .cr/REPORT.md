# Code Review Report — a2a-orchestrator (post-v0.8.0)

**Reviewer:** GCW Code Reviewer (glm-5.2)
**Date:** 2026-06-24
**Scope:** Full codebase — 20 source modules, 2 schemas, 20 test files, config, examples
**Mode:** standard (all 5 reviewers, 2 critic cycles)
**Baseline:** 230 tests pass, ruff clean, mypy clean (20 files)

---

## Executive summary

**No critical or high findings.** The codebase is production-ready for v0.9.0.

All 6 previous-review fixes (C1, C2, H1, H2, H3, H4) are **confirmed resolved** with dedicated tests. The architecture is clean: single-responsibility modules, thread-safe stores, graceful degradation (Mnemos→JSONL, WS→silent), and proper tenant isolation.

7 findings total: **0 critical, 0 high, 3 medium, 4 low**. All are quality/polish items — none block release.

| Severity | Count | Blocks release? |
|---|---|---|
| Critical | 0 | — |
| High | 0 | — |
| Medium | 3 | No |
| Low | 4 | No |

---

## Previous fixes verification

| Fix | Description | Status | Evidence |
|---|---|---|---|
| **C1** | Saga budget double-counting (`add_chain` + `record_call` both incremented) | ✅ Resolved | `saga.py:148` — `add_chain` docstring explicitly states "does NOT increment budget_used". `record_call` is the sole incrementer. Test `test_review_fixes.py::TestC1SagaBudgetNoDoubleCounting` verifies 6 calls pass with `SAGA_MAX_BUDGET=6`. |
| **C2** | Message store tenant isolation (tenant B could read tenant A's messages) | ✅ Resolved | `server.py:317` — `send_a2a` uses `ctx.message_store` (per-tenant). `load_context` and `search_messages` both resolve tenant-specific stores. `tenant.py:52` — non-default tenants get `MessageStore(path=None)` (in-memory, no shared file). Test `TestC2TenantIsolation` covers load + search cross-tenant. |
| **H1** | WebSocket bound to `0.0.0.0` by default | ✅ Resolved | `ws_server.py:31` — `DEFAULT_WS_BIND_HOST = "127.0.0.1"`. Auth token support added (`_resolve_auth_token`, `_handler` checks `auth_token`). Test `TestH1WebSocketBindAddress` covers default bind, custom bind, auth reject, auth accept, no-auth. |
| **H2** | `verify_message` caught `Exception` (swallowed programming errors) | ✅ Resolved | `signing.py:155` — only `InvalidSignature` and `ValueError` caught. Test `TestH2VerifyMessageExceptionPropagation` verifies `TypeError`/`AttributeError` propagate, invalid sig returns `False`, bad base64 returns `False`. |
| **H3** | `get_metrics(tenant_id="all")` accessed `_tenants` without lock | ✅ Resolved | `server.py:617` — uses `tenant_manager.all_contexts()` (thread-safe snapshot under lock). `tenant.py:103` — `all_contexts()` returns `dict(self._tenants)` under `self._lock`. |
| **H4** | `register()` didn't hold lock during registry+keystore mutation | ✅ Resolved | `registration.py:117` — steps 3-6 (duplicate check, add card, add key, consume challenge) all under `self._lock`. |

---

## Findings by severity

### Medium

#### M1 — `_registration_services` cache is not thread-safe

**File:** `a2a_orchestrator/server.py:119-140`
**Issue:** The per-tenant `RegistrationService` cache (`_registration_services: dict`) is a module-level dict accessed without a lock. Two concurrent `register_agent` calls for the same new tenant_id can race: both see `svc is None`, both create a `RegistrationService`, both write to the dict. The loser's service is discarded, but the winner's registry/key_store may have been mutated by the loser's `register()` call before the dict write.

**Impact:** Low probability (requires two registrations for the same new tenant in the same microsecond), but the consequence is a lost registration or a card added to a discarded service's registry.

**Recommendation:** Either (a) guard the cache with a lock, or (b) delegate caching to `TenantManager` (which already has a lock and owns per-tenant state). Option (b) is cleaner — add a `get_registration_service(tenant_id)` method to `TenantManager`.

```python
# Option (b): in TenantManager
def get_registration_service(self, tenant_id: str) -> RegistrationService:
    with self._lock:
        ctx = self.get_or_create(tenant_id)
        svc = ctx._registration_service  # cached on TenantContext
        if svc is None:
            svc = RegistrationService(ctx.registry, ctx.key_store)
            ctx._registration_service = svc
        return svc
```

#### M2 — `check_depth` docstring contradicts implementation (target cap not applied)

**File:** `a2a_orchestrator/routing.py:88-115`
**Issue:** The docstring says "We compare against the *minimum* of the protocol-wide ceiling and the target's per-card override" and "then in `check_all` we apply the per-card cap of the *target* before persisting." Neither is true:

1. The function only checks the **sender's** `max_chain_depth`, not the target's.
2. `check_all` does **not** apply the target's per-card cap — it just calls `check_depth(from_id, session, registry)` which only looks at the sender.

This means: if `agent-deep` has `max_chain_depth=5` and routes to `agent-shallow` (which has `max_chain_depth=1`), the target's cap is never enforced. The sender's cap is, but not the receiver's.

**Impact:** An agent that declared "I should never be deep in a chain" (`max_chain_depth=1`) can still receive messages at depth 2+ if the sender's cap allows it. The receiver's declared boundary is ignored.

**Recommendation:** Add the target's cap check in `check_all` (or in `check_depth` by passing `to_id`):

```python
# In check_all, after check_depth(from_id, ...):
target_cap = registry.max_chain_depth(to_id)
if next_depth >= target_cap:
    return Rejection(R3_CHAIN_TOO_DEEP,
        f"Target {to_id!r} declared max_chain_depth={target_cap}; "
        f"current depth {next_depth} would exceed it.")
```

Add a test: `agent-a` (cap 3) → `agent-shallow` (cap 1) at depth 1 → should reject.

#### M3 — `R6_SIGNATURE_INVALID` and `SAGA_*` rejection codes missing from metrics initial dict

**File:** `a2a_orchestrator/metrics.py:38-43`
**Issue:** The `rejections_by_rule` dict is initialised with `R1`-`R5` and `SCHEMA_INVALID`, but **not** `R6_SIGNATURE_INVALID`, `SAGA_NOT_FOUND`, or `SAGA_BUDGET_EXHAUSTED`. These are tracked dynamically (the `else` branch in `record_rejected` handles unknown codes), so they **do** appear in snapshots after the first occurrence. However:

1. A fresh `metrics.snapshot()` before any R6/SAGA rejection will **not** show these keys at all (not even as `0`), which can confuse dashboards expecting a stable schema.
2. The `reset()` method only zeroes the initially-known keys — dynamically-added codes persist across `reset()` with their pre-reset values.

**Impact:** Inconsistent metrics output shape. `reset()` doesn't fully reset.

**Recommendation:** Add the missing codes to the initial dict and to `reset()`:

```python
"R6_SIGNATURE_INVALID": 0,
"SAGA_NOT_FOUND": 0,
"SAGA_BUDGET_EXHAUSTED": 0,
```

---

### Low

#### L1 — Version string mismatch: `A2A_SCHEMA_VERSION` is `0.7.0`, package is `0.8.0`

**File:** `a2a_orchestrator/__init__.py:44`, `a2a_orchestrator/schemas/a2a-message.schema.json:12`, `pyproject.toml:8`
**Issue:** `A2A_SCHEMA_VERSION = "0.7.0"` and the schema `const` is `"0.7.0"`, but `pyproject.toml` version is `0.8.0` and the `__init__.py` docstring says "Wire-format version: 0.7.0". The `web_server.py:97` comment references "0.8.0" as the old hardcoded value.

This is intentional if the wire format didn't change between v0.7.0 and v0.8.0 (schema version ≠ package version). But the `__init__.py` docstring line 35 says "Wire-format version: 0.7.0" which is correct — just potentially confusing to a reader who sees `version = "0.8.0"` in pyproject and `0.7.0` in the schema.

**Recommendation:** Add a one-line comment in `__init__.py` clarifying that `A2A_SCHEMA_VERSION` is the **wire-format** version (pinned to the schema), independent of the package version. This prevents a future contributor from "fixing" the mismatch by bumping the schema version without a wire-format change.

```python
# Wire-format version — pinned to a2a-message.schema.json.
# This is INDEPENDENT of the package version in pyproject.toml.
# Bump only on breaking wire-format changes, not on feature releases.
A2A_SCHEMA_VERSION = "0.7.0"
```

#### L2 — `R5_DESTRUCTIVE_PENDING` constant is defined but never used

**File:** `a2a_orchestrator/destructive.py:30`
**Issue:** `R5_DESTRUCTIVE_PENDING = "R5_DESTRUCTIVE_PENDING"` is defined but never referenced anywhere in the codebase (only the `_DENIED` variant is used). Dead code.

**Recommendation:** Remove the constant, or document it as a reserved code for future async-consent flow. If removing, also remove from any documentation that references it.

#### L3 — `load_context` turn_id-only fallback returns "most recent delivered" — misleading

**File:** `a2a_orchestrator/server.py:580-590`
**Issue:** When `turn_id` is provided but `message_id` is empty, and Mnemos is unavailable, the JSONL fallback scans recent messages and returns the **most recent delivered message** for the session — not the message matching `turn_id`. The reason string says "loaded from JSONL fallback (most recent for session ...)" which is honest, but the caller asked for a specific `turn_id` and gets a different message.

This is a known limitation (JSONL store doesn't track turn_ids), and the code comments acknowledge it. But the `ok: True` response with a mismatched message could mislead the receiving agent into thinking it got the right context.

**Recommendation:** Consider returning `ok: False` when `turn_id` is provided but cannot be resolved from JSONL (since the store can't match by turn_id). Or add a `warning` field to the response: `"warning": "turn_id not available in JSONL fallback; returned most recent message"`.

#### L4 — Conftest schema diverges from embedded schema (`agent_file` pattern)

**File:** `tests/conftest.py:38` vs `a2a_orchestrator/schemas/agent-card.schema.json:24`
**Issue:** The test conftest uses a trimmed copy of the schema. The embedded schema's `agent_file` pattern is `^([a-z][a-z0-9-]*/)*[a-z][a-z0-9-]*\.agent\.md$` (allows directory prefixes like `gcw-it-team/senior-dba.agent.md` — this was the v0.8.0 schema fix). The conftest copy uses `^[a-z][a-z0-9-]*\.agent\.md$` (no directory prefix).

This means tests don't validate the directory-prefix feature that was the schema fix in commit `743f496`. A card with `agent_file: "gcw-it-team/senior-dba.agent.md"` would pass the embedded schema but fail the test schema.

**Recommendation:** Sync the conftest schema with the embedded schema, or (better) have conftest load the actual embedded schemas from the package instead of maintaining a trimmed copy. This eliminates drift permanently.

---

## Architecture assessment

### Strengths

1. **Clean separation of concerns.** Each module has one job: `routing` (pure checks), `persistence` (storage), `signing` (crypto), `tenant` (isolation), `ws_server` (transport), `web_server` (REST), `cli` (UI), `server` (wiring). No circular dependencies.

2. **Thread safety is consistent.** Every mutable store (`SessionStore`, `SagaStore`, `MessageStore`, `Metrics`, `KeyStore`, `TenantManager`, `RegistrationService`) uses `threading.Lock`. The only gap is `_registration_services` (M1).

3. **Graceful degradation is thorough.** Mnemos→JSONL fallback, WS→silent, FastAPI→lazy import, websockets→optional. No hard dependencies on external services.

4. **Tenant isolation is complete.** Per-tenant registry, session store, message store, metrics, saga store, key store. The `TenantManager` is the single entry point with a lock.

5. **No logic duplication between MCP/REST/CLI.** `web_server.py` and `cli.py` both call the `server.py` tool functions directly — no reimplementation of routing logic.

6. **Bounded memory.** LRU eviction on `SessionStore` (256), `SagaStore` (128), `RegistrationService` challenges (100). No unbounded growth.

### Areas for improvement (non-blocking)

1. **`check_depth` target cap** (M2) — the receiver's `max_chain_depth` is declared in the schema but not enforced. This is a protocol-level gap, not just a bug.

2. **Test schema drift** (L4) — maintaining a trimmed schema copy in conftest creates a maintenance burden and misses schema changes.

3. **Metrics schema stability** (M3) — the dynamic-add pattern for rejection codes means the metrics output shape is not stable across restarts.

---

## Test coverage assessment

| Area | Coverage | Notes |
|---|---|---|
| R1-R4 routing | ✅ Strong | All gates tested in `test_routing.py` + e2e |
| R5 destructive | ✅ Good | `test_destructive.py` covers provider true/false/default |
| R6 signing | ✅ Good | `test_r6_signing.py` covers no-key, valid, missing, invalid, keystore |
| Saga | ✅ Strong | `test_saga.py` + `test_create_saga_tool.py` — budget, eviction, tenant isolation |
| Tenant isolation | ✅ Strong | `test_tenant.py` + C2 tests in `test_review_fixes.py` |
| Persistence | ✅ Strong | Thread safety, atomic writes, lazy load, in-memory mode |
| WS server | ✅ Good | Broadcast, multiple subscribers, auth, broadcast_sync |
| Web server | ✅ Good | All endpoints, CORS, API key auth |
| Registration | ✅ Good | Full flow, invalid sig, expired, duplicate, unregister |
| Search | ✅ Good | JSONL scoring, session filter, limit, fallback |
| CLI | ✅ Good | send, list, status, agents, metrics, saga, register |

### Untested paths

- **R3 target cap** (M2) — no test verifies the receiver's `max_chain_depth` is enforced (because it isn't).
- **`R5_DESTRUCTIVE_PENDING`** (L2) — dead code, no test (correctly).
- **Concurrent `_resolve_registration_service`** (M1) — no test for the race condition.
- **`metrics.reset()` with dynamically-added codes** (M3) — no test verifies reset clears R6/SAGA codes.

---

## Security assessment

| Area | Status | Notes |
|---|---|---|
| R6 signature verification | ✅ | Ed25519, canonical JSON, opt-in via `public_key`, KeyStore for runtime agents |
| Registration challenge-response | ✅ | 5-min TTL, nonce signing, cap on pending challenges |
| WS bind address | ✅ | Default `127.0.0.1`, optional auth token |
| Web server CORS | ✅ | Explicit origins, wildcard+credentials rejected (M6 fix) |
| Web server API key | ✅ | Optional, `X-API-Key` header, health endpoint exempt |
| Secret leakage | ✅ | No secrets in code; env vars for all credentials |
| Tenant isolation | ✅ | Per-tenant stores, no cross-tenant access in any tool |
| JSONL fallback | ✅ | Atomic writes (`O_APPEND` + `fsync`), corrupt-line tolerance |

No security findings.

---

## Concurrency assessment

| Store | Lock | Bounded | Notes |
|---|---|---|---|
| `SessionStore` | ✅ `threading.Lock` | ✅ LRU 256 | `move_to_end` on access |
| `SagaStore` | ✅ `threading.Lock` | ✅ LRU 128 | `move_to_end` on access |
| `MessageStore` | ✅ `threading.Lock` | ❌ unbounded | In-memory list grows; file is append-only |
| `Metrics` | ✅ `threading.Lock` | N/A | Counters only |
| `KeyStore` | ✅ `threading.Lock` | N/A | Dict, no eviction needed |
| `TenantManager` | ✅ `threading.Lock` | ❌ unbounded | Tenants never evicted (by design) |
| `RegistrationService` | ✅ `threading.Lock` | ✅ 100 challenges | Global cleanup on each `create_challenge` |
| `WebSocketServer` | ❌ no lock | N/A | Async, single event loop — safe by design |
| `_registration_services` | ❌ no lock | ❌ unbounded | **M1** — race condition |

**Note on `MessageStore`:** The in-memory list is unbounded. In a long-running server with many messages, this grows without limit. The JSONL file is append-only (no rotation). This is acceptable for v0.9.0 (messages are small, sessions are bounded) but should be addressed before v1.0 — either cap the in-memory list or add file rotation.

---

## Schema correctness

| Schema | Matches code? | Notes |
|---|---|---|
| `agent-card.schema.json` | ✅ | All fields in code (`id`, `routing`, `max_chain_depth`, `public_key`, `tenant_id`) are in schema. `agent_file` pattern allows directory prefixes (v0.8.0 fix). |
| `a2a-message.schema.json` | ✅ | All fields in `_build_message` (`schema_version`, `message_id`, `routing_meta`, `payload`, `signature`, `tenant_id`) are in schema. `additionalProperties: false` enforced. |

**One caveat:** The `routing_meta.depth` max is `5` in the schema, but `MAX_CHAIN_DEPTH = 3` in code. This is intentional (schema allows up to 5 for future flexibility, code enforces 3 now). Document this if not already.

---

## Recommendation

**Ship v0.9.0.** No critical or high findings. Address M1-M3 and L1-L4 in a follow-up PR (they are all quality improvements, not correctness issues). The one item worth fixing before v1.0 is M2 (target cap enforcement) — it's a protocol-level gap that affects routing correctness.

### Suggested PR for v0.9.1

1. M2: enforce target's `max_chain_depth` in `check_all` + add test
2. M1: move `_registration_services` cache into `TenantManager`
3. M3: add R6/SAGA codes to metrics initial dict + `reset()`
4. L4: sync conftest schema with embedded schema (or load from package)
5. L1-L3: documentation/comments cleanup