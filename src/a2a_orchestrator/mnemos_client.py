"""REST client for the Mnemos session/turn API.

Mnemos (``http://127.0.0.1:8787``) is the durable memory backend for A2A
messages. This module is a thin sync client over ``httpx`` that maps the
5 A2A-relevant endpoints:

1. :meth:`create_session`  → ``POST /v1/sessions``
2. :meth:`get_session`     → ``GET  /v1/sessions/{id}``
3. :meth:`write_turn`      → ``POST /v1/sessions/{id}/turns``
4. :meth:`get_turn`        → ``GET  /v1/sessions/{id}/turns/{turn_id}``
5. :meth:`get_turn_range`  → ``POST /v1/sessions/{id}/turns/range``

Retry policy: 3 attempts with exponential backoff (0.5s, 1s, 2s) on
``5xx`` responses and connection errors. On final failure raises
:class:`MnemosUnavailableError` so the caller can fall back to the local
JSONL store (:mod:`.persistence`).

Idempotency: the caller passes ``message_id`` in the turn body; Mnemos
deduplicates on that field, so a retry after a partial failure is safe.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

# Default Mnemos port is 8787 (NOT 8000). Overridable via env var.
DEFAULT_BASE_URL = "http://127.0.0.1:8787"
ENV_BASE_URL = "MNEMOS_BASE_URL"

# Retry tuning. Exposed as module constants so tests can monkey-patch
# them to zero for fast test runs.
MAX_RETRIES = 3
RETRY_BACKOFFS = (0.5, 1.0, 2.0)  # seconds; applied before attempts 2, 3, 4
REQUEST_TIMEOUT = 5.0  # seconds per request


class MnemosUnavailableError(RuntimeError):
    """Raised when Mnemos cannot be reached after all retries.

    The caller catches this and falls back to the local JSONL store.
    Carries the last exception for debugging.
    """

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause


def _resolve_base_url() -> str:
    """Return the Mnemos base URL from env or the default."""
    return os.environ.get(ENV_BASE_URL, DEFAULT_BASE_URL).rstrip("/")


class MnemosClient:
    """Sync REST client for the 5 A2A-relevant Mnemos endpoints.

    Args:
        base_url: Mnemos HTTP root. Defaults to ``$MNEMOS_BASE_URL`` or
            ``http://127.0.0.1:8787``.
        timeout: per-request timeout in seconds.
        max_retries: number of attempts before giving up.
        backoffs: tuple of seconds to sleep before each retry.
        client: optional pre-built ``httpx.Client`` (for testing with
            ``MockTransport``). If omitted, a new client is created.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = REQUEST_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        backoffs: tuple[float, ...] = RETRY_BACKOFFS,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = (base_url or _resolve_base_url()).rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoffs = backoffs
        self._client = client  # lazy: created on first request if None

    # ------------------------------------------------------------------ #
    # Public API — one method per A2A endpoint
    # ------------------------------------------------------------------ #

    def create_session(
        self,
        user_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/sessions`` — create a new Mnemos session.

        Returns the session dict (``session_id``, ``created_at``, ...).
        """
        body: dict[str, Any] = {"user_id": user_id}
        if metadata:
            body["metadata"] = metadata
        return self._request("POST", "/v1/sessions", json=body)

    def get_session(self, session_id: str) -> dict[str, Any]:
        """``GET /v1/sessions/{id}`` — fetch session metadata."""
        return self._request("GET", f"/v1/sessions/{session_id}")

    def write_turn(self, session_id: str, turn: dict[str, Any]) -> dict[str, Any]:
        """``POST /v1/sessions/{id}/turns`` — append a turn (A2A message).

        The ``turn`` dict must include ``message_id`` for idempotency;
        Mnemos deduplicates on that field so retries are safe.
        """
        return self._request("POST", f"/v1/sessions/{session_id}/turns", json=turn)

    def get_turn(
        self,
        session_id: str,
        turn_id: str,
        mode: str = "summary",
    ) -> dict[str, Any]:
        """``GET  /v1/sessions/{id}/turns/{turn_id}?mode=...`` — fetch one turn."""
        return self._request(
            "GET",
            f"/v1/sessions/{session_id}/turns/{turn_id}",
            params={"mode": mode},
        )

    def get_turn_range(
        self,
        session_id: str,
        from_step: int,
        to_step: int,
        mode: str = "summary",
    ) -> dict[str, Any]:
        """``POST /v1/sessions/{id}/turns/range`` — fetch a slice of turns."""
        body = {"from_step": from_step, "to_step": to_step, "mode": mode}
        return self._request(
            "POST",
            f"/v1/sessions/{session_id}/turns/range",
            json=body,
        )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _ensure_client(self) -> httpx.Client:
        """Lazily create the httpx client (so tests can inject a mock)."""
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute an HTTP request with retry/backoff on 5xx and conn errors.

        Raises:
            MnemosUnavailableError: after all retries are exhausted.
        """
        url = f"{self._base_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                client = self._ensure_client()
                resp = client.request(
                    method,
                    url,
                    json=json,
                    params=params,
                    timeout=self._timeout,
                )
            except httpx.ConnectError as exc:
                last_exc = exc
                self._sleep_before_retry(attempt)
                continue
            except httpx.TimeoutException as exc:
                last_exc = exc
                self._sleep_before_retry(attempt)
                continue
            except httpx.HTTPError as exc:
                # Other transport errors — retry once, then give up.
                last_exc = exc
                self._sleep_before_retry(attempt)
                continue

            # 2xx → success
            if 200 <= resp.status_code < 300:
                data: dict[str, Any] = resp.json()
                return data

            # 5xx → retry
            if 500 <= resp.status_code < 600:
                last_exc = httpx.HTTPStatusError(
                    f"Mnemos returned {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
                self._sleep_before_retry(attempt)
                continue

            # 4xx → don't retry (client error)
            raise MnemosUnavailableError(
                f"Mnemos returned {resp.status_code}: {resp.text}",
                cause=last_exc,
            )

        raise MnemosUnavailableError(
            f"Mnemos unavailable after {self._max_retries} attempts: {last_exc}",
            cause=last_exc,
        )

    def _sleep_before_retry(self, attempt: int) -> None:
        """Sleep before the next retry attempt (no-op for attempt 1)."""
        if attempt < len(self._backoffs) + 1:
            time.sleep(self._backoffs[attempt - 1])
