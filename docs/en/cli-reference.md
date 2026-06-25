# CLI Reference

The `a2a-cli` CLI wraps the same internal functions as the
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
a2a-cli send --from agent-a --to agent-b \
  --reason "Task requires database expertise" \
  --summary "User needs a migration for the orders table" \
  --session-id conv-001
```

### List recent messages

```bash
a2a-cli list --session-id conv-001 --limit 10
```

### Chain status

```bash
a2a-cli status --session-id conv-001
```

### List registered agents

```bash
a2a-cli agents
```

### Metrics counters

```bash
a2a-cli metrics
```

### Start the MCP server

```bash
# Same as python3 -m a2a_orchestrator
a2a-cli serve

# MCP + WebSocket
a2a-cli serve --ws

# MCP + WebSocket + Web server
a2a-cli serve --all --web-host 127.0.0.1 --web-port 8789
```

### Start the web/HTTP server only

```bash
a2a-cli web --host 127.0.0.1 --port 8789
```

### Monitor WebSocket events

```bash
a2a-cli ws-monitor --session-id conv-001
```

### Search messages

```bash
a2a-cli search "orders migration" --limit 5
```

### Saga management

```bash
a2a-cli saga list --status active
a2a-cli saga status saga-abc123
```

### Register an external agent

Two-step flow: challenge, then sign + submit.

```bash
# Step 1: get the challenge nonce
a2a-cli register --agent-card card.json --public-key key.b64

# Step 2: sign the nonce and submit
a2a-cli register --agent-card card.json --public-key key.b64 --signature <sig>
```

### List tenants

```bash
a2a-cli tenants list
```

## See also

- [Tools Reference](tools-reference.md) — the MCP tool equivalents
- [Configuration](configuration.md) — env vars
- [External Agents](external-agents.md) — registration flow