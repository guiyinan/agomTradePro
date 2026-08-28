"""Validation helpers for reconciliation evidence persistence."""

from __future__ import annotations

import uuid

from .reconciliation_models import ReconciliationEvidenceModel


def evidence_uuid(value: str) -> uuid.UUID:
    """Convert a domain evidence identifier into a database UUID."""

    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError("reconciliation evidence_id must be a UUID") from exc


def validated_alias(value: object) -> str:
    """Return one bounded Django database alias or raise."""

    if (
        type(value) is not str
        or not value
        or len(value) > 64
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError("reconciliation database alias is invalid")
    return value


def row_matches_evidence(
    row: ReconciliationEvidenceModel,
    defaults: dict[str, object],
) -> bool:
    """Compare all immutable evidence fields while excluding ORM timestamps."""

    return all(getattr(row, field) == value for field, value in defaults.items())


__all__ = ["evidence_uuid", "row_matches_evidence", "validated_alias"]
