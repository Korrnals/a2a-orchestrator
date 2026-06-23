"""JSON-schema validation for Agent Cards and A2A messages.

Loads the two schemas shipped under ``a2a_orchestrator/schemas/`` at
import time and exposes thin ``validate_*`` helpers. The schemas are
the source of truth for wire-format compatibility — bumping
``A2A_SCHEMA_VERSION`` in ``__init__.py`` must be done in lock-step
with the schema pin.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator

# Schema and card locations are resolved at import time by :mod:`.config`.
# This indirection keeps the package importable regardless of where it
# is installed (env vars ``A2A_SCHEMA_DIR`` / ``A2A_CARDS_DIR`` override
# the auto-detection; embedded schemas are the default).
from .config import A2A_MESSAGE_SCHEMA_PATH, AGENT_CARD_SCHEMA_PATH


def _load_schema(path: Path) -> dict:
    """Read a schema file and return its parsed JSON.

    Raises FileNotFoundError if the schema is missing — this is a fatal
    installation error and we fail loudly rather than silently degrading
    to a no-op validator.
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"Required JSON Schema not found: {path}. "
            "Check the embedded schemas under a2a_orchestrator/schemas/ "
            f"or set the A2A_SCHEMA_DIR environment variable."
        )
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


# Eager-load both schemas. Any failure to load is a hard error.
_AGENT_CARD_SCHEMA = _load_schema(AGENT_CARD_SCHEMA_PATH)
_A2A_MESSAGE_SCHEMA = _load_schema(A2A_MESSAGE_SCHEMA_PATH)

# Pre-build Draft-2020-12 validators for speed and clearer error messages.
_AGENT_CARD_VALIDATOR = Draft202012Validator(_AGENT_CARD_SCHEMA)
_A2A_MESSAGE_VALIDATOR = Draft202012Validator(_A2A_MESSAGE_SCHEMA)


class ValidationError(ValueError):
    """Raised when a payload fails JSON-schema validation.

    Carries the underlying ``jsonschema.ValidationError`` in ``__cause__``
    for debugging.
    """

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


def _format_errors(exc: jsonschema.ValidationError) -> list[str]:
    """Flatten a jsonschema exception into a list of human-readable lines.

    ``ValidationError`` raised by ``Validator.validate()`` represents a
    single error (not a collection). ``iter_errors`` is a method on the
    ``Validator`` class, not on the exception — so we format the
    exception itself, plus any ``context`` sub-errors (which appear when
    ``anyOf`` / ``oneOf`` matching fails).
    """
    out: list[str] = []
    path = "/".join(str(p) for p in exc.absolute_path) or "<root>"
    out.append(f"{path}: {exc.message}")
    # Sub-errors from anyOf/oneOf are in exc.context.
    for sub in getattr(exc, "context", []) or []:
        sub_path = "/".join(str(p) for p in sub.absolute_path) or "<root>"
        out.append(f"{sub_path}: {sub.message}")
    return out


def validate_agent_card(card: dict[str, Any]) -> None:
    """Validate a parsed Agent Card dict.

    Raises:
        ValidationError: if the card does not conform to the schema.
    """
    try:
        _AGENT_CARD_VALIDATOR.validate(card)
    except jsonschema.ValidationError as exc:
        raise ValidationError(
            f"Agent Card for id={card.get('id', '<unknown>')!r} failed schema validation",
            errors=_format_errors(exc),
        ) from exc


def validate_a2a_message(message: dict[str, Any]) -> None:
    """Validate a parsed A2A message dict.

    Raises:
        ValidationError: if the message does not conform to the wire format.
    """
    try:
        _A2A_MESSAGE_VALIDATOR.validate(message)
    except jsonschema.ValidationError as exc:
        raise ValidationError(
            f"A2A message id={message.get('message_id', '<unknown>')!r} "
            f"failed schema validation",
            errors=_format_errors(exc),
        ) from exc


def get_schemas() -> dict[str, dict]:
    """Return both schemas as a dict — for tests and debug tooling."""
    return {
        "agent_card": _AGENT_CARD_SCHEMA,
        "a2a_message": _A2A_MESSAGE_SCHEMA,
    }
