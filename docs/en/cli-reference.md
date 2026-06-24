# CLI Reference

The `a2a-orchestrator` CLI wraps the same internal functions as the
MCP tools. Useful for scripting, debugging, and smoke-testing without
an MCP client.

Uses `argparse` (no extra dependency) so the CLI works in any Python
3.11+ environment without installing additional packages.

## Commands

| Command | Purpose |
| --- | --- |
| `send` | Send an A2A message |
| `list` | List recent messages for a session |
| `status` | Chain status for a session |
| `agents` | List registered agents |
| `metrics` | Metrics counters |
| `serve` | Start MCP server (`--ws`, `--all`) |
| `web` | Start web/HTTP server |
| `ws-monitor` | Monitor WebSocket events |
| `search` | Search A2A messages |
| `saga` | Saga management (`list`, `status`) |
| `register` | Register an external agent |
| `tenants` | Tenant management (`list`) |

## Examples

### Send a message

```bash
a2a-orchestrator send --from agent-a --to agent-b \
  --reason "Task requires database expertise" \
  --summary "User needs a migration for the orders table" \
  --session-id conv-001
```

### List recent messages

```bash
a2a-orchestrator list --session-id conv-001 --limit 10
```

### Chain status

```bash
a2a-orchestrator status --session-id conv-001
```

### List registered agents

```bash
a2a-orchestrator agents
```

### Metrics counters

```bash
a2a-orchestrator metrics
```

### Start the MCP server

```bash
# Same as python3 -m a2a_orchestrator
a2a-orchestrator serve

# MCP + WebSocket
a2a-orchestrator serve --ws

# MCP + WebSocket + Web server
a2a-orchestrator serve --all --web-host 127.0.0.1 --web-port 8789
```

### Start the web/HTTP server only

```bash
a2a-orchestrator web --host 127.0.0.1 --port 8789
```

### Monitor WebSocket events

```bash
a2a-orchestrator ws-monitor --session-id conv-001
```

### Search messages

```bash
a2a-orchestrator search "orders migration" --limit 5
```

### Saga management

```bash
a2a-orchestrator saga list --status active
a2a-orchestrator saga status saga-abc123
```

### Register an external agent

Two-step flow: challenge, then sign + submit.

```bash
# Step 1: get the challenge nonce
a2a-orchestrator register --agent-card card.json --public-key key.b64

# Step 2: sign the nonce and submit
a2a-orchestrator register --agent-card card.json --public-key key.b64 --signature <sig>
```

### List tenants

```bash
a2a-orchestrator tenants list
```

## See also

- [Tools Reference](tools-reference.md) — the MCP tool equivalents
- [Configuration](configuration.md) — env vars
- [External Agents](external-agents.md) — registration flow