"""Unit tests for WebSocket server (a2a_orchestrator.ws_server)."""
from __future__ import annotations

import asyncio
import json

import pytest
import websockets
from a2a_orchestrator.ws_server import WebSocketServer


@pytest.mark.asyncio
async def test_broadcast_no_subscribers():
    """Broadcast to a session with no subscribers returns 0."""
    server = WebSocketServer(port=18788)
    count = await server.broadcast("session-1", {"type": "test"})
    assert count == 0


@pytest.mark.asyncio
async def test_broadcast_to_subscriber():
    """A subscriber receives broadcast events for its session."""
    server = WebSocketServer(port=18789)
    await server.start_async()
    try:
        async with websockets.connect("ws://127.0.0.1:18789") as ws:
            await ws.send(json.dumps({"action": "subscribe", "session_id": "s1"}))
            resp = await ws.recv()
            assert json.loads(resp)["ok"] is True

            await server.broadcast("s1", {"type": "a2a_delivered", "data": {"msg": "hi"}})
            event = await asyncio.wait_for(ws.recv(), timeout=2.0)
            parsed = json.loads(event)
            assert parsed["type"] == "a2a_delivered"
    finally:
        server.stop()


@pytest.mark.asyncio
async def test_multiple_subscribers_same_session():
    """Multiple subscribers on the same session all receive events."""
    server = WebSocketServer(port=18790)
    await server.start_async()
    try:
        async with websockets.connect("ws://127.0.0.1:18790") as ws1, \
                   websockets.connect("ws://127.0.0.1:18790") as ws2:
            await ws1.send(json.dumps({"action": "subscribe", "session_id": "s1"}))
            await ws1.recv()
            await ws2.send(json.dumps({"action": "subscribe", "session_id": "s1"}))
            await ws2.recv()

            count = await server.broadcast("s1", {"type": "chain_updated"})
            assert count == 2

            ev1 = await asyncio.wait_for(ws1.recv(), timeout=2.0)
            ev2 = await asyncio.wait_for(ws2.recv(), timeout=2.0)
            assert json.loads(ev1)["type"] == "chain_updated"
            assert json.loads(ev2)["type"] == "chain_updated"
    finally:
        server.stop()


@pytest.mark.asyncio
async def test_subscriber_different_session_does_not_receive():
    """A subscriber on session-2 does NOT receive events for session-1."""
    server = WebSocketServer(port=18791)
    await server.start_async()
    try:
        async with websockets.connect("ws://127.0.0.1:18791") as ws1, \
                   websockets.connect("ws://127.0.0.1:18791") as ws2:
            await ws1.send(json.dumps({"action": "subscribe", "session_id": "s1"}))
            await ws1.recv()
            await ws2.send(json.dumps({"action": "subscribe", "session_id": "s2"}))
            await ws2.recv()

            count = await server.broadcast("s1", {"type": "a2a_delivered"})
            assert count == 1  # Only ws1 received.

            # ws2 should NOT receive anything — verify with timeout.
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(ws2.recv(), timeout=0.5)
    finally:
        server.stop()


@pytest.mark.asyncio
async def test_broadcast_sync_from_sync_context():
    """broadcast_sync schedules on the event loop and returns count.

    broadcast_sync is designed for calling from sync code (e.g. the MCP
    tool handler) into a running event loop. We test it by calling from
    a thread while the main async test yields control to let the loop
    process the scheduled coroutine.
    """
    import threading

    server = WebSocketServer(port=18792)
    await server.start_async()
    try:
        async with websockets.connect("ws://127.0.0.1:18792") as ws:
            await ws.send(json.dumps({"action": "subscribe", "session_id": "sync-test"}))
            await ws.recv()

            # Call broadcast_sync from a separate thread.
            future_result: list[int] = []
            def _sync_call() -> None:
                future_result.append(server.broadcast_sync("sync-test", {"type": "test"}))
            t = threading.Thread(target=_sync_call)
            t.start()
            # Yield control to the event loop so the scheduled coroutine
            # can execute while the thread waits on future.result().
            while t.is_alive():
                await asyncio.sleep(0.05)
            t.join(timeout=3.0)

            assert len(future_result) == 1
            assert future_result[0] >= 1
    finally:
        server.stop()


@pytest.mark.asyncio
async def test_subscriber_count():
    """subscriber_count returns correct counts."""
    server = WebSocketServer(port=18793)
    await server.start_async()
    try:
        async with websockets.connect("ws://127.0.0.1:18793") as ws1, \
                   websockets.connect("ws://127.0.0.1:18793") as ws2:
            await ws1.send(json.dumps({"action": "subscribe", "session_id": "s1"}))
            await ws1.recv()
            await ws2.send(json.dumps({"action": "subscribe", "session_id": "s1"}))
            await ws2.recv()

            assert server.subscriber_count("s1") == 2
            assert server.subscriber_count("s2") == 0
            assert server.subscriber_count() == 2  # total
    finally:
        server.stop()
