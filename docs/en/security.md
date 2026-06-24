# Security

The security model, threat landscape, and hardening guidance for
`a2a-orchestrator`.

## Security model

The orchestrator enforces six routing checks (R1–R6) on every
`send_a2a` call. Together they prevent the most common multi-agent
failure modes: loops, unbounded delegation, unauthorized routing, and
unsigned messages from untrusted agents.

| Control | Rule | What it prevents |
| --- | --- | --- |
| Whitelist | R1 | Unauthorized agents routing to each other |
| Loop prevention | R2 | Agents calling each other in circles |
| Depth cap | R3 | Unbounded delegation chains |
| Budget cap | R4 | Runaway call amplification |
| Signature | R6 | Impersonation in distributed deployments |
| Destructive consent | R5 | Irreversible actions without user approval |

## Threat model

| Threat | Mitigation |
| --- | --- |
| Agent impersonation | R6 — Ed25519 signature verification |
| Routing loop (A→B→A) | R2 — upstream detection in chain |
| Unbounded recursion | R3 + R4 — depth and budget caps |
| Unauthorized access | R1 — `accepts_routes_from` whitelist |
| Destructive action without consent | R5 — fail-closed consent provider |
| Cross-tenant data leak | `TenantManager` — full per-tenant isolation |
| Mnemos downtime | JSONL fallback — durable local audit trail |
| Replay of old messages | Unique `message_id` per call; nonce TTL on registration |

## Hardening

### Production deployment

- **Set `A2A_WEB_API_KEY`** — the REST wrapper has no auth by default.
  Always set an API key when exposing the web server.
- **Restrict CORS** — set `A2A_WEB_CORS_ORIGINS` to your specific
  origins, not the default `localhost`.
- **Use TLS** — the default WS and web server use plain HTTP/WS. Put
  them behind a reverse proxy (Caddy, nginx) with TLS termination.
- **Pin `A2A_CARDS_DIR`** — don't rely on auto-detection in
  production. Set the env var explicitly.

### Key management

- Generate Ed25519 keypairs with a secure RNG
  (`Ed25519PrivateKey.generate()`).
- Store private keys in a secret manager, never in the Agent Card or
  committed files.
- Rotate keys periodically; update the `public_key` field in the Agent
  Card or re-register the agent.
- The `KeyStore` holds only **public** keys — private keys never enter
  the orchestrator.

### Consent provider (R5)

The default consent provider is **fail-closed** — it denies all
destructive actions unless explicitly overridden. VS Code UI
integration can monkey-patch `consent_provider` at runtime to surface
interactive consent dialogs. Never replace it with a fail-open
provider in production.

## Sensitive data

The orchestrator does not log message payloads at `INFO` level. At
`DEBUG` level, full messages may appear in logs — use this level only
in development. See the project's
[sensitive-data policy](https://github.com/Korrnals/GithubCopilotWorkflow)
for the full redaction rules.

## See also

- [Routing Rules](routing-rules.md) — R1–R6 in detail
- [Signed Messages](signed-messages.md) — Ed25519 and R6
- [Configuration](configuration.md) — `A2A_WEB_API_KEY`, CORS