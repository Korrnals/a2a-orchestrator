# Getting Started

Install, configure, and send your first A2A message in under 5 minutes.

## Prerequisites

- Python 3.11+
- (Optional) [Mnemos](https://github.com/Korrnals/mnemos) running for durable storage
- Agent Card JSON files describing your agents

## Install

### One-liner (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/Korrnals/a2a-orchestrator/main/scripts/install.sh | bash
```

The install script:

- Creates a venv at `~/.a2a-orchestrator/venv`
- Installs the package from GitHub
- Creates a launcher in `~/.local/bin/a2a-orchestrator`
- Optionally registers in VS Code `mcp.json` (prompts unless `--mcp`)

Install options:

```bash
# Specific version
curl -fsSL .../install.sh | bash -s -- --version 1.0.0

# Auto-setup MCP (no prompt)
curl -fsSL .../install.sh | bash -s -- --mcp

# No venv (system Python)
curl -fsSL .../install.sh | bash -s -- --no-venv
```

### Manual (development checkout)

```bash
git clone https://github.com/Korrnals/a2a-orchestrator.git
cd a2a-orchestrator
pip install -e .

# Optional: web server dependencies (FastAPI + uvicorn)
pip install -e ".[web]"
```

## Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/Korrnals/a2a-orchestrator/main/scripts/uninstall.sh | bash
```

Removes the venv, the launcher, and the `mcp.json` entry.

## Configure

All settings are environment variables. Schemas are embedded — no
external schema directory needed. Agent Cards are auto-detected from
`a2a/agents/` in development checkouts.

```bash
export A2A_CARDS_DIR=/path/to/agent/cards
export MNEMOS_BASE_URL=http://127.0.0.1:8787
```

See [Configuration](configuration.md) for the full env-var reference.

## Register in VS Code

Add the server to your `mcp.json`:

```json
{
  "servers": {
    "a2a-orchestrator": {
      "command": "python3",
      "args": ["-m", "a2a_orchestrator"],
      "env": {
        "A2A_CARDS_DIR": "/path/to/agent/cards",
        "MNEMOS_BASE_URL": "http://127.0.0.1:8787"
      }
    }
  }
}
```

After editing, reload the window
(**Ctrl+Shift+P → Developer: Reload Window**) so the MCP host re-reads
the config.

## First A2A message

Once the server is registered, an agent calls `send_a2a`:

```python
send_a2a(
    target="agent-dba",
    reason="Task requires database expertise",
    summary="User needs a migration for the orders table",
    key_decisions=["add column, not a new table"],
    open_questions=["should the new column be indexed?"],
    from_id="agent-tech-lead",
    session_id="conv-001",
)
# → {ok: true, reason: "delivered", next_senior: "agent-dba",
#    message_id: "msg-a1b2c3d4e5f6"}
```

The receiving agent reads the message with `load_context`:

```python
load_context(session_id="conv-001", message_id="msg-a1b2c3d4e5f6")
```

## Verify it works

```bash
# CLI smoke test — send + list
a2a-orchestrator send --from agent-a --to agent-b \
  --reason "smoke test" --summary "hello" --session-id test-001
a2a-orchestrator list --session-id test-001

# Check chain status
a2a-orchestrator status --session-id test-001
```

## Next steps

- [Tools Reference](tools-reference.md) — all 11 MCP tools
- [Routing Rules](routing-rules.md) — R1–R6 explained
- [Architecture](architecture.md) — how the pieces fit together
- [Testing](testing.md) — e2e and unit test results