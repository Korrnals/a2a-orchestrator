# Configuration

All settings are environment variables. The `A2A_*` names are primary;
the old `GCW_*` names are accepted as backward-compat fallbacks.

## Environment variables

| Env var | Legacy fallback | Default | Purpose |
| --- | --- | --- | --- |
| `A2A_CARDS_DIR` | `GCW_CARDS_DIR` | auto-detect | Directory with Agent Card JSON files (`a2a/agents/*.json`) |
| `A2A_SCHEMA_DIR` | `GCW_SCHEMA_DIR` | embedded | Directory containing `agent-card.schema.json` and `a2a-message.schema.json` |
| `A2A_FALLBACK_JSONL` | `GCW_A2A_FALLBACK_JSONL` | `~/.a2a/a2a-messages.jsonl` | JSONL fallback file path |
| `MNEMOS_BASE_URL` | — | `http://127.0.0.1:8787` | Mnemos REST API base URL |
| `A2A_ORCHESTRATOR_LOG_LEVEL` | `GCW_ORCHESTRATOR_LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, …) |
| `A2A_WS_PORT` | — | `8788` | WebSocket server port |
| `A2A_WEB_CORS_ORIGINS` | — | `http://localhost,http://127.0.0.1` | Comma-separated CORS origins for the web server |
| `A2A_WEB_API_KEY` | — | *(unset = no auth)* | API key for web server (`X-API-Key` header) |

## Auto-detection

### `A2A_CARDS_DIR`

1. The env var itself, if set.
2. `a2a/agents` under any parent of the package directory (in-tree dev).

In production, always set `A2A_CARDS_DIR` explicitly — don't rely on
auto-detection.

### `A2A_SCHEMA_DIR`

1. The env var itself, if set.
2. Embedded schemas at `a2a_orchestrator/schemas/` (default — no
   external directory needed).
3. `docs/a2a/schemas/` under any parent of the package directory (last
   resort for in-tree dev checkouts).

## VS Code `mcp.json` setup

```json
{
  "servers": {
    "a2a-cli": {
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

> **Distrobox / sandbox note.** If you use an `envFile`, always
> specify an **absolute** path — `~/` resolves against the MCP host's
> root namespace, not the user's `$HOME`.

## Minimal config (no Mnemos)

The orchestrator works without Mnemos — messages fall back to the
local JSONL file. This is enough for a single-machine setup:

```bash
export A2A_CARDS_DIR=/path/to/agent/cards
python3 -m a2a_orchestrator
```

## Full config (with web server)

```bash
export A2A_CARDS_DIR=/path/to/agent/cards
export MNEMOS_BASE_URL=http://127.0.0.1:8787
export A2A_WS_PORT=8788
export A2A_WEB_CORS_ORIGINS=https://my-app.example.com
export A2A_WEB_API_KEY=secret-key-here
a2a-cli serve --all
```

## See also

- [Getting Started](getting-started.md) — first steps
- [REST API](rest-api.md) — web server endpoints
- [WebSockets](websockets.md) — WS server config