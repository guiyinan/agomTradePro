"""Pure domain values and validation for semantic-key governance."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from .entities import CapabilityDefinition

SemanticCorrectionAction = Literal["set", "remove"]

_SEMANTIC_KEY_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
)
_MAX_SEMANTIC_KEY_LENGTH = 255
_MAX_BATCH_CORRECTIONS = 100


class SemanticIdempotencyConflict(ValueError):
    """Raised when an idempotency key is reused with a different payload."""


def normalize_semantic_key(value: str) -> str:
    """Return a validated lower-case dot-notation semantic key."""

    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > _MAX_SEMANTIC_KEY_LENGTH
        or _SEMANTIC_KEY_PATTERN.fullmatch(normalized) is None
    ):
        raise ValueError(
            "semantic key must be lower-case dot notation with at least two "
            "letter-led segments and at most 255 characters"
        )
    return normalized


@dataclass(frozen=True)
class SemanticCorrection:
    """One ordered semantic-key override operation."""

    capability_key: str
    action: SemanticCorrectionAction
    semantic_key: str | None = None

    def __post_init__(self) -> None:
        """Normalize and validate the correction."""

        capability_key = self.capability_key.strip()
        action = self.action.strip()
        if not capability_key:
            raise ValueError("capability key must not be empty")
        if action not in {"set", "remove"}:
            raise ValueError("action must be either 'set' or 'remove'")

        semantic_key = self.semantic_key
        if action == "set":
            if semantic_key is None or not semantic_key.strip():
                raise ValueError("set action requires semantic_key")
            semantic_key = normalize_semantic_key(semantic_key)
        elif semantic_key is not None:
            raise ValueError("remove action must not include semantic_key")

        object.__setattr__(self, "capability_key", capability_key)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "semantic_key", semantic_key)


@dataclass(frozen=True)
class SemanticCorrectionBatch:
    """A bounded, idempotent, ordered semantic correction request."""

    idempotency_key: str
    reason: str
    corrections: tuple[SemanticCorrection, ...]

    def __post_init__(self) -> None:
        """Normalize metadata and enforce batch invariants."""

        idempotency_key = self.idempotency_key.strip()
        reason = self.reason.strip()
        corrections = tuple(self.corrections)

        if not idempotency_key:
            raise ValueError("idempotency key must not be empty")
        if not reason:
            raise ValueError("reason must not be empty")
        if not corrections:
            raise ValueError("batch requires at least one correction")
        if len(corrections) > _MAX_BATCH_CORRECTIONS:
            raise ValueError("batch contains at most 100 corrections")

        capability_keys = [correction.capability_key for correction in corrections]
        if len(set(capability_keys)) != len(capability_keys):
            raise ValueError("batch contains duplicate capability keys")

        object.__setattr__(self, "idempotency_key", idempotency_key)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "corrections", corrections)


@dataclass(frozen=True)
class SemanticValueSnapshot:
    """Collected and currently effective values for one capability."""

    capability_key: str
    collected_semantic_key: str
    effective_semantic_key: str


@dataclass(frozen=True)
class SemanticCatalogCapability:
    """Catalog capability paired with its original collected semantic key."""

    capability: CapabilityDefinition
    collected_semantic_key: str


@dataclass(frozen=True)
class SemanticAuditEntry:
    """Immutable audit evidence for one persisted correction."""

    batch_id: UUID
    idempotency_key: str
    capability_key: str
    action: SemanticCorrectionAction
    old_collected_value: str
    old_effective_value: str
    new_effective_value: str
    reason: str
    operator_id: int | None
    request_fingerprint: str
    created_at: datetime


@dataclass(frozen=True)
class SemanticBatchPersistence:
    """Persisted outcome for an original or replayed correction batch."""

    batch_id: UUID
    request_fingerprint: str
    replayed: bool
    entries: tuple[SemanticAuditEntry, ...]


def canonical_batch_fingerprint(batch: SemanticCorrectionBatch) -> str:
    """Return the stable SHA-256 fingerprint for a correction batch payload."""

    payload = {
        "reason": batch.reason,
        "corrections": [
            {
                "capability_key": correction.capability_key,
                "action": correction.action,
                "semantic_key": correction.semantic_key,
            }
            for correction in batch.corrections
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
