"""Strict canonical codecs for Research evidence ledgers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import cast

from apps.research.domain.evidence_contracts import (
    ArtifactRef,
    ClaimKind,
    DecisionPermission,
    DependencyFlag,
    EvidenceBlockerCode,
    EvidenceEnvelope,
    EvidenceOperatorSpec,
    GovernanceState,
    MethodKind,
    MetricDirection,
    TrackRecordSnapshot,
)


class EvidenceCodecError(ValueError):
    """A persisted evidence payload is not the one canonical representation."""


def encode_evidence_operator_spec(spec: EvidenceOperatorSpec) -> dict[str, object]:
    """Encode an exact operator specification to canonical JSON primitives."""

    return {
        "operator_id": spec.operator_id,
        "operator_version": spec.operator_version,
        "research_family": spec.research_family,
        "output_artifact_type": spec.output_artifact_type,
        "claim_kind": spec.claim_kind.value,
        "method_kind": spec.method_kind.value,
        "required_input_roles": list(spec.required_input_roles),
        "dependency_flags": sorted(item.value for item in spec.dependency_flags),
        "maximum_permission": spec.maximum_permission.value,
        "requires_track_record": spec.requires_track_record,
        "activated_at": _datetime_text(spec.activated_at),
        "valid_until": _datetime_text(spec.valid_until),
        "content_hash": spec.content_hash,
    }


def decode_evidence_operator_spec(payload: object) -> EvidenceOperatorSpec:
    """Restore an operator spec and reject non-canonical or hash-invalid data."""

    data = _exact_mapping(
        payload,
        {
            "operator_id",
            "operator_version",
            "research_family",
            "output_artifact_type",
            "claim_kind",
            "method_kind",
            "required_input_roles",
            "dependency_flags",
            "maximum_permission",
            "requires_track_record",
            "activated_at",
            "valid_until",
            "content_hash",
        },
    )
    try:
        spec = EvidenceOperatorSpec(
            operator_id=_string(data["operator_id"]),
            operator_version=_string(data["operator_version"]),
            research_family=_string(data["research_family"]),
            output_artifact_type=_string(data["output_artifact_type"]),
            claim_kind=ClaimKind(_string(data["claim_kind"])),
            method_kind=MethodKind(_string(data["method_kind"])),
            required_input_roles=_string_tuple(data["required_input_roles"]),
            dependency_flags=frozenset(
                DependencyFlag(item) for item in _string_tuple(data["dependency_flags"])
            ),
            maximum_permission=DecisionPermission(_string(data["maximum_permission"])),
            requires_track_record=_bool(data["requires_track_record"]),
            activated_at=_datetime(data["activated_at"]),
            valid_until=_datetime(data["valid_until"]),
            content_hash=_string(data["content_hash"]),
        )
    except (TypeError, ValueError) as error:
        raise EvidenceCodecError("operator specification payload is invalid") from error
    _require_canonical(payload, encode_evidence_operator_spec(spec))
    return spec


def encode_track_record_snapshot(snapshot: TrackRecordSnapshot) -> dict[str, object]:
    """Encode an exact Track Record snapshot to canonical JSON primitives."""

    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "artifact": snapshot.artifact.to_payload(),
        "target": snapshot.target,
        "horizon": snapshot.horizon,
        "sample_policy_id": snapshot.sample_policy_id,
        "sample_policy_version": snapshot.sample_policy_version,
        "evaluated_at": _datetime_text(snapshot.evaluated_at),
        "valid_until": _datetime_text(snapshot.valid_until),
        "eligible": snapshot.eligible,
        "resolved": snapshot.resolved,
        "unresolved": snapshot.unresolved,
        "censored": snapshot.censored,
        "invalidated": snapshot.invalidated,
        "n_eff": str(snapshot.n_eff),
        "coverage": str(snapshot.coverage),
        "market_regimes": list(snapshot.market_regimes),
        "primary_metric_code": snapshot.primary_metric_code,
        "primary_metric_unit": snapshot.primary_metric_unit,
        "metric_direction": (
            snapshot.metric_direction.value if snapshot.metric_direction is not None else None
        ),
        "primary_metric_value": _decimal_text(snapshot.primary_metric_value),
        "benchmark_metric_value": _decimal_text(snapshot.benchmark_metric_value),
        "skill_delta": _decimal_text(snapshot.skill_delta),
        "confidence_interval_low": _decimal_text(snapshot.confidence_interval_low),
        "confidence_interval_high": _decimal_text(snapshot.confidence_interval_high),
        "drift_detected": snapshot.drift_detected,
        "promotion_ref": snapshot.promotion_ref.to_payload(),
        "outcome_refs": [item.to_payload() for item in snapshot.outcome_refs],
        "content_hash": snapshot.content_hash,
    }


def decode_track_record_snapshot(payload: object) -> TrackRecordSnapshot:
    """Restore a Track Record and recompute its canonical Domain hash."""

    data = _exact_mapping(
        payload,
        {
            "snapshot_id",
            "snapshot_version",
            "artifact",
            "target",
            "horizon",
            "sample_policy_id",
            "sample_policy_version",
            "evaluated_at",
            "valid_until",
            "eligible",
            "resolved",
            "unresolved",
            "censored",
            "invalidated",
            "n_eff",
            "coverage",
            "market_regimes",
            "primary_metric_code",
            "primary_metric_unit",
            "metric_direction",
            "primary_metric_value",
            "benchmark_metric_value",
            "skill_delta",
            "confidence_interval_low",
            "confidence_interval_high",
            "drift_detected",
            "promotion_ref",
            "outcome_refs",
            "content_hash",
        },
    )
    try:
        direction_value = data["metric_direction"]
        snapshot = TrackRecordSnapshot(
            snapshot_id=_string(data["snapshot_id"]),
            snapshot_version=_string(data["snapshot_version"]),
            artifact=_artifact(data["artifact"]),
            target=_string(data["target"]),
            horizon=_string(data["horizon"]),
            sample_policy_id=_string(data["sample_policy_id"]),
            sample_policy_version=_string(data["sample_policy_version"]),
            evaluated_at=_datetime(data["evaluated_at"]),
            valid_until=_datetime(data["valid_until"]),
            eligible=_int(data["eligible"]),
            resolved=_int(data["resolved"]),
            unresolved=_int(data["unresolved"]),
            censored=_int(data["censored"]),
            invalidated=_int(data["invalidated"]),
            n_eff=_decimal(data["n_eff"]),
            coverage=_decimal(data["coverage"]),
            market_regimes=_string_tuple(data["market_regimes"]),
            primary_metric_code=_optional_string(data["primary_metric_code"]),
            primary_metric_unit=_optional_string(data["primary_metric_unit"]),
            metric_direction=(
                None if direction_value is None else MetricDirection(_string(direction_value))
            ),
            primary_metric_value=_optional_decimal(data["primary_metric_value"]),
            benchmark_metric_value=_optional_decimal(data["benchmark_metric_value"]),
            skill_delta=_optional_decimal(data["skill_delta"]),
            confidence_interval_low=_optional_decimal(data["confidence_interval_low"]),
            confidence_interval_high=_optional_decimal(data["confidence_interval_high"]),
            drift_detected=_bool(data["drift_detected"]),
            promotion_ref=_artifact(data["promotion_ref"]),
            outcome_refs=tuple(_artifact(item) for item in _list(data["outcome_refs"])),
            content_hash=_string(data["content_hash"]),
        )
    except (TypeError, ValueError) as error:
        raise EvidenceCodecError("track-record payload is invalid") from error
    _require_canonical(payload, encode_track_record_snapshot(snapshot))
    return snapshot


def encode_evidence_envelope(envelope: EvidenceEnvelope) -> dict[str, object]:
    """Encode an exact resolved Evidence Envelope."""

    return {
        "output_artifact": envelope.output_artifact.to_payload(),
        "operator_spec_ref": envelope.operator_spec_ref.to_payload(),
        "claim_kind": envelope.claim_kind.value,
        "method_kind": envelope.method_kind.value,
        "research_family": envelope.research_family,
        "governance_state": envelope.governance_state.value,
        "permission": envelope.permission.value,
        "lineage": [item.to_payload() for item in envelope.lineage],
        "dependency_flags": sorted(item.value for item in envelope.dependency_flags),
        "track_record_ref": (
            envelope.track_record_ref.to_payload()
            if envelope.track_record_ref is not None
            else None
        ),
        "blockers": [item.value for item in envelope.blockers],
        "evaluated_at": _datetime_text(envelope.evaluated_at),
        "valid_until": _datetime_text(envelope.valid_until),
        "content_hash": envelope.content_hash,
    }


def decode_evidence_envelope(payload: object) -> EvidenceEnvelope:
    """Restore an Envelope and recompute its canonical Domain hash."""

    data = _exact_mapping(
        payload,
        {
            "output_artifact",
            "operator_spec_ref",
            "claim_kind",
            "method_kind",
            "research_family",
            "governance_state",
            "permission",
            "lineage",
            "dependency_flags",
            "track_record_ref",
            "blockers",
            "evaluated_at",
            "valid_until",
            "content_hash",
        },
    )
    try:
        track_ref = data["track_record_ref"]
        envelope = EvidenceEnvelope(
            output_artifact=_artifact(data["output_artifact"]),
            operator_spec_ref=_artifact(data["operator_spec_ref"]),
            claim_kind=ClaimKind(_string(data["claim_kind"])),
            method_kind=MethodKind(_string(data["method_kind"])),
            research_family=_string(data["research_family"]),
            governance_state=GovernanceState(_string(data["governance_state"])),
            permission=DecisionPermission(_string(data["permission"])),
            lineage=tuple(_artifact(item) for item in _list(data["lineage"])),
            dependency_flags=frozenset(
                DependencyFlag(item) for item in _string_tuple(data["dependency_flags"])
            ),
            track_record_ref=None if track_ref is None else _artifact(track_ref),
            blockers=tuple(EvidenceBlockerCode(item) for item in _string_tuple(data["blockers"])),
            evaluated_at=_datetime(data["evaluated_at"]),
            valid_until=_datetime(data["valid_until"]),
            content_hash=_string(data["content_hash"]),
        )
    except (TypeError, ValueError) as error:
        raise EvidenceCodecError("evidence-envelope payload is invalid") from error
    _require_canonical(payload, encode_evidence_envelope(envelope))
    return envelope


def _artifact(value: object) -> ArtifactRef:
    data = _exact_mapping(
        value,
        {"owner", "artifact_type", "artifact_id", "artifact_version", "content_hash"},
    )
    return ArtifactRef(
        owner=_string(data["owner"]),
        artifact_type=_string(data["artifact_type"]),
        artifact_id=_string(data["artifact_id"]),
        artifact_version=_string(data["artifact_version"]),
        content_hash=_string(data["content_hash"]),
    )


def _exact_mapping(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise EvidenceCodecError("payload keys differ from the canonical schema")
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    if type(value) is not list:
        raise EvidenceCodecError("payload collection must be a list")
    return cast(list[object], value)


def _string(value: object) -> str:
    if type(value) is not str:
        raise EvidenceCodecError("payload scalar must be a string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    return tuple(_string(item) for item in _list(value))


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise EvidenceCodecError("payload scalar must be a bool")
    return value


def _int(value: object) -> int:
    if type(value) is not int:
        raise EvidenceCodecError("payload scalar must be an int")
    return value


def _decimal(value: object) -> Decimal:
    text = _string(value)
    try:
        return Decimal(text)
    except InvalidOperation as error:
        raise EvidenceCodecError("payload decimal is invalid") from error


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else _decimal(value)


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise EvidenceCodecError("payload datetime must be canonical UTC")
    try:
        result = datetime.fromisoformat(f"{text[:-1]}+00:00")
    except ValueError as error:
        raise EvidenceCodecError("payload datetime is invalid") from error
    if _datetime_text(result) != text:
        raise EvidenceCodecError("payload datetime is not canonical")
    return result


def _datetime_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _require_canonical(original: object, encoded: dict[str, object]) -> None:
    if original != encoded:
        raise EvidenceCodecError("payload differs from its canonical reconstruction")


__all__ = [
    "EvidenceCodecError",
    "decode_evidence_envelope",
    "decode_evidence_operator_spec",
    "decode_track_record_snapshot",
    "encode_evidence_envelope",
    "encode_evidence_operator_spec",
    "encode_track_record_snapshot",
]
