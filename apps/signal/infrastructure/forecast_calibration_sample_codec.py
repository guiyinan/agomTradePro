"""Strict JSON codec for Signal-owned calibration sample evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import TypeVar
from uuid import UUID

from apps.signal.domain.forecast_calibration_sample import (
    ForecastCalibrationEntryOwnerRecord,
    ForecastCalibrationExpectedMember,
    ForecastCalibrationInvalidationEvidence,
    ForecastCalibrationResolution,
    ForecastCalibrationSampleDefinition,
    ForecastCalibrationSampleMemberReceipt,
    ForecastCalibrationSampleReceipt,
    ForecastCalibrationSampleSource,
)
from apps.signal.domain.forecast_scenario_evidence import ScenarioForecastBinding

_T = TypeVar("_T")


class ForecastCalibrationSampleCodecError(ValueError):
    """Raised when a persisted calibration payload is not exact and canonical."""


def _mapping(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ForecastCalibrationSampleCodecError(f"{label} must be an object")
    assert isinstance(value, dict)
    if any(type(key) is not str for key in value):
        raise ForecastCalibrationSampleCodecError(f"{label} keys must be strings")
    return value


def _keys(value: dict[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ForecastCalibrationSampleCodecError(f"{label} has unexpected or missing keys")


def _string(value: object, label: str) -> str:
    if type(value) is not str:
        raise ForecastCalibrationSampleCodecError(f"{label} must be a string")
    assert isinstance(value, str)
    return value


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ForecastCalibrationSampleCodecError(f"{label} must be a boolean")
    assert isinstance(value, bool)
    return value


def _optional_boolean(value: object, label: str) -> bool | None:
    if value is None:
        return None
    return _boolean(value, label)


def _time(value: object, label: str) -> datetime:
    text = _string(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ForecastCalibrationSampleCodecError(f"{label} must be an ISO datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ForecastCalibrationSampleCodecError(f"{label} must be timezone-aware")
    if parsed.isoformat(timespec="microseconds") != text:
        raise ForecastCalibrationSampleCodecError(f"{label} must use canonical datetime encoding")
    return parsed


def _optional_time(value: object, label: str) -> datetime | None:
    if value is None:
        return None
    return _time(value, label)


def _uuid(value: object, label: str) -> UUID:
    text = _string(value, label)
    try:
        parsed = UUID(text)
    except ValueError as exc:
        raise ForecastCalibrationSampleCodecError(f"{label} must be a UUID") from exc
    if str(parsed) != text:
        raise ForecastCalibrationSampleCodecError(f"{label} must use canonical UUID encoding")
    return parsed


def _optional_uuid(value: object, label: str) -> UUID | None:
    if value is None:
        return None
    return _uuid(value, label)


def _decimal(value: object, label: str) -> Decimal:
    text = _string(value, label)
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise ForecastCalibrationSampleCodecError(f"{label} must be a decimal string") from exc
    if not parsed.is_finite() or str(parsed) != text:
        raise ForecastCalibrationSampleCodecError(f"{label} must use canonical decimal encoding")
    return parsed


def _optional_decimal(value: object, label: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, label)


def _duration(value: object, label: str) -> timedelta:
    if type(value) is not int:
        raise ForecastCalibrationSampleCodecError(f"{label} must be integer microseconds")
    assert isinstance(value, int)
    return timedelta(microseconds=value)


def _array(value: object, label: str) -> list[object]:
    if type(value) is not list:
        raise ForecastCalibrationSampleCodecError(f"{label} must be an array")
    assert isinstance(value, list)
    return value


def _guard_decode(operation: Callable[[], _T]) -> _T:
    try:
        return operation()
    except ForecastCalibrationSampleCodecError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ForecastCalibrationSampleCodecError(
            "calibration payload violates the domain contract"
        ) from exc


def _encode_binding(value: ScenarioForecastBinding) -> dict[str, object]:
    if type(value) is not ScenarioForecastBinding:
        raise ForecastCalibrationSampleCodecError("binding must use the exact domain type")
    binding = ScenarioForecastBinding.from_values(
        scenario_revision_id=value.scenario_revision_id,
        scenario_set_revision_id=value.scenario_set_revision_id,
        subjective_probability=value.subjective_probability,
        subjective_probability_source_version=value.subjective_probability_source_version,
        model_probability=value.model_probability,
        model_probability_source_version=value.model_probability_source_version,
        model_promotion_decision_id=value.model_promotion_decision_id,
    )
    return {
        "scenario_revision_id": str(binding.scenario_revision_id),
        "scenario_set_revision_id": (
            None
            if binding.scenario_set_revision_id is None
            else str(binding.scenario_set_revision_id)
        ),
        "subjective_probability": str(binding.subjective_probability),
        "subjective_probability_source_version": binding.subjective_probability_source_version,
        "model_probability": (
            None if binding.model_probability is None else str(binding.model_probability)
        ),
        "model_probability_source_version": binding.model_probability_source_version,
        "model_promotion_decision_id": binding.model_promotion_decision_id,
    }


def _decode_binding(value: object) -> ScenarioForecastBinding:
    payload = _mapping(value, "binding")
    _keys(
        payload,
        {
            "scenario_revision_id",
            "scenario_set_revision_id",
            "subjective_probability",
            "subjective_probability_source_version",
            "model_probability",
            "model_probability_source_version",
            "model_promotion_decision_id",
        },
        "binding",
    )
    return ScenarioForecastBinding.from_values(
        scenario_revision_id=_uuid(payload["scenario_revision_id"], "scenario_revision_id"),
        scenario_set_revision_id=_optional_uuid(
            payload["scenario_set_revision_id"], "scenario_set_revision_id"
        ),
        subjective_probability=_decimal(
            payload["subjective_probability"], "subjective_probability"
        ),
        subjective_probability_source_version=_string(
            payload["subjective_probability_source_version"],
            "subjective_probability_source_version",
        ),
        model_probability=_optional_decimal(payload["model_probability"], "model_probability"),
        model_probability_source_version=_optional_string(
            payload["model_probability_source_version"],
            "model_probability_source_version",
        ),
        model_promotion_decision_id=_optional_string(
            payload["model_promotion_decision_id"],
            "model_promotion_decision_id",
        ),
    )


def _encode_invalidation(
    value: ForecastCalibrationInvalidationEvidence | None,
) -> dict[str, object] | None:
    if value is None:
        return None
    evidence = value.validated_copy()
    return {
        "evidence_version": evidence.evidence_version,
        "invalidated_at": evidence.invalidated_at.isoformat(timespec="microseconds"),
        "invalidation_rule_version": evidence.invalidation_rule_version,
        "evidence_refs": list(evidence.evidence_refs),
        "content_hash": evidence.content_hash,
    }


def _decode_invalidation(value: object) -> ForecastCalibrationInvalidationEvidence | None:
    if value is None:
        return None
    payload = _mapping(value, "invalidation")
    _keys(
        payload,
        {
            "evidence_version",
            "invalidated_at",
            "invalidation_rule_version",
            "evidence_refs",
            "content_hash",
        },
        "invalidation",
    )
    refs = tuple(
        _string(item, "evidence_ref") for item in _array(payload["evidence_refs"], "evidence_refs")
    )
    result = ForecastCalibrationInvalidationEvidence.create(
        evidence_version=_string(payload["evidence_version"], "evidence_version"),
        invalidated_at=_time(payload["invalidated_at"], "invalidated_at"),
        invalidation_rule_version=_string(
            payload["invalidation_rule_version"], "invalidation_rule_version"
        ),
        evidence_refs=refs,
    )
    if result.content_hash != _string(payload["content_hash"], "content_hash"):
        raise ForecastCalibrationSampleCodecError("invalidation content_hash mismatch")
    return result


def _encode_expected(value: ForecastCalibrationExpectedMember) -> dict[str, object]:
    member = value.validated_copy()
    return {
        "source_version": member.source_version,
        "entry_id": member.entry_id,
        "observation_version": member.observation_version,
        "forecast_group_id": member.forecast_group_id,
        "binding": _encode_binding(member.binding),
        "pit_manifest_id": member.pit_manifest_id,
        "pit_manifest_version": member.pit_manifest_version,
        "pit_manifest_hash": member.pit_manifest_hash,
        "censoring_rule_version": member.censoring_rule_version,
        "published_at": member.published_at.isoformat(timespec="microseconds"),
        "horizon_end": member.horizon_end.isoformat(timespec="microseconds"),
        "entry_recorded_at": member.entry_recorded_at.isoformat(timespec="microseconds"),
        "outcome_evidence_valid_until": member.outcome_evidence_valid_until.isoformat(
            timespec="microseconds"
        ),
        "evidence_ref": member.evidence_ref,
        "content_hash": member.content_hash,
    }


def _decode_expected(value: object) -> ForecastCalibrationExpectedMember:
    payload = _mapping(value, "expected_member")
    _keys(
        payload,
        {
            "source_version",
            "entry_id",
            "observation_version",
            "forecast_group_id",
            "binding",
            "pit_manifest_id",
            "pit_manifest_version",
            "pit_manifest_hash",
            "censoring_rule_version",
            "published_at",
            "horizon_end",
            "entry_recorded_at",
            "outcome_evidence_valid_until",
            "evidence_ref",
            "content_hash",
        },
        "expected_member",
    )
    result = ForecastCalibrationExpectedMember.create(
        entry_id=_string(payload["entry_id"], "entry_id"),
        observation_version=_string(payload["observation_version"], "observation_version"),
        forecast_group_id=_string(payload["forecast_group_id"], "forecast_group_id"),
        binding=_decode_binding(payload["binding"]),
        pit_manifest_id=_string(payload["pit_manifest_id"], "pit_manifest_id"),
        pit_manifest_version=_string(payload["pit_manifest_version"], "pit_manifest_version"),
        pit_manifest_hash=_string(payload["pit_manifest_hash"], "pit_manifest_hash"),
        censoring_rule_version=_string(payload["censoring_rule_version"], "censoring_rule_version"),
        published_at=_time(payload["published_at"], "published_at"),
        horizon_end=_time(payload["horizon_end"], "horizon_end"),
        entry_recorded_at=_time(payload["entry_recorded_at"], "entry_recorded_at"),
        outcome_evidence_valid_until=_time(
            payload["outcome_evidence_valid_until"],
            "outcome_evidence_valid_until",
        ),
        evidence_ref=_string(payload["evidence_ref"], "evidence_ref"),
    )
    if result.source_version != _string(payload["source_version"], "source_version"):
        raise ForecastCalibrationSampleCodecError("expected member source_version mismatch")
    if result.content_hash != _string(payload["content_hash"], "content_hash"):
        raise ForecastCalibrationSampleCodecError("expected member content_hash mismatch")
    return result


def _encode_source(value: ForecastCalibrationSampleSource) -> dict[str, object]:
    source = value.validated_copy()
    microseconds = int(source.forecast_horizon.total_seconds() * 1_000_000)
    return {
        "source_version": source.source_version,
        "sample_id": source.sample_id,
        "sample_version": source.sample_version,
        "scope_content_hash": source.scope_content_hash,
        "scenario_set_revision_id": str(source.scenario_set_revision_id),
        "scenario_revision_ids": [str(value) for value in source.scenario_revision_ids],
        "forecast_horizon_microseconds": microseconds,
        "censoring_rule_version": source.censoring_rule_version,
        "sample_window_start": source.sample_window_start.isoformat(timespec="microseconds"),
        "sample_window_end": source.sample_window_end.isoformat(timespec="microseconds"),
        "available_at": source.available_at.isoformat(timespec="microseconds"),
        "valid_until": source.valid_until.isoformat(timespec="microseconds"),
        "evidence_ref": source.evidence_ref,
        "members": [_encode_expected(member) for member in source.members],
        "content_hash": source.content_hash,
    }


def _decode_source(value: object) -> ForecastCalibrationSampleSource:
    payload = _mapping(value, "source")
    _keys(
        payload,
        {
            "source_version",
            "sample_id",
            "sample_version",
            "scope_content_hash",
            "scenario_set_revision_id",
            "scenario_revision_ids",
            "forecast_horizon_microseconds",
            "censoring_rule_version",
            "sample_window_start",
            "sample_window_end",
            "available_at",
            "valid_until",
            "evidence_ref",
            "members",
            "content_hash",
        },
        "source",
    )
    revisions = tuple(
        _uuid(item, "scenario_revision_id")
        for item in _array(payload["scenario_revision_ids"], "scenario_revision_ids")
    )
    members = tuple(_decode_expected(item) for item in _array(payload["members"], "members"))
    result = ForecastCalibrationSampleSource.create(
        sample_id=_string(payload["sample_id"], "sample_id"),
        sample_version=_string(payload["sample_version"], "sample_version"),
        scope_content_hash=_string(payload["scope_content_hash"], "scope_content_hash"),
        scenario_set_revision_id=_uuid(
            payload["scenario_set_revision_id"], "scenario_set_revision_id"
        ),
        scenario_revision_ids=revisions,
        forecast_horizon=_duration(
            payload["forecast_horizon_microseconds"],
            "forecast_horizon_microseconds",
        ),
        censoring_rule_version=_string(payload["censoring_rule_version"], "censoring_rule_version"),
        sample_window_start=_time(payload["sample_window_start"], "sample_window_start"),
        sample_window_end=_time(payload["sample_window_end"], "sample_window_end"),
        available_at=_time(payload["available_at"], "available_at"),
        valid_until=_time(payload["valid_until"], "valid_until"),
        evidence_ref=_string(payload["evidence_ref"], "evidence_ref"),
        members=members,
    )
    if result.source_version != _string(payload["source_version"], "source_version"):
        raise ForecastCalibrationSampleCodecError("source_version mismatch")
    if result.content_hash != _string(payload["content_hash"], "content_hash"):
        raise ForecastCalibrationSampleCodecError("source content_hash mismatch")
    return result


def _encode_definition(value: ForecastCalibrationSampleDefinition) -> dict[str, object]:
    definition = value.validated_copy()
    return {
        "definition_version": definition.definition_version,
        "source": _encode_source(definition.source),
        "registered_at": definition.registered_at.isoformat(timespec="microseconds"),
        "content_hash": definition.content_hash,
    }


def _decode_definition(value: object) -> ForecastCalibrationSampleDefinition:
    payload = _mapping(value, "definition")
    _keys(payload, {"definition_version", "source", "registered_at", "content_hash"}, "definition")
    result = ForecastCalibrationSampleDefinition.create(
        source=_decode_source(payload["source"]),
        registered_at=_time(payload["registered_at"], "registered_at"),
    )
    if result.definition_version != _string(payload["definition_version"], "definition_version"):
        raise ForecastCalibrationSampleCodecError("definition_version mismatch")
    if result.content_hash != _string(payload["content_hash"], "content_hash"):
        raise ForecastCalibrationSampleCodecError("definition content_hash mismatch")
    return result


def _encode_owner(value: ForecastCalibrationEntryOwnerRecord) -> dict[str, object]:
    owner = value.validated_copy()
    return {
        "source_version": owner.source_version,
        "entry_id": owner.entry_id,
        "binding": _encode_binding(owner.binding),
        "pit_manifest_id": owner.pit_manifest_id,
        "published_at": owner.published_at.isoformat(timespec="microseconds"),
        "horizon_end": owner.horizon_end.isoformat(timespec="microseconds"),
        "entry_recorded_at": owner.entry_recorded_at.isoformat(timespec="microseconds"),
        "resolution": owner.resolution.value,
        "scenario_realized": owner.scenario_realized,
        "outcome_recorded_at": (
            None
            if owner.outcome_recorded_at is None
            else owner.outcome_recorded_at.isoformat(timespec="microseconds")
        ),
        "outcome_source_type": owner.outcome_source_type,
        "outcome_source_hash": owner.outcome_source_hash,
        "invalidation": _encode_invalidation(owner.invalidation),
        "content_hash": owner.content_hash,
    }


def _decode_owner(value: object) -> ForecastCalibrationEntryOwnerRecord:
    payload = _mapping(value, "owner")
    _keys(
        payload,
        {
            "source_version",
            "entry_id",
            "binding",
            "pit_manifest_id",
            "published_at",
            "horizon_end",
            "entry_recorded_at",
            "resolution",
            "scenario_realized",
            "outcome_recorded_at",
            "outcome_source_type",
            "outcome_source_hash",
            "invalidation",
            "content_hash",
        },
        "owner",
    )
    try:
        resolution = ForecastCalibrationResolution(_string(payload["resolution"], "resolution"))
    except ValueError as exc:
        raise ForecastCalibrationSampleCodecError("resolution is unsupported") from exc
    result = ForecastCalibrationEntryOwnerRecord.create(
        entry_id=_string(payload["entry_id"], "entry_id"),
        binding=_decode_binding(payload["binding"]),
        pit_manifest_id=_string(payload["pit_manifest_id"], "pit_manifest_id"),
        published_at=_time(payload["published_at"], "published_at"),
        horizon_end=_time(payload["horizon_end"], "horizon_end"),
        entry_recorded_at=_time(payload["entry_recorded_at"], "entry_recorded_at"),
        resolution=resolution,
        scenario_realized=_optional_boolean(payload["scenario_realized"], "scenario_realized"),
        outcome_recorded_at=_optional_time(payload["outcome_recorded_at"], "outcome_recorded_at"),
        outcome_source_type=_optional_string(payload["outcome_source_type"], "outcome_source_type"),
        outcome_source_hash=_optional_string(payload["outcome_source_hash"], "outcome_source_hash"),
        invalidation=_decode_invalidation(payload["invalidation"]),
    )
    if result.source_version != _string(payload["source_version"], "source_version"):
        raise ForecastCalibrationSampleCodecError("owner source_version mismatch")
    if result.content_hash != _string(payload["content_hash"], "content_hash"):
        raise ForecastCalibrationSampleCodecError("owner content_hash mismatch")
    return result


def _encode_member_receipt(value: ForecastCalibrationSampleMemberReceipt) -> dict[str, object]:
    member = value.validated_copy()
    return {
        "receipt_version": member.receipt_version,
        "expected": _encode_expected(member.expected),
        "owner": _encode_owner(member.owner),
        "recorded_at": member.recorded_at.isoformat(timespec="microseconds"),
        "content_hash": member.content_hash,
    }


def _decode_member_receipt(value: object) -> ForecastCalibrationSampleMemberReceipt:
    payload = _mapping(value, "member_receipt")
    _keys(
        payload,
        {"receipt_version", "expected", "owner", "recorded_at", "content_hash"},
        "member_receipt",
    )
    result = ForecastCalibrationSampleMemberReceipt.from_sources(
        expected=_decode_expected(payload["expected"]),
        owner=_decode_owner(payload["owner"]),
        recorded_at=_time(payload["recorded_at"], "recorded_at"),
    )
    if result.receipt_version != _string(payload["receipt_version"], "receipt_version"):
        raise ForecastCalibrationSampleCodecError("member receipt_version mismatch")
    if result.content_hash != _string(payload["content_hash"], "content_hash"):
        raise ForecastCalibrationSampleCodecError("member content_hash mismatch")
    return result


def encode_forecast_calibration_sample_definition(
    value: ForecastCalibrationSampleDefinition,
) -> dict[str, object]:
    """Encode one recursively validated canonical definition."""

    try:
        if type(value) is not ForecastCalibrationSampleDefinition:
            raise ValueError("definition must use the exact domain type")
        return _encode_definition(value)
    except (TypeError, ValueError) as exc:
        raise ForecastCalibrationSampleCodecError("cannot encode calibration definition") from exc


def decode_forecast_calibration_sample_definition(
    value: object,
) -> ForecastCalibrationSampleDefinition:
    """Decode one strict definition payload and verify every seal."""

    return _guard_decode(lambda: _decode_definition(value))


def encode_forecast_calibration_sample_receipt(
    value: ForecastCalibrationSampleReceipt,
) -> dict[str, object]:
    """Encode one recursively validated exhaustive receipt."""

    try:
        if type(value) is not ForecastCalibrationSampleReceipt:
            raise ValueError("receipt must use the exact domain type")
        receipt = value.validated_copy()
        return {
            "receipt_version": receipt.receipt_version,
            "receipt_id": receipt.receipt_id,
            "definition": _encode_definition(receipt.definition),
            "pit_as_of": receipt.pit_as_of.isoformat(timespec="microseconds"),
            "recorded_at": receipt.recorded_at.isoformat(timespec="microseconds"),
            "members": [_encode_member_receipt(member) for member in receipt.members],
            "content_hash": receipt.content_hash,
        }
    except (TypeError, ValueError) as exc:
        raise ForecastCalibrationSampleCodecError("cannot encode calibration receipt") from exc


def decode_forecast_calibration_sample_receipt(value: object) -> ForecastCalibrationSampleReceipt:
    """Decode one strict receipt payload and verify complete membership."""

    def operation() -> ForecastCalibrationSampleReceipt:
        payload = _mapping(value, "receipt")
        _keys(
            payload,
            {
                "receipt_version",
                "receipt_id",
                "definition",
                "pit_as_of",
                "recorded_at",
                "members",
                "content_hash",
            },
            "receipt",
        )
        members = tuple(
            _decode_member_receipt(item) for item in _array(payload["members"], "members")
        )
        result = ForecastCalibrationSampleReceipt.create(
            definition=_decode_definition(payload["definition"]),
            pit_as_of=_time(payload["pit_as_of"], "pit_as_of"),
            recorded_at=_time(payload["recorded_at"], "recorded_at"),
            members=members,
        )
        if result.receipt_version != _string(payload["receipt_version"], "receipt_version"):
            raise ForecastCalibrationSampleCodecError("receipt_version mismatch")
        if result.receipt_id != _string(payload["receipt_id"], "receipt_id"):
            raise ForecastCalibrationSampleCodecError("receipt_id mismatch")
        if result.content_hash != _string(payload["content_hash"], "content_hash"):
            raise ForecastCalibrationSampleCodecError("receipt content_hash mismatch")
        return result

    return _guard_decode(operation)
