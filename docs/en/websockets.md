# WebSockets

The orchestrator can run a WebSocket server alongside the MCP stdio
server. Clients subscribe to session events and receive push
notifications when A2A messages are delivered, rejected, or chain
state changes.

## Server properties

| Property | Value |
| --- | --- |
| Default port | `8788` (`A2A_WS_PORT`) |
| Protocol | `ws://` (no TLS in the default config) |
| Optional | If `websockets` is not installed, degrades silently to no-push |

## Event types

| Event | When |
| --- | --- |
| `a2a_delivered` | An A2A message was successfully routed |
| `a2a_rejected` | An A2A message was rejected (R1–R6) |
| `chain_updated` | A session's chain/budget state changed |
| `saga_completed` | A saga was marked as completed |
| `saga_abandoned` | A saga was abandoned |

## Start with WebSocket

```bash
# MCP + WebSocket
a2a-cli serve --ws

# MCP + WebSocket + Web server
a2a-cli serve --all

# Monitor events for a session
a2a-cli ws-monitor --session-id conv-abc
```

## Event payload

Each event is a JSON object broadcast to all subscribed clients:

```json
{
  "event": "a2a_delivered",
  "session_id": "conv-abc",
  "message_id": "msg-a1b2c3d4e5f6",
  "from": "agent-tech-lead",
  "to": "agent-dba",
  "timestamp": "2026-06-24T12:00:00Z"
}
```

Rejected messages include a `code` field with the rejection reason:

```json
{
  "event": "a2a_rejected",
  "session_id": "conv-abc",
  "message_id": "msg-b2c3d4e5f6g7",
  "code": "R2_LOOP_DETECTED",
  "reason": "Target already upstream in the chain"
}
```

## Subscribe

Clients connect to `ws://localhost:8788` and filter events by
`session_id`. The `ws-monitor` CLI command is a ready-made subscriber
that prints events for a given session.

## Graceful degradation

If the `websockets` package is not installed, the orchestrator starts
without the WS server — all MCP tools still work, just without push
notifications. Install it with:

```bash
pip install websockets
```

## See also

- [Configuration](configuration.md) — `A2A_WS_PORT`
- [CLI Reference](cli-reference.md) — `serve --ws`, `ws-monitor`
- [REST API](rest-api.md) — the HTTP alternative