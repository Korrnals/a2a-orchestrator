# Multi-tenant

The orchestrator supports per-tenant isolation. Each tenant has its
own Agent Card registry, session store, message store, metrics, saga
store, and key store.

## Properties

| Property | Value |
| --- | --- |
| Default tenant | `"default"` (backward compat — all calls without `tenant_id` use it) |
| Isolation | Full: registry, sessions, metrics, sagas, keys |
| Management | `TenantManager` creates and caches `TenantContext` on demand |
| Cards directory | Default tenant uses `A2A_CARDS_DIR`; other tenants use `cards_dir / tenant_id` |

## Using `tenant_id`

Pass the `tenant_id` parameter on tools that support it:

| Tool | `tenant_id` param |
| --- | --- |
| `send_a2a` | `tenant_id` (default `"default"`) |
| `get_chain_status` | `tenant_id` |
| `get_metrics` | `tenant_id` (use `"all"` for all tenants) |
| `get_saga_status` | `tenant_id` |
| `search_messages` | `tenant_id` |
| `create_saga` | `tenant_id` |
| `create_registration_challenge` | `tenant_id` |
| `register_agent` | `tenant_id` |
| `unregister_agent` | `tenant_id` |

## List tenants

```python
list_tenants()
# → {ok: true, tenants: [{tenant_id, sessions, agents, ...}], count: N}
```

Or via CLI:

```bash
a2a-orchestrator tenants list
```

## TenantManager

The `TenantManager` is the central object that creates and caches
`TenantContext` instances. Each `TenantContext` bundles:

- `registry` — Agent Card registry (per-tenant cards)
- `session_store` — per-session chain/depth/budget
- `message_store` — per-tenant JSONL fallback
- `metrics` — per-tenant counters
- `saga_store` — per-tenant sagas
- `key_store` — per-tenant Ed25519 keys

The default tenant is created eagerly at import time for backward
compatibility. Other tenants are created on first access.

## Cards directory layout

```text
$A2A_CARDS_DIR/
├── agent-tech-lead.json      # default tenant
├── agent-dba.json
└── acme-corp/                # tenant "acme-corp"
    ├── agent-a.json
    └── agent-b.json
```

The default tenant loads cards from `A2A_CARDS_DIR` root. Tenant
`acme-corp` loads from `A2A_CARDS_DIR/acme-corp/`.

## See also

- [Configuration](configuration.md) — `A2A_CARDS_DIR`
- [External Agents](external-agents.md) — per-tenant registration
- [Tools Reference](tools-reference.md) — `list_tenants`