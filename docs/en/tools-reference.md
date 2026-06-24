# Tools Reference

The server exposes **11 MCP tools**. Agents call them to route
messages, load context, inspect state, search, and manage tenants and
external agents.

## `send_a2a`

Route a structured A2A message from one agent to another. Runs R1–R6,
persists the message, updates session chain/budget, optionally tracks
saga state, and broadcasts a WebSocket event.

```python
send_a2a(
    target: str,               # A2A id of the receiving agent
    reason: str,               # 10–500 chars — why the handoff
    summary: str,              # 20–2000 chars — what was done / found
    key_decisions: list[str] = [],       # decisions already made
    open_questions: list[str] = [],      # things the receiver must resolve
    artifacts: list[dict] = [],          # {kind, pointer} — files, diffs, memory
    intent: str = "handoff",             # see intent table below
    session_id: str = "",                # conversation id (auto-generated if empty)
    from_id: str = "",                   # A2A id of the calling agent
    saga_id: str = "",                   # optional saga id (saga must exist)
    signature: str = "",                 # base64 Ed25519 signature (R6)
    tenant_id: str = "default",          # tenant id for multi-tenant isolation
) -> dict
```

### Return value

| Field | Type | Present on | Description |
| --- | --- | --- | --- |
| `ok` | `bool` | always | `True` if delivered, `False` if rejected |
| `reason` | `str` | always | `"delivered"` or a human-readable rejection reason |
| `next_senior` | `str` | success | A2A id of the receiving agent |
| `message_id` | `str` | always | Unique id (`msg-<hex>`), even for rejected messages |
| `code` | `str` | rejection | Stable rejection code (e.g. `R1_NOT_WHITELISTED`) |

Rejected messages are **still persisted** (with `outcome: "rejected"`)
so the audit trail is complete.

### Intents

| Intent | When to use |
| --- | --- |
| `handoff` | Transfer ownership of the task (default) |
| `request-info` | Ask a question, keep ownership |
| `share-finding` | Report a result upstream |
| `request-review` | Ask for a review of work done |
| `request-implementation` | Ask another agent to implement |
| `request-documentation` | Ask another agent to write docs |
| `destructive-action-request` | Triggers R5 — requires user consent |

### Example

```python
send_a2a(
    target="agent-dba",
    reason="Task requires database expertise",
    summary="User needs a migration for the orders table",
    key_decisions=["add column, not a new table"],
    open_questions=["should the new column be indexed?"],
    artifacts=[{"kind": "file", "pointer": "src/models/orders.py"}],
    intent="handoff",
    from_id="agent-tech-lead",
    session_id="conv-001",
)
```

## `create_saga`

Create a new saga for long-lived multi-chain dialog state. A saga
allows multiple A2A chains to share budget and state across a single
logical task. Budget per saga: 6 calls.

```python
create_saga(
    root_session_id: str,      # session id that initiated the saga
    metadata: str = "",         # optional JSON string of free-form metadata
    tenant_id: str = "default", # tenant id
) -> dict
# → {ok: true, saga_id: "saga-<hex>", reason: "created"}
```

## `load_context`

Load an A2A message by `turn_id` or `message_id`. Used by the
receiving agent to read the message that was routed to them.

```python
load_context(
    session_id: str,           # Mnemos session id
    turn_id: str = "",         # Mnemos turn id (takes priority)
    message_id: str = "",     # A2A message_id (used if turn_id empty)
    mode: str = "summary",     # "summary" or "full"
    tenant_id: str = "default",
) -> dict
# → {ok: true, message: {...}, reason: "loaded"}
```

## `get_chain_status`

Get the current routing chain status for a session.

```python
get_chain_status(
    session_id: str,
    tenant_id: str = "default",
) -> dict
# → {ok: true, chain: [...], depth: int, budget_used: int,
#    calls_remaining: int, recent_messages: [...]}
```

## `get_metrics`

Return the orchestrator's metrics counters.

```python
get_metrics(tenant_id: str = "default") -> dict
# tenant_id="all" returns metrics for all tenants
# → {messages_delivered, messages_rejected, rejections_by_rule,
#    mnemos_writes, fallback_writes, active_sessions, total_sessions}
```

## `get_saga_status`

Get the status of a saga by its id.

```python
get_saga_status(
    saga_id: str,
    tenant_id: str = "default",
) -> dict
# → {ok: true, saga: {saga_id, state, chains, budget_used, ...}}
```

## `search_messages`

Search A2A messages by query (substring match with scoring).

```python
search_messages(
    query: str,                # space-separated terms
    session_id: str = "",       # scope to session if provided
    limit: int = 10,            # max results
    tenant_id: str = "default",
) -> dict
# → {ok: true, results: [{message, score, session_id, message_id}], count: N}
```

## `create_registration_challenge`

Create a registration challenge for an external agent. Returns a nonce
that the agent must sign with their Ed25519 private key.

```python
create_registration_challenge(
    agent_id: str,
    tenant_id: str = "default",
) -> dict
# → {ok: true, challenge: "<nonce>", reason: "created"}
```

## `register_agent`

Register an external agent with challenge-response verification.

```python
register_agent(
    agent_card: str,           # JSON string of the Agent Card
    public_key: str,           # base64 Ed25519 public key
    challenge_signature: str,  # base64 signature of the challenge nonce
    tenant_id: str = "default",
) -> dict
# → {ok: true, agent_id: "...", reason: "registered"}
```

## `unregister_agent`

Unregister an externally-registered agent.

```python
unregister_agent(
    agent_id: str,
    tenant_id: str = "default",
) -> dict
# → {ok: true, reason: "unregistered"}
```

## `list_tenants`

List all tenants and their statistics.

```python
list_tenants() -> dict
# → {ok: true, tenants: [...], count: N}
```

## See also

- [Routing Rules](routing-rules.md) — R1–R6 gates
- [Saga Pattern](saga-pattern.md) — multi-chain state
- [Signed Messages](signed-messages.md) — Ed25519 and R6
- [CLI Reference](cli-reference.md) — same functions from the command line