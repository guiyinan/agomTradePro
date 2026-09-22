"""Typed source evidence carried by financial facts.

This module is intentionally independent from Django and provider transports.
It represents only the three source fields already present on
``FinancialFactModel``.  Response scope and completion metadata belong to a
separate evidence layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import FinancialResponseScopeBasis
from apps.data_center.domain.financial_source_time_evidence import FinancialSourceTimeWitness

FINANCIAL_FACT_DATASET_KEY = "equity.financial.fact"


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


@dataclass(frozen=True, slots=True)
class FinancialFactDecisionEvidence:
    """Bind one parsed provider row to an immutable captured response artifact."""

    artifact_reference: FinancialResponseArtifactRef
    native_asset_code: str
    native_period_end: date
    native_row_id: str
    source_time_witness: FinancialSourceTimeWitness | None = None

    def __post_init__(self) -> None:
        """Require body-verified response scope and exact native row dimensions."""

        if not isinstance(self.artifact_reference, FinancialResponseArtifactRef):
            raise ValueError("FinancialFactDecisionEvidence.artifact_reference must be typed")
        for field_name, value in (
            ("native_asset_code", self.native_asset_code),
            ("native_row_id", self.native_row_id),
        ):
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"FinancialFactDecisionEvidence.{field_name} is invalid")
        if isinstance(self.native_period_end, datetime) or not isinstance(
            self.native_period_end, date
        ):
            raise ValueError("FinancialFactDecisionEvidence.native_period_end must be a date")

        evidence = self.artifact_reference.evidence
        request_scope = evidence.request_scope
        response_scope = evidence.response_scope
        if request_scope.dataset_key != FINANCIAL_FACT_DATASET_KEY:
            raise ValueError("financial decision evidence dataset is invalid")
        if evidence.response_scope_basis is not FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED:
            raise ValueError("financial decision evidence response scope is not body verified")
        if request_scope.asset_code != self.native_asset_code:
            raise ValueError("financial decision evidence request asset mismatch")
        if response_scope.row_count <= 0:
            raise ValueError("financial decision evidence response contains no rows")
        if self.native_period_end not in response_scope.period_ends:
            raise ValueError("financial decision evidence period is outside response scope")
        witness = self.source_time_witness
        if witness is not None:
            if not isinstance(witness, FinancialSourceTimeWitness):
                raise ValueError("financial source-time witness must be typed")
            if (
                witness.native_asset_code != self.native_asset_code
                or witness.native_period_end != self.native_period_end
                or witness.financial_native_row_id != self.native_row_id
                or witness.artifact_reference.provider_name
                != self.artifact_reference.evidence.request_scope.provider_name
            ):
                raise ValueError("financial source-time witness dimensions do not match")

    def to_dict(self) -> dict[str, object]:
        """Return the bounded binding without storage location or key metadata."""

        evidence = self.artifact_reference.evidence
        payload: dict[str, object] = {
            "capture_id": str(self.artifact_reference.capture_id),
            "body_sha256": evidence.body_sha256,
            "body_scope": evidence.body_scope.value,
            "response_scope_basis": evidence.response_scope_basis.value,
            "native_asset_code": self.native_asset_code,
            "native_period_end": self.native_period_end.isoformat(),
            "native_row_id": self.native_row_id,
        }
        if self.source_time_witness is not None:
            payload["source_time_witness"] = self.source_time_witness.to_dict()
        return payload


def _is_sha256(value: str) -> bool:
    """Return whether ``value`` is one lowercase SHA-256 digest."""

    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "FINANCIAL_FACT_DATASET_KEY",
    "FinancialFactDecisionEvidence",
    "FinancialFactSourceEvidence",
]
