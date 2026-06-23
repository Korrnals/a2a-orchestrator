"""FastMCP server entry point and MCP tools.

This module wires together every component into MCP tools:

1. ``send_a2a`` — Build an A2A message, validate it, run R1→R2→R3→R4
   →R5 (and R6 for signed messages), persist to Mnemos or JSONL, update
   session chain/budget, optionally track saga, broadcast WS event,
   return the routing result.
2. ``load_context`` — Load an A2A message by turn_id or message_id
   (used by the receiving agent to read routed messages).
3. ``get_chain_status`` — Get the current routing chain status for a
   session (chain, depth, budget, recent messages).
4. ``get_metrics`` — Return the orchestrator's metrics counters.
5. ``get_saga_status`` — Return saga state, chains, and budget.
6. ``search_messages`` — Search A2A messages by query.
7. ``register_agent`` / ``create_registration_challenge`` /
   ``unregister_agent`` — External agent registration flow.
8. ``list_tenants`` — List all tenants and their stats.

On REJECT: the rejected message is still persisted (with ``outcome`` set
to the rejection code) so Mnemos has a complete audit trail, and the
tool returns ``{ok: False, code, reason}``.

Run the server with::

    python3 -m a2a_orchestrator

The module-level singletons (tenant manager, message store, mnemos
client, consent provider) are created once at import time so the server
is ready to serve the first tool call without warmup. Per-tenant state
(registry, session store, metrics, saga store, key store) is managed
by the ``TenantManager``.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from . import A2A_SCHEMA_VERSION
from .config import CARDS_DIR
from .destructive import (
    ConsentDenied,
    ConsentProvider,
    default_consent_provider,
    is_destructive,
    request_consent,
)
from .mnemos_client import MnemosClient, MnemosUnavailableError
from .persistence import MessageStore
from .registration import RegistrationRequest, RegistrationService
from .routing import check_all, check_signature
from .search import search_a2a_messages
from .session import MAX_BUDGET
from .tenant import DEFAULT_TENANT, TenantContext, TenantManager
from .validation import ValidationError, validate_a2a_message
from .ws_server import broadcast_event

log = logging.getLogger("a2a_orchestrator")

# --------------------------------------------------------------------------- #
# Module-level singletons — created once at import time.
# --------------------------------------------------------------------------- #

# Tenant manager: per-tenant registries, session stores, metrics, etc.
# The default tenant is created eagerly for backward compatibility.
tenant_manager = TenantManager(default_cards_dir=CARDS_DIR)
_default_ctx = tenant_manager.get_or_create(DEFAULT_TENANT)

# Backward-compat aliases: expose the default tenant's singletons at
# module level so existing tests and CLI code that reference
# ``server.registry``, ``server.session_store``, etc. still work.
registry = _default_ctx.registry
session_store = _default_ctx.session_store
metrics = _default_ctx.metrics
saga_store = _default_ctx.saga_store
key_store = _default_ctx.key_store
# C2 fix: message_store is now per-tenant (inside TenantContext). We
# keep a module-level alias to the default tenant's store for backward
# compatibility with tests and CLI code that reference
# ``server.message_store``.
message_store = _default_ctx.message_store

# Mnemos client: lazy httpx client, retry on 5xx/conn errors.
mnemos_client = MnemosClient()

# Consent provider: fail-closed by default. VS Code UI integration can
# monkey-patch this at runtime (or pass a custom provider to send_a2a).
consent_provider: ConsentProvider = default_consent_provider

# Registration service: uses the default tenant's registry + key store.
# For multi-tenant registration, use the tenant-specific service via
# _resolve_registration_service(tenant_id).
registration_service = RegistrationService(
    registry=_default_ctx.registry,
    key_store=_default_ctx.key_store,
)


def set_consent_provider(provider: ConsentProvider) -> None:
    """Override the global consent provider (for VS Code UI integration)."""
    global consent_provider
    consent_provider = provider


def _resolve_tenant(tenant_id: str) -> TenantContext:
    """Return the TenantContext for ``tenant_id``, creating it if needed."""
    if tenant_id == DEFAULT_TENANT:
        return _default_ctx
    return tenant_manager.get_or_create(tenant_id)


# Per-tenant RegistrationService cache (M2 fix). Each tenant gets its
# own RegistrationService bound to that tenant's registry + key store.
_registration_services: dict[str, RegistrationService] = {}


def _resolve_registration_service(tenant_id: str) -> RegistrationService:
    """Return the RegistrationService for ``tenant_id``, creating it if needed.

    Each tenant gets its own RegistrationService bound to that tenant's
    registry + key store so externally-registered agents are isolated
    per tenant.
    """
    if tenant_id == DEFAULT_TENANT:
        return registration_service
    svc = _registration_services.get(tenant_id)
    if svc is None:
        ctx = _resolve_tenant(tenant_id)
        svc = RegistrationService(
            registry=ctx.registry,
            key_store=ctx.key_store,
        )
        _registration_services[tenant_id] = svc
    return svc


# --------------------------------------------------------------------------- #
# MCP server + tools
# --------------------------------------------------------------------------- #

mcp = FastMCP("a2a-orchestrator")


def _build_message(
    *,
    target: str,
    reason: str,
    summary: str,
    key_decisions: list[str],
    open_questions: list[str],
    artifacts: list[dict[str, Any]],
    intent: str,
    session_id: str,
    from_id: str,
    session_chain: list[str],
    depth: int,
    calls_remaining: int,
    saga_id: str = "",
    signature: str = "",
    tenant_id: str = DEFAULT_TENANT,
) -> dict[str, Any]:
    """Construct the A2A message dict from tool arguments + session state."""
    msg: dict[str, Any] = {
        "schema_version": A2A_SCHEMA_VERSION,
        "message_id": f"msg-{uuid4().hex[:12]}",
        "session_id": session_id,
        "from": from_id,
        "to": target,
        "intent": intent,
        "reason": reason,
        "payload": {
            "summary": summary,
            "key_decisions": key_decisions,
            "open_questions": open_questions,
            "artifacts": artifacts,
        },
        "routing_meta": {
            "chain": session_chain,
            "depth": depth,
            "calls_remaining": calls_remaining,
            "parent_message_id": None,
        },
    }
    # Optional fields — only included when non-empty so schema
    # validation (which has them as optional) passes cleanly.
    if saga_id:
        msg["routing_meta"]["saga_id"] = saga_id
    if signature:
        msg["signature"] = signature
    if tenant_id and tenant_id != DEFAULT_TENANT:
        msg["tenant_id"] = tenant_id
    return msg


def _persist(
    message: dict[str, Any],
    *,
    outcome: str,
    rejection_reason: str | None = None,
    store: MessageStore | None = None,
) -> None:
    """Persist a message to Mnemos, falling back to JSONL on failure.

    The ``outcome`` field is added to the turn body so Mnemos records
    whether the message was delivered or rejected. ``rejection_reason``
    is set only for rejected messages.

    Args:
        message: The A2A message dict to persist.
        outcome: ``"delivered"`` or ``"rejected"``.
        rejection_reason: Rejection code (only for rejected messages).
        store: The tenant-specific MessageStore to write to. If ``None``,
            falls back to the default tenant's message_store (backward
            compat for tests that call _persist directly).
    """
    turn_body: dict[str, Any] = {
        "role": "a2a_message",
        "from": message.get("from", ""),
        "to": message.get("to", ""),
        "message_id": message.get("message_id", ""),
        "content": json.dumps(message, ensure_ascii=False, sort_keys=True),
        "outcome": outcome,
        "tags": [message.get("intent", "handoff")],
    }
    if rejection_reason:
        turn_body["rejection_reason"] = rejection_reason

    # Always write to the local JSONL store first (durable audit trail).
    # Then attempt Mnemos; if it fails, the JSONL copy is the fallback.
    # C2 fix: use the tenant-specific message store, not the global one.
    write_store = store if store is not None else message_store
    try:
        write_store.append({**message, "outcome": outcome,
                            "rejection_reason": rejection_reason})
    except Exception:
        log.exception("JSONL fallback write failed for message %s",
                      message.get("message_id"))

    try:
        mnemos_client.write_turn(message.get("session_id", ""), turn_body)
        metrics.record_mnemos_write()
    except MnemosUnavailableError as exc:
        log.warning("Mnemos unavailable, JSONL fallback active: %s", exc)
        metrics.record_fallback_write()
    except Exception:
        log.exception("Mnemos write_turn raised unexpected error")
        metrics.record_fallback_write()


@mcp.tool()
def send_a2a(
    target: str,
    reason: str,
    summary: str,
    key_decisions: list[str] | None = None,
    open_questions: list[str] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    intent: str = "handoff",
    session_id: str = "",
    from_id: str = "",
    saga_id: str = "",
    signature: str = "",
    tenant_id: str = DEFAULT_TENANT,
) -> dict[str, Any]:
    """Route an A2A message from one agent to another.

    Performs the 6 routing checks (R1-R6) defined by the A2A protocol,
    persists the message to Mnemos (or JSONL fallback), updates the
    per-session chain/budget state, optionally tracks saga state, and
    broadcasts a WebSocket event.

    Args:
        target: A2A id of the receiving agent (e.g. ``agent-dba``).
        reason: 10-500 char human-readable explanation of why the handoff.
        summary: 20-2000 char summary of what the sender has done/found.
        key_decisions: bullet list of decisions already made.
        open_questions: bullet list of things the receiver needs to resolve.
        artifacts: list of ``{kind, pointer}`` dicts (files, diffs, memory).
        intent: one of ``handoff``, ``request-info``, ``share-finding``,
            ``request-review``, ``request-implementation``,
            ``request-documentation``, ``destructive-action-request``.
        session_id: Mnemos session id (from VS Code context or generated).
        from_id: A2A id of the calling agent.
        saga_id: Optional saga id for long-lived dialog state. If provided,
            the chain is tracked within the saga and budget is enforced
            per-saga (6 calls max across all chains).
        signature: Optional Ed25519 signature (base64). Required when the
            sender's Agent Card has a ``public_key`` field (R6).
        tenant_id: Tenant id for multi-tenant isolation. Defaults to
            ``"default"`` (backward compat).

    Returns:
        ``{ok: bool, reason: str, next_senior: str, message_id: str}`` on
        success; ``{ok: False, code: str, reason: str, message_id: str}``
        on rejection.
    """
    # Normalise mutable defaults (avoid the classic shared-list bug).
    if key_decisions is None:
        key_decisions = []
    if open_questions is None:
        open_questions = []
    if artifacts is None:
        artifacts = []

    # Generate a session id if the caller didn't pass one.
    if not session_id:
        session_id = f"conv-{uuid4().hex[:12]}"

    # --- 0. Resolve tenant context ------------------------------------ #
    ctx = _resolve_tenant(tenant_id)
    t_registry = ctx.registry
    t_session_store = ctx.session_store
    t_metrics = ctx.metrics
    t_key_store = ctx.key_store
    t_message_store = ctx.message_store  # C2 fix: per-tenant message store

    # --- 1. Get/create session state ----------------------------------- #
    session = t_session_store.get_or_create(session_id)
    # Track session creation for metrics (only if it's a new session).
    if session.budget_used == 0 and not session.chain:
        t_metrics.record_session_created()
    t_metrics.set_active_sessions(len(t_session_store))

    # --- 2. Build the A2A message -------------------------------------- #
    message = _build_message(
        target=target,
        reason=reason,
        summary=summary,
        key_decisions=key_decisions,
        open_questions=open_questions,
        artifacts=artifacts,
        intent=intent,
        session_id=session_id,
        from_id=from_id,
        session_chain=list(session.chain),
        depth=session.depth(),
        calls_remaining=session.calls_remaining(),
        saga_id=saga_id,
        signature=signature,
        tenant_id=tenant_id,
    )

    # --- 3. Schema validation ----------------------------------------- #
    try:
        validate_a2a_message(message)
    except ValidationError as exc:
        log.warning("A2A message failed schema validation: %s", exc)
        _persist(message, outcome="rejected",
                 rejection_reason=f"schema_validation_failed: {exc}",
                 store=t_message_store)
        t_metrics.record_rejected("SCHEMA_INVALID")
        broadcast_event(session_id, "a2a_rejected",
                        {"code": "SCHEMA_INVALID", "message_id": message["message_id"]})
        return {
            "ok": False,
            "code": "SCHEMA_INVALID",
            "reason": str(exc),
            "message_id": message["message_id"],
        }

    # --- 4. R1→R2→R3→R4 routing checks --------------------------------- #
    rejection = check_all(from_id, target, session, t_registry)
    if rejection is not None:
        log.info("A2A REJECTED %s→%s: %s", from_id, target, rejection.code)
        _persist(message, outcome="rejected",
                 rejection_reason=rejection.code, store=t_message_store)
        session.record_message({**message, "outcome": "rejected",
                                "rejection_code": rejection.code})
        t_metrics.record_rejected(rejection.code)
        broadcast_event(session_id, "a2a_rejected",
                        {"code": rejection.code, "message_id": message["message_id"]})
        return {
            "ok": False,
            "code": rejection.code,
            "reason": rejection.message,
            "message_id": message["message_id"],
        }

    # --- 5. R6: signature verification (if sender has a public key) --- #
    sig_rejection = check_signature(
        from_id, message, signature, t_registry, t_key_store,
    )
    if sig_rejection is not None:
        log.info("A2A REJECTED %s→%s: %s", from_id, target, sig_rejection.code)
        _persist(message, outcome="rejected",
                 rejection_reason=sig_rejection.code, store=t_message_store)
        session.record_message({**message, "outcome": "rejected",
                                "rejection_code": sig_rejection.code})
        t_metrics.record_rejected(sig_rejection.code)
        broadcast_event(session_id, "a2a_rejected",
                        {"code": sig_rejection.code, "message_id": message["message_id"]})
        return {
            "ok": False,
            "code": sig_rejection.code,
            "reason": sig_rejection.message,
            "message_id": message["message_id"],
        }

    # --- 6. R5: destructive action consent ---------------------------- #
    if is_destructive(intent):
        try:
            request_consent(
                from_id=from_id,
                to_id=target,
                summary=summary,
                key_decisions=key_decisions,
                open_questions=open_questions,
                provider=consent_provider,
            )
        except ConsentDenied as exc:
            log.info("A2A REJECTED R5 (consent denied): %s", exc.reason)
            _persist(message, outcome="rejected",
                     rejection_reason="R5_DESTRUCTIVE_DENIED",
                     store=t_message_store)
            session.record_message({**message, "outcome": "rejected",
                                    "rejection_code": "R5_DESTRUCTIVE_DENIED"})
            t_metrics.record_rejected("R5_DESTRUCTIVE_DENIED")
            broadcast_event(session_id, "a2a_rejected",
                            {"code": "R5_DESTRUCTIVE_DENIED",
                             "message_id": message["message_id"]})
            return {
                "ok": False,
                "code": "R5_DESTRUCTIVE_DENIED",
                "reason": exc.reason,
                "message_id": message["message_id"],
            }

    # --- 7. Saga budget check (if saga_id provided) ------------------- #
    if saga_id:
        saga = ctx.saga_store.get_saga(saga_id)
        if saga is None:
            # M1 fix: persist + record + metrics + WS, same as other
            # rejection paths, so the audit trail is complete.
            log.info("A2A REJECTED %s→%s: SAGA_NOT_FOUND", from_id, target)
            _persist(message, outcome="rejected",
                     rejection_reason="SAGA_NOT_FOUND",
                     store=t_message_store)
            session.record_message({**message, "outcome": "rejected",
                                    "rejection_code": "SAGA_NOT_FOUND"})
            t_metrics.record_rejected("SAGA_NOT_FOUND")
            broadcast_event(session_id, "a2a_rejected",
                            {"code": "SAGA_NOT_FOUND",
                             "message_id": message["message_id"]})
            return {
                "ok": False,
                "code": "SAGA_NOT_FOUND",
                "reason": f"Saga {saga_id!r} not found.",
                "message_id": message["message_id"],
            }
        if not ctx.saga_store.record_call(saga_id):
            _persist(message, outcome="rejected",
                     rejection_reason="SAGA_BUDGET_EXHAUSTED",
                     store=t_message_store)
            session.record_message({**message, "outcome": "rejected",
                                    "rejection_code": "SAGA_BUDGET_EXHAUSTED"})
            t_metrics.record_rejected("SAGA_BUDGET_EXHAUSTED")
            broadcast_event(session_id, "a2a_rejected",
                            {"code": "SAGA_BUDGET_EXHAUSTED",
                             "message_id": message["message_id"]})
            return {
                "ok": False,
                "code": "SAGA_BUDGET_EXHAUSTED",
                "reason": f"Saga {saga_id} budget exhausted.",
                "message_id": message["message_id"],
            }

    # --- 8. Persist (Mnemos → JSONL fallback) ------------------------- #
    _persist(message, outcome="delivered", store=t_message_store)

    # --- 9. Update session chain/budget ------------------------------- #
    session.append_hop(from_id, target)
    session.record_message({**message, "outcome": "delivered"})

    # --- 10. Track chain in saga -------------------------------------- #
    if saga_id:
        ctx.saga_store.add_chain(saga_id, list(session.chain))

    t_metrics.record_delivered()
    log.info("A2A delivered %s→%s (msg %s, depth %d, budget %d/%d%s)",
             from_id, target, message["message_id"],
             session.depth(), session.budget_used, MAX_BUDGET,
             f", saga={saga_id}" if saga_id else "")

    # --- 11. Broadcast WS event --------------------------------------- #
    broadcast_event(session_id, "a2a_delivered", {
        "from": from_id, "to": target,
        "message_id": message["message_id"],
        "depth": session.depth(),
        "saga_id": saga_id,
    })
    broadcast_event(session_id, "chain_updated", {
        "chain": list(session.chain),
        "depth": session.depth(),
        "budget_used": session.budget_used,
    })

    return {
        "ok": True,
        "reason": "delivered",
        "next_senior": target,
        "message_id": message["message_id"],
    }


@mcp.tool()
def load_context(
    session_id: str,
    turn_id: str = "",
    message_id: str = "",
    mode: str = "summary",
    tenant_id: str = DEFAULT_TENANT,
) -> dict[str, Any]:
    """Load an A2A message by turn_id or message_id.

    Used by the receiving agent to read the A2A message that was routed
    to them. Returns the message content, key_decisions, open_questions,
    artifacts.

    Args:
        session_id: The Mnemos session id.
        turn_id: The Mnemos turn id (if known). Takes priority.
        message_id: The A2A message_id (used if turn_id is empty).
        mode: ``"summary"`` or ``"full"`` — controls how much detail
            Mnemos returns.
        tenant_id: Tenant id for multi-tenant isolation. Defaults to
            ``"default"``. Only messages from this tenant's store are
            searched in the JSONL fallback (C2 fix).

    Returns:
        ``{ok: bool, message: dict | None, reason: str}``
    """
    # C2 fix: resolve the tenant-specific message store so load_context
    # only sees messages from the caller's tenant.
    ctx = _resolve_tenant(tenant_id)
    t_message_store = ctx.message_store
    # --- 1. Try Mnemos first (if turn_id provided) -------------------- #
    if turn_id:
        try:
            turn = mnemos_client.get_turn(session_id, turn_id, mode=mode)
            content = turn.get("content") or turn.get("body") or ""
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    parsed = {"raw": content}
            else:
                parsed = content if isinstance(content, dict) else {"raw": content}
            return {
                "ok": True,
                "message": parsed,
                "reason": f"loaded from Mnemos turn {turn_id}",
            }
        except MnemosUnavailableError as exc:
            log.warning("Mnemos unavailable for load_context: %s", exc)
            # Fall through to JSONL fallback below.

    # --- 2. Try Mnemos by message_id (search turns) ------------------- #
    if message_id and not turn_id:
        try:
            # Fetch a range of turns and search for the message_id.
            # We fetch up to 100 turns (step 0-99) — covers most sessions.
            range_resp = mnemos_client.get_turn_range(
                session_id, from_step=0, to_step=99, mode=mode,
            )
            turns = range_resp.get("turns", []) or range_resp.get("items", [])
            for turn in turns:
                turn_content = turn.get("content") or turn.get("body") or ""
                if isinstance(turn_content, str):
                    try:
                        parsed_turn = json.loads(turn_content)
                    except json.JSONDecodeError:
                        continue
                elif isinstance(turn_content, dict):
                    parsed_turn = turn_content
                else:
                    continue
                if parsed_turn.get("message_id") == message_id:
                    return {
                        "ok": True,
                        "message": parsed_turn,
                        "reason": f"loaded from Mnemos by message_id {message_id}",
                    }
        except MnemosUnavailableError as exc:
            log.warning("Mnemos unavailable for load_context search: %s", exc)
            # Fall through to JSONL fallback below.

    # --- 3. Fallback: JSONL MessageStore ------------------------------ #
    if message_id:
        msg = t_message_store.find_by_message_id(message_id)
        if msg is not None:
            return {
                "ok": True,
                "message": msg,
                "reason": f"loaded from JSONL fallback by message_id {message_id}",
            }

    # If only session_id + turn_id given and Mnemos failed, try JSONL
    # by scanning recent messages for the session.
    if turn_id and not message_id:
        recent = t_message_store.load_recent(session_id, n=50)
        for msg in reversed(recent):
            # We don't have turn_id in the JSONL store, but we can
            # return the most recent message for the session.
            if msg.get("outcome") == "delivered":
                return {
                    "ok": True,
                    "message": msg,
                    "reason": f"loaded from JSONL fallback (most recent for session {session_id})",
                }

    return {
        "ok": False,
        "message": None,
        "reason": f"Message not found (session_id={session_id}, turn_id={turn_id}, message_id={message_id})",
    }


@mcp.tool()
def get_chain_status(
    session_id: str,
    tenant_id: str = DEFAULT_TENANT,
) -> dict[str, Any]:
    """Get the current routing chain status for a session.

    Returns the chain (list of agent ids), current depth, budget used,
    budget remaining, and the last few messages.

    Args:
        session_id: The session id to query.
        tenant_id: Tenant id (default: ``"default"``).

    Returns:
        ``{ok: bool, chain: list[str], depth: int, budget_used: int,
        calls_remaining: int, recent_messages: list[dict]}``
    """
    ctx = _resolve_tenant(tenant_id)
    session = ctx.session_store.get(session_id)
    if session is None:
        return {
            "ok": True,
            "chain": [],
            "depth": 0,
            "budget_used": 0,
            "calls_remaining": 3,
            "recent_messages": [],
            "reason": "session not found (empty state)",
        }

    # Return last 5 messages (most recent last).
    recent = session.messages[-5:] if session.messages else []

    return {
        "ok": True,
        "chain": list(session.chain),
        "depth": session.depth(),
        "budget_used": session.budget_used,
        "calls_remaining": session.calls_remaining(),
        "recent_messages": recent,
    }


@mcp.tool()
def get_metrics(tenant_id: str = DEFAULT_TENANT) -> dict[str, Any]:
    """Return the orchestrator's metrics counters.

    Args:
        tenant_id: Tenant id. If ``"all"``, return metrics for all tenants.

    Returns:
        A dict with: messages_delivered, messages_rejected,
        rejections_by_rule, mnemos_writes, fallback_writes,
        active_sessions, total_sessions.
    """
    if tenant_id == "all":
        # H3 fix: use the thread-safe all_contexts() snapshot instead
        # of accessing _tenants directly (which bypasses the lock).
        return {
            "ok": True,
            "tenants": tenant_manager.tenant_stats(),
            "per_tenant": {
                tid: ctx.metrics.snapshot()
                for tid, ctx in tenant_manager.all_contexts().items()
            },
        }
    ctx = _resolve_tenant(tenant_id)
    ctx.metrics.set_active_sessions(len(ctx.session_store))
    return ctx.metrics.snapshot()


@mcp.tool()
def get_saga_status(saga_id: str, tenant_id: str = DEFAULT_TENANT) -> dict[str, Any]:
    """Get the status of a saga by its id.

    Args:
        saga_id: The saga id to query.
        tenant_id: Tenant id (default: ``"default"``).

    Returns:
        ``{ok: bool, saga: dict | None, reason: str}``
    """
    ctx = _resolve_tenant(tenant_id)
    saga = ctx.saga_store.get_saga(saga_id)
    if saga is None:
        return {
            "ok": False,
            "saga": None,
            "reason": f"Saga {saga_id!r} not found.",
        }
    return {
        "ok": True,
        "saga": saga.to_dict(),
        "reason": "found",
    }


@mcp.tool()
def create_saga(
    root_session_id: str,
    metadata: str = "",
    tenant_id: str = DEFAULT_TENANT,
) -> dict[str, Any]:
    """Create a new saga for long-lived multi-chain dialog state.

    A saga allows multiple A2A chains to share budget and state
    across a single logical task. Budget per saga: 6 calls.

    Args:
        root_session_id: The session id that initiated the saga.
        metadata: Optional JSON string of free-form metadata (e.g.
            ``'{"task":"migration"}'``). Empty string means no metadata.
        tenant_id: Tenant id (default: ``"default"``). The saga is
            created in this tenant's saga store (tenant isolation).

    Returns:
        ``{ok: bool, saga_id: str, reason: str}``
    """
    # Parse metadata JSON string → dict (empty/invalid → empty dict).
    metadata_dict: dict[str, Any] = {}
    if metadata:
        try:
            parsed = json.loads(metadata)
        except json.JSONDecodeError as exc:
            return {
                "ok": False,
                "saga_id": "",
                "reason": f"metadata is not valid JSON: {exc}",
            }
        if not isinstance(parsed, dict):
            return {
                "ok": False,
                "saga_id": "",
                "reason": "metadata must be a JSON object, not a scalar/array.",
            }
        metadata_dict = parsed

    try:
        ctx = _resolve_tenant(tenant_id)
        saga = ctx.saga_store.create_saga(
            root_session_id=root_session_id,
            metadata=metadata_dict,
        )
    except Exception as exc:  # pragma: no cover — defensive
        log.exception("create_saga failed")
        return {"ok": False, "saga_id": "", "reason": str(exc)}

    return {
        "ok": True,
        "saga_id": saga.saga_id,
        "reason": "created",
    }


@mcp.tool()
def search_messages(
    query: str,
    session_id: str = "",
    limit: int = 10,
    tenant_id: str = DEFAULT_TENANT,
) -> dict[str, Any]:
    """Search A2A messages by query (substring match with scoring).

    Args:
        query: The search query (space-separated terms).
        session_id: If provided, search within this session only.
        limit: Maximum number of results (default: 10).
        tenant_id: Tenant id (default: ``"default"``).

    Returns:
        ``{ok: bool, results: list[dict], count: int}``
    """
    # C2 fix: use the tenant-specific message store so search_messages
    # only searches messages from the caller's tenant.
    ctx = _resolve_tenant(tenant_id)
    results = search_a2a_messages(
        query=query,
        session_id=session_id,
        limit=limit,
        mnemos_client=mnemos_client,
        message_store=ctx.message_store,
    )
    return {
        "ok": True,
        "results": results,
        "count": len(results),
    }


@mcp.tool()
def create_registration_challenge(
    agent_id: str,
    tenant_id: str = DEFAULT_TENANT,
) -> dict[str, Any]:
    """Create a registration challenge for an external agent.

    Returns a nonce that the agent must sign with their Ed25519 private
    key and submit in ``register_agent``.

    Args:
        agent_id: The A2A id of the agent requesting registration.
        tenant_id: Tenant id (default: ``"default"``). The challenge is
            scoped to this tenant's RegistrationService (M2 fix).

    Returns:
        ``{ok: bool, challenge: str, reason: str}``
    """
    svc = _resolve_registration_service(tenant_id)
    nonce = svc.create_challenge(agent_id)
    return {
        "ok": True,
        "challenge": nonce,
        "agent_id": agent_id,
        "reason": "sign this nonce and submit with register_agent",
    }


@mcp.tool()
def register_agent(
    agent_card: str,
    public_key: str,
    challenge_signature: str,
    tenant_id: str = DEFAULT_TENANT,
) -> dict[str, Any]:
    """Register an external agent with challenge-response verification.

    Args:
        agent_card: JSON string of the Agent Card to register.
        public_key: Base64 Ed25519 public key of the agent.
        challenge_signature: Base64 signature of the challenge nonce.
        tenant_id: Tenant id (default: ``"default"``). The agent is
            registered into this tenant's registry + key store (M2 fix).

    Returns:
        ``{ok: bool, agent_id: str, reason: str}``
    """
    try:
        card = json.loads(agent_card)
    except json.JSONDecodeError as exc:
        return {"ok": False, "reason": f"agent_card is not valid JSON: {exc}"}

    request = RegistrationRequest(
        agent_card=card,
        public_key=public_key,
        challenge_signature=challenge_signature,
    )
    svc = _resolve_registration_service(tenant_id)
    return svc.register(request)


@mcp.tool()
def unregister_agent(
    agent_id: str,
    tenant_id: str = DEFAULT_TENANT,
) -> dict[str, Any]:
    """Unregister an externally-registered agent.

    Args:
        agent_id: The A2A id to remove.
        tenant_id: Tenant id (default: ``"default"``). The agent is
            removed from this tenant's registry + key store (M2 fix).

    Returns:
        ``{ok: bool, reason: str}``
    """
    svc = _resolve_registration_service(tenant_id)
    removed = svc.unregister(agent_id)
    return {
        "ok": removed,
        "reason": "removed" if removed else f"agent {agent_id!r} not found",
    }


@mcp.tool()
def list_tenants() -> dict[str, Any]:
    """List all tenants and their statistics.

    Returns:
        ``{ok: bool, tenants: list[dict], count: int}``
    """
    stats = tenant_manager.tenant_stats()
    return {
        "ok": True,
        "tenants": stats,
        "count": len(stats),
    }


def main() -> None:
    """Entry point for ``python3 -m a2a_orchestrator``."""
    logging.basicConfig(
        level=os.environ.get("A2A_ORCHESTRATOR_LOG_LEVEL",
                             os.environ.get("GCW_ORCHESTRATOR_LOG_LEVEL", "INFO")),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    mcp.run()


if __name__ == "__main__":
    main()
