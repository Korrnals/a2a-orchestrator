"""WebSocket server for real-time A2A event notifications.

Runs alongside the MCP stdio server. Clients subscribe to session
events and receive push notifications when A2A messages are delivered,
rejected, chains updated, or sagas completed.

Event types:

* ``a2a_delivered`` — an A2A message was successfully routed.
* ``a2a_rejected`` — an A2A message was rejected (R1-R6).
* ``chain_updated`` — a session's chain/budget state changed.
* ``saga_completed`` — a saga was marked as completed.
* ``saga_abandoned`` — a saga was abandoned.

The server is optional — if the ``websockets`` library is not installed
or the WS port is not configured, the orchestrator silently degrades
to no-push (clients poll ``get_chain_status`` instead).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

log = logging.getLogger("a2a_orchestrator.ws")

DEFAULT_WS_PORT = 8788
ENV_WS_PORT = "A2A_WS_PORT"
ENV_WS_BIND_HOST = "A2A_WS_BIND_HOST"
ENV_WS_AUTH_TOKEN = "A2A_WS_AUTH_TOKEN"
ENV_WS_BROADCAST_TIMEOUT = "A2A_WS_BROADCAST_TIMEOUT"
DEFAULT_WS_BIND_HOST = "127.0.0.1"
DEFAULT_WS_BROADCAST_TIMEOUT = 2.0


def _resolve_ws_port() -> int:
    """Return the WS port from env or the default."""
    return int(os.environ.get(ENV_WS_PORT, DEFAULT_WS_PORT))


def _resolve_bind_host() -> str:
    """Return the bind host from env or the default (127.0.0.1).

    H1 fix: default to localhost so session events are not exposed to
    the network. Set ``A2A_WS_BIND_HOST=0.0.0.0`` to bind all interfaces
    (use with ``A2A_WS_AUTH_TOKEN`` for auth).
    """
    return os.environ.get(ENV_WS_BIND_HOST, DEFAULT_WS_BIND_HOST)


def _resolve_auth_token() -> str | None:
    """Return the WS auth token from env, or ``None`` if auth is disabled.

    When set, WebSocket clients must include ``{"auth_token": "..."}``
    in their subscribe message. Default: no auth (localhost only).
    """
    return os.environ.get(ENV_WS_AUTH_TOKEN) or None


def _resolve_broadcast_timeout() -> float:
    """Return the broadcast timeout from env or the default (2.0s).

    L4 fix: configurable via ``A2A_WS_BROADCAST_TIMEOUT``.
    """
    try:
        return float(os.environ.get(ENV_WS_BROADCAST_TIMEOUT,
                                    DEFAULT_WS_BROADCAST_TIMEOUT))
    except (TypeError, ValueError):
        return DEFAULT_WS_BROADCAST_TIMEOUT


class WebSocketServer:
    """Manages WebSocket client connections per session_id.

    This class is transport-agnostic — it maintains the subscription
    state and provides a ``broadcast`` method. The actual WebSocket
    listener is started by :meth:`start` using the ``websockets``
    library.

    Thread-safe: ``broadcast`` can be called from any thread (it
    schedules the send on the event loop).
    """

    def __init__(
        self,
        port: int | None = None,
        bind_host: str | None = None,
        auth_token: str | None = None,
        broadcast_timeout: float | None = None,
    ) -> None:
        self._port = port or _resolve_ws_port()
        # H1 fix: default bind to 127.0.0.1 (localhost only), not 0.0.0.0.
        self._bind_host = bind_host or _resolve_bind_host()
        # H1 fix: optional auth token for non-localhost deployments.
        self._auth_token = auth_token if auth_token is not None else _resolve_auth_token()
        # L4 fix: configurable broadcast timeout.
        self._broadcast_timeout = (broadcast_timeout
                                   if broadcast_timeout is not None
                                   else _resolve_broadcast_timeout())
        # session_id -> set of WebSocket connections
        self._subscribers: dict[str, set[Any]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: Any = None

    @property
    def port(self) -> int:
        return self._port

    @property
    def bind_host(self) -> str:
        """Return the bind host (H1 fix: default 127.0.0.1)."""
        return self._bind_host

    async def add_subscriber(self, session_id: str, ws: Any) -> None:
        """Register a WebSocket connection for ``session_id`` events."""
        self._subscribers.setdefault(session_id, set()).add(ws)
        log.debug("WS subscriber added for session %s (total: %d)",
                  session_id, len(self._subscribers[session_id]))

    async def remove_subscriber(self, session_id: str, ws: Any) -> None:
        """Unregister a WebSocket connection."""
        subs = self._subscribers.get(session_id)
        if subs:
            subs.discard(ws)
            if not subs:
                self._subscribers.pop(session_id, None)

    async def broadcast(self, session_id: str, event: dict[str, Any]) -> int:
        """Send an event to all subscribers of ``session_id``.

        Returns the number of clients that received the event.
        """
        subs = set(self._subscribers.get(session_id, set()))
        if not subs:
            return 0
        message = json.dumps(event, ensure_ascii=False, sort_keys=True)
        delivered = 0
        for ws in subs:
            try:
                await ws.send(message)
                delivered += 1
            except Exception:
                log.debug("WS send failed for a subscriber of %s", session_id)
                await self.remove_subscriber(session_id, ws)
        return delivered

    def broadcast_sync(self, session_id: str, event: dict[str, Any]) -> int:
        """Thread-safe broadcast from a sync context.

        Schedules :meth:`broadcast` on the event loop. Returns 0 if no
        loop is running (the event is silently dropped).
        """
        if self._loop is None or not self._loop.is_running():
            return 0
        future = asyncio.run_coroutine_threadsafe(
            self.broadcast(session_id, event), self._loop,
        )
        try:
            return future.result(timeout=self._broadcast_timeout)
        except TimeoutError:
            # L4 fix: log a warning when the broadcast times out so
            # operators can detect slow/stuck subscribers.
            log.warning("WS broadcast to session %s timed out after %.1fs",
                        session_id, self._broadcast_timeout)
            return 0
        except Exception:
            return 0

    async def _handler(self, ws: Any) -> None:
        """Handle a single WebSocket connection.

        The first message from the client must be a JSON object with
        ``{"action": "subscribe", "session_id": "..."}``. After that,
        the client receives events for that session until disconnect.

        H1 fix: if an auth token is configured, the subscribe message
        must also include ``"auth_token": "<token>"``.
        """
        # L3 fix: initialise session_id before the try block so the
        # finally clause can safely check it without a locals() lookup.
        session_id = ""
        try:
            # Wait for the subscription message.
            raw = await ws.recv()
            data = json.loads(raw)
            if data.get("action") != "subscribe":
                await ws.send(json.dumps({"ok": False, "reason": "send subscribe first"}))
                return
            # H1 fix: auth token check (if configured).
            if self._auth_token is not None:
                provided_token = data.get("auth_token", "")
                if provided_token != self._auth_token:
                    await ws.send(json.dumps({
                        "ok": False, "reason": "invalid or missing auth_token",
                    }))
                    return
            session_id = data.get("session_id", "")
            if not session_id:
                await ws.send(json.dumps({"ok": False, "reason": "session_id required"}))
                return
            await self.add_subscriber(session_id, ws)
            await ws.send(json.dumps({"ok": True, "reason": "subscribed",
                                       "session_id": session_id}))
            # Keep the connection open; events are pushed via broadcast.
            # We just wait until the client disconnects.
            async for _ in ws:
                pass  # Ignore incoming messages after subscribe.
        except Exception as exc:
            log.debug("WS handler ended: %s", exc)
        finally:
            # L3 fix: clean up subscription on disconnect using the
            # pre-initialised session_id variable (no locals() lookup).
            if session_id:
                await self.remove_subscriber(session_id, ws)

    async def start_async(self) -> None:
        """Start the WebSocket server (async context).

        Binds to ``self._bind_host`` (default: ``127.0.0.1``) on
        ``self._port``. Sets ``self._loop`` so :meth:`broadcast_sync`
        can schedule sends from sync code.

        H1 fix: default bind host is localhost, not 0.0.0.0.
        """
        import websockets

        self._loop = asyncio.get_running_loop()
        self._server = await websockets.serve(
            self._handler, self._bind_host, self._port,
        )
        log.info("WebSocket server listening on %s:%d", self._bind_host, self._port)

    def start(self) -> None:
        """Start the WebSocket server in a blocking manner.

        Runs the asyncio event loop. Call from a dedicated thread if
        you need the WS server to run alongside the MCP stdio server.
        """
        asyncio.run(self._run_server())

    async def _run_server(self) -> None:
        await self.start_async()
        # Run forever.
        await asyncio.Future()  # Never completes.

    def stop(self) -> None:
        """Stop the WebSocket server."""
        if self._server is not None:
            self._server.close()
            self._server = None

    def subscriber_count(self, session_id: str = "") -> int:
        """Return the number of subscribers for a session (or total)."""
        if session_id:
            return len(self._subscribers.get(session_id, set()))
        return sum(len(s) for s in self._subscribers.values())


# Module-level singleton — created lazily.
_ws_server: WebSocketServer | None = None


def get_ws_server() -> WebSocketServer | None:
    """Return the global WebSocket server singleton, or ``None`` if not started."""
    return _ws_server


def set_ws_server(server: WebSocketServer | None) -> None:
    """Set the global WebSocket server (for testing or explicit init)."""
    global _ws_server
    _ws_server = server


def broadcast_event(session_id: str, event_type: str, data: dict[str, Any]) -> int:
    """Broadcast an event to subscribers of ``session_id``.

    Returns the number of clients that received the event. If no WS
    server is running, returns 0 silently (graceful degradation).
    """
    server = _ws_server
    if server is None:
        return 0
    event = {"type": event_type, "session_id": session_id, "data": data}
    return server.broadcast_sync(session_id, event)
