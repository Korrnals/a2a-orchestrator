"""Multi-tenant isolation — multiple teams on one orchestrator.

Each tenant has its own Agent Card registry, session store, message
store, metrics, saga store, and key store. The ``TenantManager``
creates and caches ``TenantContext`` instances on demand.

The default tenant (``tenant_id="default"``) provides backward
compatibility: all existing calls without a ``tenant_id`` parameter
operate on the default tenant.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .metrics import Metrics
from .persistence import MessageStore
from .registry import AgentCardRegistry
from .saga import SagaStore
from .session import SessionStore
from .signing import KeyStore

DEFAULT_TENANT = "default"

# H1 fix: tenant_id is used in filesystem path joins (cards directory).
# Without validation, a malicious tenant_id like "../../etc" could escape
# the cards root and read arbitrary directories. This regex enforces a
# safe, flat namespace: lowercase letter, then lowercase letters/digits/hyphens.
# No path separators, no dots, no parent traversal possible.
_TENANT_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def _validate_tenant_id(tenant_id: str) -> None:
    """Validate ``tenant_id`` against the safe-namespace regex.

    Raises ``ValueError`` if the id contains characters that could be
    used for path traversal or namespace injection. This is called
    before any path operation that incorporates ``tenant_id``.

    The default tenant (``"default"``) always passes — it is a literal
    constant, not user input, but we validate it anyway for uniformity.
    """
    if not isinstance(tenant_id, str) or not _TENANT_ID_RE.match(tenant_id):
        raise ValueError(
            f"Invalid tenant_id {tenant_id!r}: must match "
            f"{_TENANT_ID_RE.pattern} (lowercase letters, digits, hyphens; "
            f"no path separators or dots)."
        )


@dataclass
class TenantContext:
    """All per-tenant state in one container.

    Each tenant gets its own instances of every store/registry so that
    agents, sessions, chains, and metrics are fully isolated.
    """

    tenant_id: str
    registry: AgentCardRegistry = field(init=False)
    session_store: SessionStore = field(init=False)
    message_store: MessageStore = field(init=False)
    metrics: Metrics = field(init=False)
    saga_store: SagaStore = field(init=False)
    key_store: KeyStore = field(init=False)

    def __post_init__(self) -> None:
        # M5 fix: registry is always set by TenantManager.get_or_create
        # (which resolves the cards directory). We initialise it here
        # only as a fallback so a standalone TenantContext (without a
        # manager) still works. TenantManager overwrites this with the
        # correct cards-dir-aware instance.
        self.registry = AgentCardRegistry(cards_dir=Path("a2a/agents"))
        self.session_store = SessionStore(max_sessions=256)
        self.message_store = MessageStore(path=None)  # in-memory by default
        self.metrics = Metrics()
        self.saga_store = SagaStore(max_sagas=128)
        self.key_store = KeyStore()

    def load_registry(self) -> None:
        """Load the Agent Card registry from disk.

        Called after construction once the cards directory is set.
        Silently ignores missing directory (empty registry → R1 rejects).
        """
        import contextlib

        with contextlib.suppress(FileNotFoundError):
            self.registry.load()

    def load_keys(self) -> None:
        """Load public keys from the registry into the key store."""
        self.key_store.load_from_registry(self.registry)


class TenantManager:
    """Thread-safe manager of per-tenant contexts.

    Args:
        default_cards_dir: Cards directory for the default tenant.
            Other tenants get ``cards_dir / tenant_id``.
    """

    def __init__(self, default_cards_dir: Path | str | None = None) -> None:
        self._default_cards_dir = Path(default_cards_dir) if default_cards_dir else None
        self._tenants: dict[str, TenantContext] = {}
        self._lock = threading.Lock()

    def get_or_create(
        self,
        tenant_id: str,
        cards_dir: Path | str | None = None,
    ) -> TenantContext:
        """Return the context for ``tenant_id``, creating it if needed.

        Args:
            tenant_id: The tenant identifier.
            cards_dir: Optional override for the cards directory. If
                omitted, uses ``default_cards_dir`` for the default
                tenant and ``default_cards_dir / tenant_id`` for others.
        """
        # H1 fix: validate tenant_id BEFORE any path join to prevent
        # path traversal (e.g. tenant_id="../../etc" reading arbitrary
        # directories). This runs under the lock so validation and
        # context creation are atomic.
        _validate_tenant_id(tenant_id)
        with self._lock:
            ctx = self._tenants.get(tenant_id)
            if ctx is not None:
                return ctx

            ctx = TenantContext(tenant_id=tenant_id)

            # Resolve the cards directory.
            if cards_dir is not None:
                ctx.registry = AgentCardRegistry(cards_dir=Path(cards_dir))
            elif self._default_cards_dir is not None:
                if tenant_id == DEFAULT_TENANT:
                    # Default tenant uses the cards dir directly.
                    ctx.registry = AgentCardRegistry(cards_dir=self._default_cards_dir)
                else:
                    # Other tenants get a subdirectory.
                    tenant_cards = self._default_cards_dir / tenant_id
                    ctx.registry = AgentCardRegistry(cards_dir=tenant_cards)
            # else: uses the default "a2a/agents" from TenantContext.

            ctx.load_registry()
            ctx.load_keys()
            self._tenants[tenant_id] = ctx
            return ctx

    def get(self, tenant_id: str) -> TenantContext | None:
        """Return the context for ``tenant_id`` or ``None``."""
        with self._lock:
            return self._tenants.get(tenant_id)

    def list_tenants(self) -> list[str]:
        """Return all tenant ids."""
        with self._lock:
            return list(self._tenants.keys())

    def all_contexts(self) -> dict[str, TenantContext]:
        """Return a snapshot of all tenant contexts (thread-safe).

        Returns a shallow copy of the internal ``tenant_id -> TenantContext``
        map. The dict is a snapshot — mutations after the call do not
        affect the returned dict. Use this instead of accessing
        ``_tenants`` directly (which bypasses the lock).
        """
        with self._lock:
            return dict(self._tenants)

    def remove_tenant(self, tenant_id: str) -> bool:
        """Remove a tenant context. Returns ``True`` if it existed."""
        with self._lock:
            return self._tenants.pop(tenant_id, None) is not None

    def tenant_stats(self) -> list[dict[str, Any]]:
        """Return per-tenant statistics (agent count, sessions, sagas)."""
        with self._lock:
            stats: list[dict[str, Any]] = []
            for tid, ctx in self._tenants.items():
                stats.append({
                    "tenant_id": tid,
                    "agents": len(ctx.registry),
                    "active_sessions": len(ctx.session_store),
                    "active_sagas": len(ctx.saga_store),
                    "messages": len(ctx.message_store),
                })
            return stats

    def __len__(self) -> int:
        with self._lock:
            return len(self._tenants)

    def clear(self) -> None:
        """Drop all tenants — used by tests."""
        with self._lock:
            self._tenants.clear()
