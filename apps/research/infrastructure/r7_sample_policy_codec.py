"""Strict canonical JSON codec for R7 sample policy ledgers."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast
from uuid import UUID

from apps.research.domain.r7_sample_policy import (
    PersistedR7SamplePolicy,
    R7SamplePolicyAuthorization,
)
from apps.research.domain.scenario_probability_contracts import (
    ScenarioProbabilityResearchPolicy,
    ScenarioResearchScope,
)

_AUTH_SCHEMA = "research.r7.sample-policy-authorization.v1"
_RECORD_SCHEMA = "research.r7.persisted-sample-policy.v1"


class R7SamplePolicyCodecError(ValueError):
    """Canonical R7 ledger payload is malformed or non-canonical."""


def encode_r7_sample_policy_authorization(
    authorization: R7SamplePolicyAuthorization,
) -> dict[str, object]:
    """Encode one exact owner authorization receipt."""

    return {"schema": _AUTH_SCHEMA, "body": _encode_authorization(authorization)}


def decode_r7_sample_policy_authorization(
    payload: object,
) -> R7SamplePolicyAuthorization:
    """Strictly decode and revalidate one authorization receipt."""

    body = _envelope(payload, _AUTH_SCHEMA)
    return _decode_authorization(body)


def encode_persisted_r7_sample_policy(
    record: PersistedR7SamplePolicy,
) -> dict[str, object]:
    """Encode the complete scope, policy, approval, clock, and safety graph."""

    return {
        "schema": _RECORD_SCHEMA,
        "body": {
            "policy_id": record.policy_id,
            "policy_version": record.policy_version,
            "scope": _encode_scope(record.scope),
            "policy": _encode_policy(record.policy),
            "authorization": _encode_authorization(record.authorization),
            "recorded_at": record.recorded_at.isoformat(),
            "research_only": record.research_only,
            "must_not_use_for_decision": record.must_not_use_for_decision,
            "must_not_execute": record.must_not_execute,
            "content_hash": record.content_hash,
        },
    }


def decode_persisted_r7_sample_policy(payload: object) -> PersistedR7SamplePolicy:
    """Strictly restore a complete persisted policy without permissive coercion."""

    body = _envelope(payload, _RECORD_SCHEMA)
    _keys(
        body,
        {
            "policy_id",
            "policy_version",
            "scope",
            "policy",
            "authorization",
            "recorded_at",
            "research_only",
            "must_not_use_for_decision",
            "must_not_execute",
            "content_hash",
        },
        "record body",
    )
    try:
        return PersistedR7SamplePolicy(
            policy_id=_string(body["policy_id"], "policy_id"),
            policy_version=_string(body["policy_version"], "policy_version"),
            scope=_decode_scope(_object(body["scope"], "scope")),
            policy=_decode_policy(_object(body["policy"], "policy")),
            authorization=_decode_authorization(_object(body["authorization"], "authorization")),
            recorded_at=_datetime(body["recorded_at"], "recorded_at"),
            research_only=_boolean(body["research_only"], "research_only"),
            must_not_use_for_decision=_boolean(
                body["must_not_use_for_decision"],
                "must_not_use_for_decision",
            ),
            must_not_execute=_boolean(body["must_not_execute"], "must_not_execute"),
            content_hash=_string(body["content_hash"], "content_hash"),
        )
    except (TypeError, ValueError) as exc:
        raise R7SamplePolicyCodecError(str(exc)) from exc


def _encode_authorization(value: R7SamplePolicyAuthorization) -> dict[str, object]:
    return {
        "owner": value.owner,
        "capability": value.capability,
        "purpose": value.purpose,
        "authorization_id": value.authorization_id,
        "authorization_version": value.authorization_version,
        "owner_record_id": value.owner_record_id,
        "owner_record_version": value.owner_record_version,
        "owner_record_hash": value.owner_record_hash,
        "policy_id": value.policy_id,
        "policy_version": value.policy_version,
        "scope_content_hash": value.scope_content_hash,
        "policy_definition_hash": value.policy_definition_hash,
        "approved_by": value.approved_by,
        "issued_at": value.issued_at.isoformat(),
        "valid_until": value.valid_until.isoformat(),
        "content_hash": value.content_hash,
    }


def _decode_authorization(body: dict[str, object]) -> R7SamplePolicyAuthorization:
    _keys(
        body,
        {
            "owner",
            "capability",
            "purpose",
            "authorization_id",
            "authorization_version",
            "owner_record_id",
            "owner_record_version",
            "owner_record_hash",
            "policy_id",
            "policy_version",
            "scope_content_hash",
            "policy_definition_hash",
            "approved_by",
            "issued_at",
            "valid_until",
            "content_hash",
        },
        "authorization body",
    )
    try:
        return R7SamplePolicyAuthorization(
            owner=_string(body["owner"], "owner"),
            capability=_string(body["capability"], "capability"),
            purpose=_string(body["purpose"], "purpose"),
            authorization_id=_string(body["authorization_id"], "authorization_id"),
            authorization_version=_string(body["authorization_version"], "authorization_version"),
            owner_record_id=_string(body["owner_record_id"], "owner_record_id"),
            owner_record_version=_string(body["owner_record_version"], "owner_record_version"),
            owner_record_hash=_string(body["owner_record_hash"], "owner_record_hash"),
            policy_id=_string(body["policy_id"], "policy_id"),
            policy_version=_string(body["policy_version"], "policy_version"),
            scope_content_hash=_string(body["scope_content_hash"], "scope_content_hash"),
            policy_definition_hash=_string(
                body["policy_definition_hash"], "policy_definition_hash"
            ),
            approved_by=_string(body["approved_by"], "approved_by"),
            issued_at=_datetime(body["issued_at"], "issued_at"),
            valid_until=_datetime(body["valid_until"], "valid_until"),
            content_hash=_string(body["content_hash"], "content_hash"),
        )
    except (TypeError, ValueError) as exc:
        raise R7SamplePolicyCodecError(str(exc)) from exc


def _encode_scope(value: ScenarioResearchScope) -> dict[str, object]:
    return {
        "scope_version": value.scope_version,
        "scenario_set_revision_id": (
            str(value.scenario_set_revision_id) if value.scenario_set_revision_id else None
        ),
        "scenario_revision_ids": [str(item) for item in value.scenario_revision_ids],
        "forecast_horizon_seconds": str(value.forecast_horizon.total_seconds()),
        "censoring_rule_version": value.censoring_rule_version,
        "path_horizon_periods": value.path_horizon_periods,
        "path_initial_state_revision_ids": [
            str(item) for item in value.path_initial_state_revision_ids
        ],
        "content_hash": value.content_hash,
    }


def _decode_scope(body: dict[str, object]) -> ScenarioResearchScope:
    _keys(
        body,
        {
            "scope_version",
            "scenario_set_revision_id",
            "scenario_revision_ids",
            "forecast_horizon_seconds",
            "censoring_rule_version",
            "path_horizon_periods",
            "path_initial_state_revision_ids",
            "content_hash",
        },
        "scope body",
    )
    set_id_value = body["scenario_set_revision_id"]
    if set_id_value is not None and not isinstance(set_id_value, str):
        raise R7SamplePolicyCodecError("scenario_set_revision_id must be string or null")
    try:
        return ScenarioResearchScope(
            scope_version=_string(body["scope_version"], "scope_version"),
            scenario_set_revision_id=(
                _uuid(set_id_value, "scenario_set_revision_id") if set_id_value else None
            ),
            scenario_revision_ids=_uuids(body["scenario_revision_ids"], "scenario_revision_ids"),
            forecast_horizon=_duration(
                body["forecast_horizon_seconds"], "forecast_horizon_seconds"
            ),
            censoring_rule_version=_string(
                body["censoring_rule_version"], "censoring_rule_version"
            ),
            path_horizon_periods=_integer(body["path_horizon_periods"], "path_horizon_periods"),
            path_initial_state_revision_ids=_uuids(
                body["path_initial_state_revision_ids"],
                "path_initial_state_revision_ids",
            ),
            content_hash=_string(body["content_hash"], "scope content_hash"),
        )
    except (TypeError, ValueError) as exc:
        raise R7SamplePolicyCodecError(str(exc)) from exc


def _encode_policy(value: ScenarioProbabilityResearchPolicy) -> dict[str, object]:
    return {
        "policy_version": value.policy_version,
        "activated_at": value.activated_at.isoformat(),
        "valid_until": value.valid_until.isoformat(),
        "sample_window_start": value.sample_window_start.isoformat(),
        "sample_window_end": value.sample_window_end.isoformat(),
        "forecast_horizon_seconds": str(value.forecast_horizon.total_seconds()),
        "censoring_lag_seconds": str(value.censoring_lag.total_seconds()),
        "censoring_rule_version": value.censoring_rule_version,
        "minimum_forecasts_per_revision": value.minimum_forecasts_per_revision,
        "minimum_resolved_outcomes_per_revision": (value.minimum_resolved_outcomes_per_revision),
        "minimum_outcome_coverage": str(value.minimum_outcome_coverage),
        "minimum_binary_class_observations": value.minimum_binary_class_observations,
        "minimum_multiclass_groups": value.minimum_multiclass_groups,
        "minimum_multiclass_class_observations": (value.minimum_multiclass_class_observations),
        "maximum_outcome_evidence_age_seconds": str(
            value.maximum_outcome_evidence_age.total_seconds()
        ),
        "calibration_bin_edges": [str(item) for item in value.calibration_bin_edges],
        "probability_sum_tolerance": str(value.probability_sum_tolerance),
        "minimum_historical_analogies": value.minimum_historical_analogies,
        "minimum_path_probability_observations": (value.minimum_path_probability_observations),
        "path_horizon_periods": value.path_horizon_periods,
        "require_all_path_initial_states": value.require_all_path_initial_states,
        "maximum_research_evidence_age_seconds": str(
            value.maximum_research_evidence_age.total_seconds()
        ),
        "invalidation_review_delay_seconds": str(value.invalidation_review_delay.total_seconds()),
        "approved_by": value.approved_by,
        "content_hash": value.content_hash,
    }


def _decode_policy(body: dict[str, object]) -> ScenarioProbabilityResearchPolicy:
    expected = {
        "policy_version",
        "activated_at",
        "valid_until",
        "sample_window_start",
        "sample_window_end",
        "forecast_horizon_seconds",
        "censoring_lag_seconds",
        "censoring_rule_version",
        "minimum_forecasts_per_revision",
        "minimum_resolved_outcomes_per_revision",
        "minimum_outcome_coverage",
        "minimum_binary_class_observations",
        "minimum_multiclass_groups",
        "minimum_multiclass_class_observations",
        "maximum_outcome_evidence_age_seconds",
        "calibration_bin_edges",
        "probability_sum_tolerance",
        "minimum_historical_analogies",
        "minimum_path_probability_observations",
        "path_horizon_periods",
        "require_all_path_initial_states",
        "maximum_research_evidence_age_seconds",
        "invalidation_review_delay_seconds",
        "approved_by",
        "content_hash",
    }
    _keys(body, expected, "policy body")
    try:
        return ScenarioProbabilityResearchPolicy(
            policy_version=_string(body["policy_version"], "policy_version"),
            activated_at=_datetime(body["activated_at"], "activated_at"),
            valid_until=_datetime(body["valid_until"], "valid_until"),
            sample_window_start=_datetime(body["sample_window_start"], "sample_window_start"),
            sample_window_end=_datetime(body["sample_window_end"], "sample_window_end"),
            forecast_horizon=_duration(
                body["forecast_horizon_seconds"], "forecast_horizon_seconds"
            ),
            censoring_lag=_duration(body["censoring_lag_seconds"], "censoring_lag_seconds"),
            censoring_rule_version=_string(
                body["censoring_rule_version"], "censoring_rule_version"
            ),
            minimum_forecasts_per_revision=_integer(
                body["minimum_forecasts_per_revision"],
                "minimum_forecasts_per_revision",
            ),
            minimum_resolved_outcomes_per_revision=_integer(
                body["minimum_resolved_outcomes_per_revision"],
                "minimum_resolved_outcomes_per_revision",
            ),
            minimum_outcome_coverage=_decimal(
                body["minimum_outcome_coverage"], "minimum_outcome_coverage"
            ),
            minimum_binary_class_observations=_integer(
                body["minimum_binary_class_observations"],
                "minimum_binary_class_observations",
            ),
            minimum_multiclass_groups=_integer(
                body["minimum_multiclass_groups"], "minimum_multiclass_groups"
            ),
            minimum_multiclass_class_observations=_integer(
                body["minimum_multiclass_class_observations"],
                "minimum_multiclass_class_observations",
            ),
            maximum_outcome_evidence_age=_duration(
                body["maximum_outcome_evidence_age_seconds"],
                "maximum_outcome_evidence_age_seconds",
            ),
            calibration_bin_edges=_decimals(body["calibration_bin_edges"], "calibration_bin_edges"),
            probability_sum_tolerance=_decimal(
                body["probability_sum_tolerance"], "probability_sum_tolerance"
            ),
            minimum_historical_analogies=_integer(
                body["minimum_historical_analogies"], "minimum_historical_analogies"
            ),
            minimum_path_probability_observations=_integer(
                body["minimum_path_probability_observations"],
                "minimum_path_probability_observations",
            ),
            path_horizon_periods=_integer(body["path_horizon_periods"], "path_horizon_periods"),
            require_all_path_initial_states=_boolean(
                body["require_all_path_initial_states"],
                "require_all_path_initial_states",
            ),
            maximum_research_evidence_age=_duration(
                body["maximum_research_evidence_age_seconds"],
                "maximum_research_evidence_age_seconds",
            ),
            invalidation_review_delay=_duration(
                body["invalidation_review_delay_seconds"],
                "invalidation_review_delay_seconds",
            ),
            approved_by=_string(body["approved_by"], "approved_by"),
            content_hash=_string(body["content_hash"], "policy content_hash"),
        )
    except (TypeError, ValueError) as exc:
        raise R7SamplePolicyCodecError(str(exc)) from exc


def _envelope(payload: object, schema: str) -> dict[str, object]:
    envelope = _object(payload, "envelope")
    _keys(envelope, {"schema", "body"}, "envelope")
    if envelope["schema"] != schema:
        raise R7SamplePolicyCodecError("unexpected R7 sample policy schema")
    return _object(envelope["body"], "body")


def _object(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise R7SamplePolicyCodecError(f"{field_name} must be an object")
    return cast(dict[str, object], value)


def _keys(value: dict[str, object], expected: set[str], field_name: str) -> None:
    if set(value) != expected:
        raise R7SamplePolicyCodecError(f"{field_name} keys are not canonical")


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise R7SamplePolicyCodecError(f"{field_name} must be a string")
    return value


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise R7SamplePolicyCodecError(f"{field_name} must be a boolean")
    return value


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise R7SamplePolicyCodecError(f"{field_name} must be an integer")
    return value


def _datetime(value: object, field_name: str) -> datetime:
    text = _string(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise R7SamplePolicyCodecError(f"{field_name} must be ISO datetime") from exc
    if parsed.isoformat() != text or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise R7SamplePolicyCodecError(f"{field_name} must be canonical aware datetime")
    return parsed


def _decimal(value: object, field_name: str) -> Decimal:
    text = _string(value, field_name)
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise R7SamplePolicyCodecError(f"{field_name} must be decimal text") from exc
    if not parsed.is_finite() or str(parsed) != text:
        raise R7SamplePolicyCodecError(f"{field_name} must be canonical decimal text")
    return parsed


def _duration(value: object, field_name: str) -> timedelta:
    seconds = _decimal(value, field_name)
    microseconds = seconds * Decimal(1_000_000)
    if microseconds != microseconds.to_integral_value():
        raise R7SamplePolicyCodecError(f"{field_name} exceeds timedelta microsecond precision")
    return timedelta(microseconds=int(microseconds))


def _strings(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise R7SamplePolicyCodecError(f"{field_name} must be a string array")
    return tuple(cast(list[str], value))


def _uuids(value: object, field_name: str) -> tuple[UUID, ...]:
    try:
        return tuple(_uuid(item, field_name) for item in _strings(value, field_name))
    except ValueError as exc:
        raise R7SamplePolicyCodecError(str(exc)) from exc


def _uuid(value: str, field_name: str) -> UUID:
    """Decode only the lowercase hyphenated UUID spelling emitted by the codec."""

    parsed = UUID(value)
    if str(parsed) != value:
        raise ValueError(f"{field_name} must use canonical lowercase UUID text")
    return parsed


def _decimals(value: object, field_name: str) -> tuple[Decimal, ...]:
    return tuple(_decimal(item, field_name) for item in _strings(value, field_name))


__all__ = [
    "R7SamplePolicyCodecError",
    "decode_persisted_r7_sample_policy",
    "decode_r7_sample_policy_authorization",
    "encode_persisted_r7_sample_policy",
    "encode_r7_sample_policy_authorization",
]
