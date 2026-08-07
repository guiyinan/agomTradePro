"""Complete FixedIncome-owned record seal for downstream R5 research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.fixed_income.domain.evidence import canonical_hash as _strict_canonical_hash
from apps.fixed_income.domain.evidence import (
    require_aware,
    require_sha256,
    require_token,
)
from apps.fixed_income.domain.relative_value_assessment import (
    R5RelativeValueAssessment,
    R5RelativeValueStatus,
)


def _canonical_hash(payload: object) -> str:
    """Hash after narrowing payload list syntax to exact tuples."""

    return _strict_canonical_hash(_tuple_payload(payload))


def _tuple_payload(value: object) -> object:
    if isinstance(value, list):
        return tuple(_tuple_payload(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_tuple_payload(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _tuple_payload(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class R5RelativeValueOwnerRecordSeal:
    """Full exact projection of one persisted fixed-income receipt/result bundle."""

    owner: str
    owner_record_key: str
    result_id: str
    result_version: str
    result_record_hash: str
    receipt_id: str
    receipt_version: str
    receipt_hash: str
    command_hash: str
    evidence_clock_graph_hash: str
    recorded_at: datetime
    assessment: R5RelativeValueAssessment
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        result_id: str,
        result_version: str,
        result_record_hash: str,
        receipt_id: str,
        receipt_version: str,
        receipt_hash: str,
        command_hash: str,
        evidence_clock_graph_hash: str,
        recorded_at: datetime,
        assessment: R5RelativeValueAssessment,
    ) -> R5RelativeValueOwnerRecordSeal:
        """Seal every promotion-relevant field from an exact owner bundle."""

        payload = _record_payload(
            result_id=result_id,
            result_version=result_version,
            result_record_hash=result_record_hash,
            receipt_id=receipt_id,
            receipt_version=receipt_version,
            receipt_hash=receipt_hash,
            command_hash=command_hash,
            evidence_clock_graph_hash=evidence_clock_graph_hash,
            recorded_at=recorded_at,
            assessment=assessment,
        )
        digest = _canonical_hash(payload)
        return cls(
            owner="fixed_income",
            owner_record_key=f"r5-rv-owner:{digest}",
            result_id=result_id,
            result_version=result_version,
            result_record_hash=result_record_hash,
            receipt_id=receipt_id,
            receipt_version=receipt_version,
            receipt_hash=receipt_hash,
            command_hash=command_hash,
            evidence_clock_graph_hash=evidence_clock_graph_hash,
            recorded_at=recorded_at,
            assessment=assessment,
            content_hash=digest,
            research_only=True,
            must_not_use_for_decision=True,
            must_not_execute=True,
        )

    def __post_init__(self) -> None:
        if self.owner != "fixed_income":
            raise ValueError("R5 promotion result record must be fixed_income-owned")
        for field_name in (
            "owner_record_key",
            "result_id",
            "result_version",
            "receipt_id",
            "receipt_version",
        ):
            require_token(
                str(getattr(self, field_name)),
                f"R5 promotion owner record {field_name}",
                maximum=300,
            )
        for field_name in (
            "result_record_hash",
            "receipt_hash",
            "command_hash",
            "evidence_clock_graph_hash",
            "content_hash",
        ):
            require_sha256(
                str(getattr(self, field_name)),
                f"R5 promotion owner record {field_name}",
            )
        require_aware(self.recorded_at, "R5 promotion owner record recorded_at")
        if self.recorded_at < self.assessment.evaluated_at:
            raise ValueError("R5 promotion owner record predates its assessment")
        if self.assessment.output_hash != self.assessment.calculated_output_hash:
            raise ValueError("R5 promotion owner assessment is not replayable")
        if not (
            self.research_only
            and self.must_not_use_for_decision
            and self.must_not_execute
            and self.assessment.research_only
            and self.assessment.must_not_use_for_decision
            and self.assessment.must_not_execute
        ):
            raise ValueError("R5 promotion owner record must remain research-only")
        expected = r5_relative_value_owner_record_seal_hash(self)
        if self.content_hash != expected or self.owner_record_key != f"r5-rv-owner:{expected}":
            raise ValueError("R5 promotion owner record content hash or identity mismatch")

    @property
    def is_assessment_available(self) -> bool:
        """Return the exact fixed-income composite availability state."""

        return self.assessment.status is R5RelativeValueStatus.AVAILABLE


def _record_payload(
    *,
    result_id: str,
    result_version: str,
    result_record_hash: str,
    receipt_id: str,
    receipt_version: str,
    receipt_hash: str,
    command_hash: str,
    evidence_clock_graph_hash: str,
    recorded_at: datetime,
    assessment: R5RelativeValueAssessment,
) -> dict[str, object]:
    return {
        "schema": "research-r5-relative-value-owner-record-seal.v1",
        "owner": "fixed_income",
        "result": [result_id, result_version, result_record_hash],
        "receipt": [receipt_id, receipt_version, receipt_hash],
        "command_hash": command_hash,
        "evidence_clock_graph_hash": evidence_clock_graph_hash,
        "recorded_at": recorded_at,
        "assessment": assessment,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def r5_relative_value_owner_record_seal_hash(
    record: R5RelativeValueOwnerRecordSeal,
) -> str:
    """Recompute the full exact fixed-income owner-record projection hash."""

    return _canonical_hash(
        _record_payload(
            result_id=record.result_id,
            result_version=record.result_version,
            result_record_hash=record.result_record_hash,
            receipt_id=record.receipt_id,
            receipt_version=record.receipt_version,
            receipt_hash=record.receipt_hash,
            command_hash=record.command_hash,
            evidence_clock_graph_hash=record.evidence_clock_graph_hash,
            recorded_at=record.recorded_at,
            assessment=record.assessment,
        )
    )


__all__ = [
    "R5RelativeValueOwnerRecordSeal",
    "r5_relative_value_owner_record_seal_hash",
]
