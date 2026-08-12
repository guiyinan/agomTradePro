"""Strict JSON codec for Signal realization-source definition evidence."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.signal.domain.forecast_realization_owner import (
    ForecastRealizationManifestSource,
    ForecastRealizationMemberSource,
)
from apps.signal.domain.forecast_realization_source_definition import (
    ForecastRealizationSourceDefinition,
)

_DEFINITION_KEYS = frozenset(
    {
        "definition_version",
        "owner",
        "source",
        "registered_at",
        "research_only",
        "must_not_use_for_decision",
        "must_not_execute",
        "content_hash",
    }
)
_SOURCE_KEYS = frozenset(
    {
        "source_version",
        "owner_record_id",
        "owner_record_version",
        "result_id",
        "result_version",
        "result_hash",
        "calendar_id",
        "calendar_version",
        "period_id",
        "period_version",
        "period_hash",
        "period_start",
        "period_end",
        "available_at",
        "valid_until",
        "evidence_ref",
        "members",
        "content_hash",
    }
)
_MEMBER_KEYS = frozenset(
    {
        "source_version",
        "entry_id",
        "observation_id",
        "observation_version",
        "expected_observation_hash",
        "forecast_group_id",
        "pit_manifest_version",
        "pit_manifest_hash",
        "censoring_rule_version",
        "outcome_evidence_valid_until",
        "available_at",
        "evidence_ref",
        "content_hash",
    }
)


class ForecastRealizationSourceDefinitionCodecError(ValueError):
    """A persisted canonical payload has missing, surplus, or invalid fields."""


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ForecastRealizationSourceDefinitionCodecError(
            "definition datetime must be timezone-aware"
        )
    return value.astimezone(UTC).isoformat()


def _exact_dict(value: object, *, label: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ForecastRealizationSourceDefinitionCodecError(f"{label} must be an exact object")
    return value


def _require_keys(
    value: dict[str, object],
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    if frozenset(value) != expected:
        raise ForecastRealizationSourceDefinitionCodecError(f"{label} keys are invalid")


def _string(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise ForecastRealizationSourceDefinitionCodecError(f"{label} must be a string")
    return value


def _boolean(value: object, *, label: str) -> bool:
    if type(value) is not bool:
        raise ForecastRealizationSourceDefinitionCodecError(f"{label} must be a boolean")
    return value


def _datetime(value: object, *, label: str) -> datetime:
    text = _string(value, label=label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ForecastRealizationSourceDefinitionCodecError(
            f"{label} must be an ISO datetime"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ForecastRealizationSourceDefinitionCodecError(f"{label} must be timezone-aware")
    if _utc_text(parsed) != text:
        raise ForecastRealizationSourceDefinitionCodecError(f"{label} must use canonical UTC text")
    return parsed


def _encode_member(value: ForecastRealizationMemberSource) -> dict[str, object]:
    ForecastRealizationMemberSource.__post_init__(value)
    return {
        "source_version": value.source_version,
        "entry_id": value.entry_id,
        "observation_id": value.observation_id,
        "observation_version": value.observation_version,
        "expected_observation_hash": value.expected_observation_hash,
        "forecast_group_id": value.forecast_group_id,
        "pit_manifest_version": value.pit_manifest_version,
        "pit_manifest_hash": value.pit_manifest_hash,
        "censoring_rule_version": value.censoring_rule_version,
        "outcome_evidence_valid_until": _utc_text(value.outcome_evidence_valid_until),
        "available_at": _utc_text(value.available_at),
        "evidence_ref": value.evidence_ref,
        "content_hash": value.content_hash,
    }


def _encode_source(value: ForecastRealizationManifestSource) -> dict[str, object]:
    ForecastRealizationManifestSource.__post_init__(value)
    return {
        "source_version": value.source_version,
        "owner_record_id": value.owner_record_id,
        "owner_record_version": value.owner_record_version,
        "result_id": value.result_id,
        "result_version": value.result_version,
        "result_hash": value.result_hash,
        "calendar_id": value.calendar_id,
        "calendar_version": value.calendar_version,
        "period_id": value.period_id,
        "period_version": value.period_version,
        "period_hash": value.period_hash,
        "period_start": _utc_text(value.period_start),
        "period_end": _utc_text(value.period_end),
        "available_at": _utc_text(value.available_at),
        "valid_until": _utc_text(value.valid_until),
        "evidence_ref": value.evidence_ref,
        "members": [_encode_member(member) for member in value.members],
        "content_hash": value.content_hash,
    }


def encode_forecast_realization_source_definition(
    value: ForecastRealizationSourceDefinition,
) -> dict[str, object]:
    """Encode one recursively validated definition to canonical JSON values."""

    try:
        definition = value.validated_copy()
    except (AttributeError, TypeError, ValueError) as error:
        raise ForecastRealizationSourceDefinitionCodecError(
            "definition cannot be encoded"
        ) from error
    return {
        "definition_version": definition.definition_version,
        "owner": definition.owner,
        "source": _encode_source(definition.source),
        "registered_at": _utc_text(definition.registered_at),
        "research_only": definition.research_only,
        "must_not_use_for_decision": definition.must_not_use_for_decision,
        "must_not_execute": definition.must_not_execute,
        "content_hash": definition.content_hash,
    }


def _decode_member(value: object) -> ForecastRealizationMemberSource:
    payload = _exact_dict(value, label="definition member")
    _require_keys(payload, _MEMBER_KEYS, label="definition member")
    return ForecastRealizationMemberSource(
        source_version=_string(payload["source_version"], label="member source_version"),
        entry_id=_string(payload["entry_id"], label="member entry_id"),
        observation_id=_string(payload["observation_id"], label="member observation_id"),
        observation_version=_string(
            payload["observation_version"], label="member observation_version"
        ),
        expected_observation_hash=_string(
            payload["expected_observation_hash"],
            label="member expected_observation_hash",
        ),
        forecast_group_id=_string(payload["forecast_group_id"], label="member forecast_group_id"),
        pit_manifest_version=_string(
            payload["pit_manifest_version"], label="member pit_manifest_version"
        ),
        pit_manifest_hash=_string(payload["pit_manifest_hash"], label="member pit_manifest_hash"),
        censoring_rule_version=_string(
            payload["censoring_rule_version"],
            label="member censoring_rule_version",
        ),
        outcome_evidence_valid_until=_datetime(
            payload["outcome_evidence_valid_until"],
            label="member outcome_evidence_valid_until",
        ),
        available_at=_datetime(payload["available_at"], label="member available_at"),
        evidence_ref=_string(payload["evidence_ref"], label="member evidence_ref"),
        content_hash=_string(payload["content_hash"], label="member content_hash"),
    )


def _decode_source(value: object) -> ForecastRealizationManifestSource:
    payload = _exact_dict(value, label="definition source")
    _require_keys(payload, _SOURCE_KEYS, label="definition source")
    raw_members = payload["members"]
    if type(raw_members) is not list:
        raise ForecastRealizationSourceDefinitionCodecError(
            "definition source members must be an exact list"
        )
    return ForecastRealizationManifestSource(
        source_version=_string(payload["source_version"], label="source source_version"),
        owner_record_id=_string(payload["owner_record_id"], label="source owner_record_id"),
        owner_record_version=_string(
            payload["owner_record_version"], label="source owner_record_version"
        ),
        result_id=_string(payload["result_id"], label="source result_id"),
        result_version=_string(payload["result_version"], label="source result_version"),
        result_hash=_string(payload["result_hash"], label="source result_hash"),
        calendar_id=_string(payload["calendar_id"], label="source calendar_id"),
        calendar_version=_string(payload["calendar_version"], label="source calendar_version"),
        period_id=_string(payload["period_id"], label="source period_id"),
        period_version=_string(payload["period_version"], label="source period_version"),
        period_hash=_string(payload["period_hash"], label="source period_hash"),
        period_start=_datetime(payload["period_start"], label="source period_start"),
        period_end=_datetime(payload["period_end"], label="source period_end"),
        available_at=_datetime(payload["available_at"], label="source available_at"),
        valid_until=_datetime(payload["valid_until"], label="source valid_until"),
        evidence_ref=_string(payload["evidence_ref"], label="source evidence_ref"),
        members=tuple(_decode_member(member) for member in raw_members),
        content_hash=_string(payload["content_hash"], label="source content_hash"),
    )


def decode_forecast_realization_source_definition(
    value: object,
) -> ForecastRealizationSourceDefinition:
    """Decode only the exact canonical schema and recursively validate seals."""

    try:
        payload = _exact_dict(value, label="source definition")
        _require_keys(payload, _DEFINITION_KEYS, label="source definition")
        definition = ForecastRealizationSourceDefinition(
            definition_version=_string(payload["definition_version"], label="definition_version"),
            owner=_string(payload["owner"], label="definition owner"),
            source=_decode_source(payload["source"]),
            registered_at=_datetime(payload["registered_at"], label="registered_at"),
            research_only=_boolean(payload["research_only"], label="research_only"),
            must_not_use_for_decision=_boolean(
                payload["must_not_use_for_decision"],
                label="must_not_use_for_decision",
            ),
            must_not_execute=_boolean(payload["must_not_execute"], label="must_not_execute"),
            content_hash=_string(payload["content_hash"], label="definition content_hash"),
        )
        return definition.validated_copy()
    except ForecastRealizationSourceDefinitionCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise ForecastRealizationSourceDefinitionCodecError(
            "source definition payload is invalid"
        ) from error


__all__ = [
    "ForecastRealizationSourceDefinitionCodecError",
    "decode_forecast_realization_source_definition",
    "encode_forecast_realization_source_definition",
]
