"""CLI wrapper for the A2A orchestrator.

Provides a command-line interface to the same internal functions as the
MCP tools. This is useful for scripting, debugging, and smoke-testing
without starting the MCP server.

Commands::

    a2a-orchestrator send --from agent-a --to agent-b --reason "..." --summary "..." --session-id conv-001
    a2a-orchestrator list --session-id conv-001 --limit 10
    a2a-orchestrator status --session-id conv-001
    a2a-orchestrator agents
    a2a-orchestrator serve

Uses ``argparse`` (no extra dependency) so the CLI works in any Python
3.11+ environment without installing additional packages.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from typing import Any


def _cmd_send(args: argparse.Namespace) -> int:
    """Send an A2A message (calls send_a2a internally)."""
    from .server import send_a2a

    result = send_a2a(
        target=args.target,
        reason=args.reason,
        summary=args.summary,
        key_decisions=args.key_decisions or [],
        open_questions=args.open_questions or [],
        artifacts=_parse_artifacts(args.artifacts),
        intent=args.intent,
        session_id=args.session_id,
        from_id=args.from_id,
    )
    _print_json(result)
    return 0 if result.get("ok") else 1


def _cmd_list(args: argparse.Namespace) -> int:
    """List recent A2A messages for a session."""
    from .server import message_store

    messages = message_store.load_recent(args.session_id, n=args.limit)
    _print_json({"ok": True, "messages": messages, "count": len(messages)})
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    """Get chain status for a session."""
    from .server import get_chain_status

    result = get_chain_status(session_id=args.session_id)
    _print_json(result)
    return 0


def _cmd_agents(args: argparse.Namespace) -> int:
    """List registered agents."""
    from .server import registry

    agents = registry.list_agents()
    _print_json({"ok": True, "agents": agents, "count": len(agents)})
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    """Start the MCP server (same as ``python3 -m a2a_orchestrator``).

    With ``--ws`` also starts the WebSocket server in a background thread.
    With ``--all`` starts MCP + WS + Web server.
    """
    import threading

    from .server import main

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if args.all:
        # Start WS server in background thread.
        from .ws_server import WebSocketServer, set_ws_server

        ws = WebSocketServer()
        set_ws_server(ws)
        ws_thread = threading.Thread(target=ws.start, daemon=True)
        ws_thread.start()

        # Start web server in background thread.
        from .web_server import run_web_server

        web_thread = threading.Thread(
            target=run_web_server,
            kwargs={"host": args.web_host, "port": args.web_port},
            daemon=True,
        )
        web_thread.start()

    elif args.ws:
        from .ws_server import WebSocketServer, set_ws_server

        ws = WebSocketServer()
        set_ws_server(ws)
        ws_thread = threading.Thread(target=ws.start, daemon=True)
        ws_thread.start()

    main()
    return 0


def _cmd_web(args: argparse.Namespace) -> int:
    """Start the web/HTTP server."""
    from .web_server import run_web_server

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    run_web_server(host=args.host, port=args.port)
    return 0


def _cmd_ws_monitor(args: argparse.Namespace) -> int:
    """Monitor WebSocket events for a session."""
    import asyncio
    import json as json_mod

    import websockets

    async def _monitor() -> None:
        port = args.port
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as ws:
            await ws.send(json_mod.dumps({
                "action": "subscribe",
                "session_id": args.session_id,
            }))
            resp = await ws.recv()
            print(resp)
            async for msg in ws:
                print(msg)

    asyncio.run(_monitor())
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    """Search A2A messages."""
    from .server import search_messages

    result = search_messages(
        query=args.query,
        session_id=args.session_id,
        limit=args.limit,
    )
    _print_json(result)
    return 0


def _cmd_saga_list(args: argparse.Namespace) -> int:
    """List active sagas."""
    from .server import _resolve_tenant

    # L7 fix: resolve the tenant-specific saga store instead of the
    # module-level default-tenant alias.
    ctx = _resolve_tenant(args.tenant_id)
    sagas = ctx.saga_store.list_sagas(status=args.status or "")
    _print_json({
        "ok": True,
        "sagas": [s.to_dict() for s in sagas],
        "count": len(sagas),
    })
    return 0


def _cmd_saga_status(args: argparse.Namespace) -> int:
    """Get saga status."""
    from .server import get_saga_status

    result = get_saga_status(saga_id=args.saga_id, tenant_id=args.tenant_id)
    _print_json(result)
    return 0 if result.get("ok") else 1


def _cmd_register(args: argparse.Namespace) -> int:
    """Register an external agent."""
    from pathlib import Path

    from .server import create_registration_challenge, register_agent

    # Read the agent card JSON file.
    card_text = Path(args.agent_card).read_text(encoding="utf-8")

    # Read the public key file.
    public_key = Path(args.public_key).read_text(encoding="utf-8").strip()

    # Step 1: create challenge.
    agent_id = json.loads(card_text).get("id", "")
    challenge_resp = create_registration_challenge(agent_id=agent_id)
    if not challenge_resp.get("ok"):
        _print_json(challenge_resp)
        return 1

    # Step 2: the caller must sign the challenge externally.
    # For CLI, we expect the signature to be provided via --signature.
    if not args.signature:
        _print_json({
            "ok": False,
            "reason": "challenge created; sign it and re-run with --signature",
            "challenge": challenge_resp["challenge"],
        })
        return 1

    # Step 3: register.
    result = register_agent(
        agent_card=card_text,
        public_key=public_key,
        challenge_signature=args.signature,
    )
    _print_json(result)
    return 0 if result.get("ok") else 1


def _cmd_tenants_list(args: argparse.Namespace) -> int:
    """List all tenants."""
    from .server import list_tenants

    result = list_tenants()
    _print_json(result)
    return 0


def _cmd_metrics(args: argparse.Namespace) -> int:
    """Get metrics counters."""
    from .server import get_metrics

    result = get_metrics()
    _print_json(result)
    return 0


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _parse_artifacts(raw: list[str] | None) -> list[dict[str, Any]]:
    """Parse ``--artifact kind:pointer`` arguments into dicts.

    Each artifact is ``kind:pointer`` (e.g. ``file:src/models.py``).
    Multiple artifacts can be passed: ``--artifact file:a.py --artifact diff:b.patch``.
    """
    if not raw:
        return []
    artifacts: list[dict[str, Any]] = []
    for item in raw:
        if ":" in item:
            kind, pointer = item.split(":", 1)
            artifacts.append({"kind": kind, "pointer": pointer})
        else:
            artifacts.append({"kind": "file", "pointer": item})
    return artifacts


def _print_json(obj: Any) -> None:
    """Print a JSON object to stdout (compact, sorted keys)."""
    print(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2))


# --------------------------------------------------------------------------- #
# Argument parser
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="a2a-orchestrator",
        description="A2A orchestrator — route messages between agents.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- send --- #
    send_parser = subparsers.add_parser("send", help="Send an A2A message.")
    send_parser.add_argument("--from", dest="from_id", required=True,
                             help="A2A id of the sending agent.")
    send_parser.add_argument("--to", dest="target", required=True,
                             help="A2A id of the receiving agent.")
    send_parser.add_argument("--reason", required=True,
                             help="10-500 char explanation of why the handoff.")
    send_parser.add_argument("--summary", required=True,
                             help="20-2000 char summary of what was done/found.")
    send_parser.add_argument("--session-id", default="",
                             help="Session id (auto-generated if empty).")
    send_parser.add_argument("--intent", default="handoff",
                             choices=["handoff", "request-info", "share-finding",
                                      "request-review", "request-implementation",
                                      "request-documentation",
                                      "destructive-action-request"],
                             help="Message intent (default: handoff).")
    send_parser.add_argument("--key-decision", dest="key_decisions",
                             action="append", default=[],
                             help="Key decision (repeatable).")
    send_parser.add_argument("--open-question", dest="open_questions",
                             action="append", default=[],
                             help="Open question (repeatable).")
    send_parser.add_argument("--artifact", dest="artifacts",
                             action="append", default=[],
                             help="Artifact as kind:pointer (repeatable).")
    send_parser.set_defaults(func=_cmd_send)

    # --- list --- #
    list_parser = subparsers.add_parser("list", help="List recent A2A messages.")
    list_parser.add_argument("--session-id", required=True,
                             help="Session id to list messages for.")
    list_parser.add_argument("--limit", type=int, default=10,
                             help="Max messages to return (default: 10).")
    list_parser.set_defaults(func=_cmd_list)

    # --- status --- #
    status_parser = subparsers.add_parser("status",
                                          help="Get chain status for a session.")
    status_parser.add_argument("--session-id", required=True,
                               help="Session id to query.")
    status_parser.set_defaults(func=_cmd_status)

    # --- agents --- #
    agents_parser = subparsers.add_parser("agents",
                                          help="List registered agents.")
    agents_parser.set_defaults(func=_cmd_agents)

    # --- metrics --- #
    metrics_parser = subparsers.add_parser("metrics",
                                           help="Get metrics counters.")
    metrics_parser.set_defaults(func=_cmd_metrics)

    # --- serve --- #
    serve_parser = subparsers.add_parser("serve",
                                         help="Start the MCP server.")
    serve_parser.add_argument("--ws", action="store_true",
                              help="Also start the WebSocket server.")
    serve_parser.add_argument("--all", action="store_true",
                              help="Start MCP + WS + Web server.")
    serve_parser.add_argument("--web-host", default="127.0.0.1",
                              help="Web server bind address (default: 127.0.0.1).")
    serve_parser.add_argument("--web-port", type=int, default=8789,
                              help="Web server port (default: 8789).")
    serve_parser.set_defaults(func=_cmd_serve)

    # --- web --- #
    web_parser = subparsers.add_parser("web",
                                       help="Start the web/HTTP server.")
    web_parser.add_argument("--host", default="127.0.0.1",
                            help="Bind address (default: 127.0.0.1).")
    web_parser.add_argument("--port", type=int, default=8789,
                            help="Listen port (default: 8789).")
    web_parser.set_defaults(func=_cmd_web)

    # --- ws-monitor --- #
    ws_parser = subparsers.add_parser("ws-monitor",
                                      help="Monitor WebSocket events for a session.")
    ws_parser.add_argument("--session-id", required=True,
                           help="Session id to monitor.")
    ws_parser.add_argument("--port", type=int, default=8788,
                           help="WebSocket server port (default: 8788).")
    ws_parser.set_defaults(func=_cmd_ws_monitor)

    # --- search --- #
    search_parser = subparsers.add_parser("search",
                                          help="Search A2A messages.")
    search_parser.add_argument("query", help="Search query.")
    search_parser.add_argument("--session-id", default="",
                               help="Restrict to this session.")
    search_parser.add_argument("--limit", type=int, default=10,
                               help="Max results (default: 10).")
    search_parser.set_defaults(func=_cmd_search)

    # --- saga --- #
    saga_parser = subparsers.add_parser("saga",
                                        help="Saga management.")
    saga_sub = saga_parser.add_subparsers(dest="saga_command")
    saga_list_parser = saga_sub.add_parser("list", help="List sagas.")
    saga_list_parser.add_argument("--status", default="",
                                  help="Filter by status (active/completed/abandoned).")
    # L7 fix: add --tenant-id flag (default "default").
    saga_list_parser.add_argument("--tenant-id", default="default",
                                  help="Tenant id (default: default).")
    saga_list_parser.set_defaults(func=_cmd_saga_list)
    saga_status_parser = saga_sub.add_parser("status", help="Get saga status.")
    saga_status_parser.add_argument("saga_id", help="Saga id.")
    # L7 fix: add --tenant-id flag (default "default").
    saga_status_parser.add_argument("--tenant-id", default="default",
                                    help="Tenant id (default: default).")
    saga_status_parser.set_defaults(func=_cmd_saga_status)

    # --- register --- #
    register_parser = subparsers.add_parser("register",
                                            help="Register an external agent.")
    register_parser.add_argument("--agent-card", required=True,
                                 help="Path to the Agent Card JSON file.")
    register_parser.add_argument("--public-key", required=True,
                                 help="Path to the base64 public key file.")
    register_parser.add_argument("--signature", default="",
                                 help="Base64 signature of the challenge nonce.")
    register_parser.set_defaults(func=_cmd_register)

    # --- tenants --- #
    tenants_parser = subparsers.add_parser("tenants",
                                           help="Tenant management.")
    tenants_sub = tenants_parser.add_subparsers(dest="tenants_command")
    tenants_list_parser = tenants_sub.add_parser("list", help="List tenants.")
    tenants_list_parser.set_defaults(func=_cmd_tenants_list)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code (0 = success, 1 = error).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    func = args.func
    return int(func(args))


if __name__ == "__main__":
    sys.exit(main())
