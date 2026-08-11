"""Load governed mechanism attestations for runtime capability-readiness checks."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from apps.research.application.capability_readiness_registry import (
    OwnerMechanismAttestation,
)
from apps.research.domain.capability_readiness import (
    ReadinessRequirement,
    is_mechanism_attestable_requirement,
)

_SCHEMA_VERSION = "research-capability-mechanism-attestations.v1"
_ENTRY_FIELDS = frozenset({"requirement", "owner", "observed_at", "valid_until", "evidence_ref"})
DEFAULT_ATTESTATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "governance"
    / "research_capability_mechanism_attestations.json"
)


def load_governed_mechanism_attestations(
    path: Path | None = None,
) -> tuple[OwnerMechanismAttestation, ...]:
    """Load and validate explicit owner attestations from the governance manifest."""

    source = path or DEFAULT_ATTESTATION_PATH
    try:
        raw: object = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("capability readiness attestation manifest is unreadable") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("capability readiness attestation manifest must be an object")
    if raw.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("capability readiness attestation schema_version is unsupported")
    raw_entries = raw.get("attestations")
    if not isinstance(raw_entries, list):
        raise ValueError("capability readiness attestations must be an array")

    attestations: list[OwnerMechanismAttestation] = []
    seen: set[ReadinessRequirement] = set()
    for index, raw_entry in enumerate(raw_entries):
        if not isinstance(raw_entry, Mapping) or any(not isinstance(key, str) for key in raw_entry):
            raise ValueError(f"capability readiness attestation {index} must be an object")
        if set(raw_entry) != _ENTRY_FIELDS:
            raise ValueError(
                f"capability readiness attestation {index} fields do not match the schema"
            )
        try:
            requirement = ReadinessRequirement(
                _required_text(raw_entry["requirement"], field="requirement")
            )
        except ValueError as exc:
            raise ValueError(
                f"capability readiness attestation {index} requirement is unsupported"
            ) from exc
        if not is_mechanism_attestable_requirement(requirement):
            raise ValueError(
                "capability readiness attestation "
                f"{index} requirement is not mechanism-attestable"
            )
        if requirement in seen:
            raise ValueError(f"duplicate governed mechanism attestation for {requirement.value}")
        seen.add(requirement)
        attestations.append(
            OwnerMechanismAttestation(
                requirement=requirement,
                owner=_required_text(raw_entry["owner"], field="owner"),
                observed_at=_timestamp(raw_entry["observed_at"], field="observed_at"),
                valid_until=_timestamp(raw_entry["valid_until"], field="valid_until"),
                evidence_ref=_required_text(
                    raw_entry["evidence_ref"],
                    field="evidence_ref",
                ),
            )
        )
    return tuple(attestations)


def _required_text(value: object, *, field: str) -> str:
    """Return one bounded non-blank manifest string."""

    if not isinstance(value, str):
        raise ValueError(f"capability readiness {field} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > 1_024 or "\x00" in normalized:
        raise ValueError(f"capability readiness {field} is invalid")
    return normalized


def _timestamp(value: object, *, field: str) -> datetime:
    """Parse an ISO-8601 timezone-aware manifest timestamp."""

    text = _required_text(value, field=field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"capability readiness {field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"capability readiness {field} must be timezone-aware")
    return parsed
