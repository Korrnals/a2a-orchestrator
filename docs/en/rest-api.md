# REST API

A FastAPI REST wrapper mirrors the MCP tools over HTTP, so non-VS Code
runtimes (CLI, web apps, external services) can use the orchestrator.

## Server properties

| Property | Value |
| --- | --- |
| Default port | `8789` |
| Dependencies | `pip install -e ".[web]"` (fastapi + uvicorn) |
| CORS | `A2A_WEB_CORS_ORIGINS` (comma-separated) |
| Auth | `A2A_WEB_API_KEY` (`X-API-Key` header; unset = no auth) |

## Endpoints

| Method | Path | Maps to |
| --- | --- | --- |
| `GET` | `/health` | Health check |
| `POST` | `/v1/send` | `send_a2a` |
| `GET` | `/v1/context/{session_id}/{turn_id}` | `load_context` |
| `GET` | `/v1/chain/{session_id}` | `get_chain_status` |
| `GET` | `/v1/metrics` | `get_metrics` |
| `GET` | `/v1/saga/{saga_id}` | `get_saga_status` |
| `POST` | `/v1/search` | `search_messages` |
| `GET` | `/v1/agents` | List registered agents |
| `POST` | `/v1/register/challenge` | `create_registration_challenge` |
| `POST` | `/v1/register` | `register_agent` |
| `DELETE` | `/v1/register/{agent_id}` | `unregister_agent` |
| `GET` | `/v1/tenants` | `list_tenants` |

## Start the web server

```bash
# Standalone web server
a2a-cli web --host 127.0.0.1 --port 8789

# Or alongside MCP + WS
a2a-cli serve --all
```

## Examples

### Send via REST

```bash
curl -X POST http://127.0.0.1:8789/v1/send \
  -H "Content-Type: application/json" \
  -d '{
    "target": "agent-dba",
    "from_id": "agent-tech-lead",
    "reason": "Task requires database expertise",
    "summary": "User needs a migration for the orders table"
  }'
```

### With API key auth

```bash
curl -X POST http://127.0.0.1:8789/v1/send \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $A2A_WEB_API_KEY" \
  -d '{"target": "agent-dba", "from_id": "agent-a", "reason": "...", "summary": "..."}'
```

### Search messages

```bash
curl -X POST http://127.0.0.1:8789/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "orders migration", "limit": 5}'
```

### Health check

```bash
curl http://127.0.0.1:8789/health
# → {"status": "ok"}
```

## See also

- [Configuration](configuration.md) — `A2A_WEB_*` env vars
- [CLI Reference](cli-reference.md) — `web` and `serve --all` commands
- [Tools Reference](tools-reference.md) — the MCP tool equivalents