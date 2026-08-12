"""Fail-closed Evidence projection for one legacy Strategy decision."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from apps.research.application.evidence_summary import EvidenceSummaryDTO
from apps.research.domain.evidence_contracts import (
    ArtifactRef,
    ClaimKind,
    MethodKind,
    build_legacy_unverified_envelope,
)

_ARTIFACT_VERSION = "decision-result-v1"
_ACTIONS = frozenset({"allow", "deny", "watch"})


@dataclass(frozen=True, slots=True)
class LegacyStrategyDecisionProjection:
    """Data-only Strategy boundary projection supplied by composition."""

    action: str
    reason_codes: tuple[str, ...]
    reason_text: str
    valid_until: datetime
    confidence: float


def _require_aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    return value


def _require_bounded_text(value: object, field_name: str, *, maximum: int) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be bounded non-blank text")
    return value


def _validate_projection(
    projection: LegacyStrategyDecisionProjection, *, evaluated_at: datetime
) -> None:
    if type(projection) is not LegacyStrategyDecisionProjection:
        raise TypeError("projection must be an exact LegacyStrategyDecisionProjection")
    evaluation_clock = _require_aware(evaluated_at, "evaluated_at")
    validity_clock = _require_aware(projection.valid_until, "valid_until")
    if validity_clock <= evaluation_clock:
        raise ValueError("legacy Strategy decision is expired at evaluated_at")
    if projection.action not in _ACTIONS:
        raise ValueError("action must be a canonical Strategy decision action")
    if type(projection.reason_codes) is not tuple or not projection.reason_codes:
        raise ValueError("reason_codes must be a non-empty tuple")
    for reason_code in projection.reason_codes:
        _require_bounded_text(reason_code, "reason_code", maximum=128)
        if any(character.isspace() for character in reason_code):
            raise ValueError("reason_code must not contain whitespace")
    if projection.reason_codes != tuple(sorted(set(projection.reason_codes))):
        raise ValueError("reason_codes must be ordered and unique")
    _require_bounded_text(projection.reason_text, "reason_text", maximum=2_000)
    if (
        type(projection.confidence) is not float
        or not math.isfinite(projection.confidence)
        or not 0.0 <= projection.confidence <= 1.0
    ):
        raise ValueError("confidence must be a finite float between zero and one")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _content_hash(projection: LegacyStrategyDecisionProjection) -> str:
    payload = asdict(projection)
    payload["valid_until"] = _utc_text(projection.valid_until)
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_strategy_decision_legacy_evidence_summary(
    projection: LegacyStrategyDecisionProjection, *, evaluated_at: datetime
) -> EvidenceSummaryDTO:
    """Wrap one exact Strategy decision as legacy-unverified display-only Evidence."""

    _validate_projection(projection, evaluated_at=evaluated_at)
    content_hash = _content_hash(projection)
    artifact = ArtifactRef(
        owner="strategy",
        artifact_type="decision_result",
        artifact_id=content_hash,
        artifact_version=_ARTIFACT_VERSION,
        content_hash=content_hash,
    )
    envelope = build_legacy_unverified_envelope(
        output_artifact=artifact,
        claim_kind=ClaimKind.RECOMMENDATION,
        method_kind=MethodKind.DETERMINISTIC,
        evaluated_at=evaluated_at,
        valid_until=projection.valid_until,
    )
    return EvidenceSummaryDTO.from_legacy_envelope(envelope=envelope)


__all__ = [
    "LegacyStrategyDecisionProjection",
    "build_strategy_decision_legacy_evidence_summary",
]
