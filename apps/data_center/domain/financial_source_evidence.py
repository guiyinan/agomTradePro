"""Typed source evidence carried by financial facts.

This module is intentionally independent from Django and provider transports.
It represents only the three source fields already present on
``FinancialFactModel``.  Response scope and completion metadata belong to a
separate evidence layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class FinancialFactSourceEvidence:
    """Preserve optional vendor identity and announcement evidence on a fact.

    ``None`` means that the source did not provide the corresponding value.
    Partial values remain explicit, but ``is_complete`` is false until all
    three fields meet this legacy bridge's shape checks.  This object does not
    prove response scope, acquisition completion, availability, or source
    lineage, and no timestamp is inferred from it.
    """

    announced_at: datetime | None = None
    source_record_id: str | None = None
    raw_payload_hash: str | None = None

    def __post_init__(self) -> None:
        """Reject naive timestamps and padded source identifiers."""

        if self.announced_at is not None and (
            self.announced_at.tzinfo is None or self.announced_at.utcoffset() is None
        ):
            raise ValueError("FinancialFactSourceEvidence.announced_at must be timezone-aware")
        for field_name, value in (
            ("source_record_id", self.source_record_id),
            ("raw_payload_hash", self.raw_payload_hash),
        ):
            if value is not None and not isinstance(value, str):
                raise ValueError(f"FinancialFactSourceEvidence.{field_name} must be text")
            if value is not None and value and value.strip() != value:
                raise ValueError(f"FinancialFactSourceEvidence.{field_name} cannot be padded")

    @property
    def is_complete(self) -> bool:
        """Return whether the three persisted fields have valid shapes.

        The result is only a typed-field completeness check.  Transport bytes,
        response scope, completion time, and independent source lineage remain
        outside this legacy Domain value.
        """

        return (
            self.announced_at is not None
            and self.source_record_id is not None
            and bool(self.source_record_id)
            and self.raw_payload_hash is not None
            and _is_sha256(self.raw_payload_hash)
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize the fields without adding availability or fetch times."""

        return {
            "announced_at": self.announced_at.isoformat() if self.announced_at else None,
            "source_record_id": self.source_record_id,
            "raw_payload_hash": self.raw_payload_hash,
        }


def _is_sha256(value: str) -> bool:
    """Return whether ``value`` is one lowercase SHA-256 digest."""

    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = ["FinancialFactSourceEvidence"]
