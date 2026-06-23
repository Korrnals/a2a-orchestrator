"""FastAPI HTTP wrapper — REST endpoints mirroring MCP tools.

Exposes the same internal functions as the MCP tools via REST, so
non-VS Code runtimes (CLI, web apps, external services) can use the
orchestrator over HTTP.

Endpoints::

    POST /v1/send              — send_a2a
    GET  /v1/context/{sid}/{tid} — load_context
    GET  /v1/chain/{sid}       — get_chain_status
    GET  /v1/metrics           — get_metrics
    GET  /v1/saga/{saga_id}    — get_saga_status
    POST /v1/search            — search_messages
    GET  /v1/agents            — list registered agents
    GET  /health               — health check
    POST /v1/register/challenge — create registration challenge
    POST /v1/register          — submit registration
    DELETE /v1/register/{aid}  — unregister

CORS and API key auth are configurable via environment variables.
"""
from __future__ import annotations

import os
from typing import Any

# FastAPI is an optional dependency — import lazily so the module can
# be imported (and tested for structure) even when fastapi is absent.
try:
    from fastapi import Depends, FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    _FASTAPI_AVAILABLE = False
    FastAPI = None  # type: ignore[assignment, misc]

ENV_CORS_ORIGINS = "A2A_WEB_CORS_ORIGINS"
ENV_API_KEY = "A2A_WEB_API_KEY"
DEFAULT_CORS_ORIGINS = "http://localhost,http://127.0.0.1"


def _resolve_cors_origins() -> list[str]:
    """Return the list of allowed CORS origins from env."""
    raw = os.environ.get(ENV_CORS_ORIGINS, DEFAULT_CORS_ORIGINS)
    return [o.strip() for o in raw.split(",") if o.strip()]


def _resolve_api_key() -> str | None:
    """Return the API key from env, or ``None`` if auth is disabled."""
    return os.environ.get(ENV_API_KEY) or None


def _api_key_dependency() -> Any:
    """Return a FastAPI dependency that checks the API key header.

    If no API key is configured, the dependency is a no-op.
    """
    expected_key = _resolve_api_key()

    if expected_key is None:
        # No auth required — return a no-op dependency.
        async def _no_auth() -> bool:
            return True
        return _no_auth

    async def _check_auth(request: Request) -> bool:
        provided = request.headers.get("X-API-Key", "")
        if provided != expected_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return True

    return _check_auth


def create_app(server_module: Any | None = None) -> Any:
    """Create and configure the FastAPI application.

    Args:
        server_module: The ``a2a_orchestrator.server`` module (or a
            mock). If ``None``, imports it lazily. This indirection
            allows tests to inject a fresh server module.

    Returns:
        A configured ``FastAPI`` instance.
    """
    if not _FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI is not installed. Install with: "
            "pip install 'a2a-orchestrator[web]'"
        )

    if server_module is None:
        from . import server as server_module  # type: ignore[no-redef]

    # L2 fix: import the canonical version from the package instead of
    # hardcoding "0.8.0".
    from . import A2A_SCHEMA_VERSION

    # We use a Protocol-free Any here because the server module's tool
    # functions return ``dict[str, Any]`` but mypy can't verify that
    # through the dynamic ``Any`` type. Each endpoint casts the result.
    srv: Any = server_module

    def _ret(value: Any) -> dict[str, Any]:
        """Cast a tool return value to dict[str, Any] for mypy."""
        return dict(value) if isinstance(value, dict) else {"ok": False, "value": value}

    app = FastAPI(
        title="A2A Orchestrator",
        version=A2A_SCHEMA_VERSION,
        description="REST API for A2A message routing between agents.",
    )

    # CORS middleware.
    # M6 fix: validate that origins are not "*" when allow_credentials
    # is True. A wildcard origin with credentials is a CORS footgun
    # (browsers reject it, and it signals a misconfiguration).
    cors_origins = _resolve_cors_origins()
    allow_credentials = True
    if allow_credentials and "*" in cors_origins:
        raise ValueError(
            "CORS misconfiguration: allow_credentials=True with wildcard "
            "origin '*' is not allowed. Set A2A_WEB_CORS_ORIGINS to "
            "explicit origins (e.g. 'http://localhost,http://127.0.0.1')."
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    auth_dep = _api_key_dependency()

    # ------------------------------------------------------------------ #
    # Endpoints
    # ------------------------------------------------------------------ #

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "service": "a2a-orchestrator",
                "version": A2A_SCHEMA_VERSION}

    @app.get("/v1/agents")
    async def list_agents(_auth: bool = Depends(auth_dep)) -> dict[str, Any]:
        agents = srv.registry.list_agents()
        return {"ok": True, "agents": agents, "count": len(agents)}

    @app.get("/v1/metrics")
    async def get_metrics(_auth: bool = Depends(auth_dep)) -> dict[str, Any]:
        return _ret(srv.get_metrics())

    @app.get("/v1/chain/{session_id}")
    async def get_chain(session_id: str, _auth: bool = Depends(auth_dep)) -> dict[str, Any]:
        return _ret(srv.get_chain_status(session_id=session_id))

    @app.get("/v1/context/{session_id}/{turn_id}")
    async def get_context(
        session_id: str,
        turn_id: str,
        message_id: str = "",
        mode: str = "summary",
        _auth: bool = Depends(auth_dep),
    ) -> dict[str, Any]:
        return _ret(srv.load_context(
            session_id=session_id,
            turn_id=turn_id,
            message_id=message_id,
            mode=mode,
        ))

    @app.post("/v1/send")
    async def send_a2a(body: dict[str, Any], _auth: bool = Depends(auth_dep)) -> dict[str, Any]:
        required = ["target", "reason", "summary", "from_id"]
        for field in required:
            if field not in body:
                raise HTTPException(status_code=422, detail=f"Missing field: {field}")
        return _ret(srv.send_a2a(
            target=body["target"],
            reason=body["reason"],
            summary=body["summary"],
            key_decisions=body.get("key_decisions", []),
            open_questions=body.get("open_questions", []),
            artifacts=body.get("artifacts", []),
            intent=body.get("intent", "handoff"),
            session_id=body.get("session_id", ""),
            from_id=body["from_id"],
            saga_id=body.get("saga_id", ""),
            signature=body.get("signature", ""),
            tenant_id=body.get("tenant_id", "default"),
        ))

    @app.get("/v1/saga/{saga_id}")
    async def get_saga(saga_id: str, _auth: bool = Depends(auth_dep)) -> dict[str, Any]:
        return _ret(srv.get_saga_status(saga_id=saga_id))

    @app.post("/v1/search")
    async def search_messages(
        body: dict[str, Any],
        _auth: bool = Depends(auth_dep),
    ) -> dict[str, Any]:
        query = body.get("query", "")
        if not query:
            raise HTTPException(status_code=422, detail="query is required")
        return _ret(srv.search_messages(
            query=query,
            session_id=body.get("session_id", ""),
            limit=body.get("limit", 10),
            tenant_id=body.get("tenant_id", "default"),
        ))

    @app.post("/v1/register/challenge")
    async def create_challenge(
        body: dict[str, Any],
        _auth: bool = Depends(auth_dep),
    ) -> dict[str, Any]:
        agent_id = body.get("agent_id", "")
        if not agent_id:
            raise HTTPException(status_code=422, detail="agent_id is required")
        return _ret(srv.create_registration_challenge(agent_id=agent_id))

    @app.post("/v1/register")
    async def register_agent(
        body: dict[str, Any],
        _auth: bool = Depends(auth_dep),
    ) -> dict[str, Any]:
        agent_card = body.get("agent_card", "")
        public_key = body.get("public_key", "")
        challenge_signature = body.get("challenge_signature", "")
        if not agent_card or not public_key or not challenge_signature:
            raise HTTPException(
                status_code=422,
                detail="agent_card, public_key, and challenge_signature are required",
            )
        return _ret(srv.register_agent(
            agent_card=agent_card,
            public_key=public_key,
            challenge_signature=challenge_signature,
        ))

    @app.delete("/v1/register/{agent_id}")
    async def unregister_agent(
        agent_id: str,
        _auth: bool = Depends(auth_dep),
    ) -> dict[str, Any]:
        return _ret(srv.unregister_agent(agent_id=agent_id))

    @app.get("/v1/tenants")
    async def list_tenants(_auth: bool = Depends(auth_dep)) -> dict[str, Any]:
        return _ret(srv.list_tenants())

    return app


def run_web_server(
    host: str = "127.0.0.1",
    port: int = 8789,
    server_module: Any | None = None,
) -> None:
    """Start the web server (blocking).

    Args:
        host: Bind address.
        port: Listen port.
        server_module: Optional server module override (for testing).
    """
    import uvicorn

    app = create_app(server_module=server_module)
    uvicorn.run(app, host=host, port=port)
