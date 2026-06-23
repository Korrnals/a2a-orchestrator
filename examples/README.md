# Examples — A2A Orchestrator

This directory contains example Agent Cards and configuration for using
the A2A orchestrator with **your own agents** (not GCW-specific).

## What is an Agent Card?

An Agent Card is a JSON file that describes:

- **Who** the agent is (`id`, `name`, `description`).
- **What** they can do (`capabilities`).
- **Who** can route to them (`routing.accepts_routes_from`).
- **What keywords** suggest this agent (`routing.routing_keywords`).
- **How deep** they can be in a chain (`max_chain_depth`, default 3).

The card is the contract that lets the orchestrator route messages
between agents.

## Creating Agent Cards for your project

1. Create a directory for your cards (e.g. `agent-cards/`).
2. Write one JSON file per agent. See `agent-cards/` for examples.
3. Point the orchestrator at your cards directory:

```bash
# Via env var:
export A2A_CARDS_DIR=/path/to/your/agent-cards

# Or in your mcp.json (see mcp.json example):
# "env": { "A2A_CARDS_DIR": "/path/to/your/agent-cards" }
```

4. Start the orchestrator:

```bash
python3 -m a2a_orchestrator
```

## Agent Card schema

The full schema is at `a2a_orchestrator/schemas/agent-card.schema.json`.
Key fields:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Kebab-case identifier (e.g. `agent-backend`) |
| `name` | string | yes | Display name |
| `version` | string | yes | Semver version |
| `plugin` | string | yes | Owning plugin/namespace |
| `agent_file` | string | yes | Path to agent definition file |
| `capabilities` | array | yes | List of capability strings |
| `routing.accepts_routes_from` | array | yes | Whitelist of allowed senders |
| `routing.routing_keywords` | array | yes | Keywords for routing |
| `max_chain_depth` | int | no | Override global max depth (default 3) |

## Routing rules

The orchestrator applies 5 checks (R1-R5) before delivering a message:

| Rule | Check | Rejection code |
| --- | --- | --- |
| R1 | Sender → target is in the whitelist | `R1_NOT_WHITELISTED` |
| R2 | Target is not already upstream in the chain | `R2_LOOP_DETECTED` |
| R3 | Chain depth ≤ max (3 by default) | `R3_CHAIN_TOO_DEEP` |
| R4 | Budget (3 calls per session) not exhausted | `R4_BUDGET_EXHAUSTED` |
| R5 | Destructive actions require user consent | `R5_DESTRUCTIVE_DENIED` |

## Example: routing between three agents

```
agent-backend → agent-database → agent-qa
```

1. `agent-backend` sends a message to `agent-database` (DBA accepts
   routes from backend).
2. `agent-database` sends a message to `agent-qa` (QA accepts routes
   from database).
3. Chain: `[agent-backend, agent-database, agent-qa]` — depth 3, budget
   exhausted. No further routing allowed.

## mcp.json example

See `mcp.json` for a minimal VS Code MCP server registration. Copy it
to your VS Code `mcp.json` and adjust the `A2A_CARDS_DIR` path.