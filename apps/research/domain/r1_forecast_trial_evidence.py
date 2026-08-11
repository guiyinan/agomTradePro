"""Research-owned preregistration evidence for the R1 forecast trial."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime

from apps.equity.domain.forecast_baseline import ForecastEvaluationPolicy


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_hash(value: object, field_name: str) -> None:
    if type(value) is not str or len(value) != 64:
        raise ValueError(f"{field_name} must be a sha256 hex digest")
    try:
        if value != value.lower():
            raise ValueError
        int(value, 16)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a sha256 hex digest") from error


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class R1ForecastTrialDefinition:
    """Canonical versioned Research definition, never supplied by a command."""

    definition_id: str
    definition_version: str
    owner: str
    capability: str
    purpose: str
    status: str
    baseline_spec_id: str
    baseline_spec_version: str
    baseline_spec_content_hash: str
    baseline_artifact_id: str
    baseline_artifact_version: str
    baseline_artifact_content_hash: str
    split_spec_hash: str
    parameter_hash: str
    calendar_id: str
    calendar_version: str
    calendar_schedule_hash: str
    expected_period_ends: tuple[date, ...]
    metric_codes: tuple[str, ...]
    evaluation_keys: tuple[tuple[date, str], ...]
    evaluation_policy: ForecastEvaluationPolicy
    activated_at: datetime
    valid_until: datetime
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        definition_id: str,
        definition_version: str,
        baseline_spec_id: str,
        baseline_spec_version: str,
        baseline_spec_content_hash: str,
        baseline_artifact_id: str,
        baseline_artifact_version: str,
        baseline_artifact_content_hash: str,
        split_spec_hash: str,
        parameter_hash: str,
        calendar_id: str,
        calendar_version: str,
        calendar_schedule_hash: str,
        expected_period_ends: tuple[date, ...],
        metric_codes: tuple[str, ...],
        evaluation_policy: ForecastEvaluationPolicy,
        activated_at: datetime,
        valid_until: datetime,
    ) -> R1ForecastTrialDefinition:
        """Seal one owner definition with the full period-metric cross-product."""

        evaluation_keys = tuple(
            (period_end, metric_code)
            for period_end in expected_period_ends
            for metric_code in metric_codes
        )
        values: dict[str, object] = {
            "definition_id": definition_id,
            "definition_version": definition_version,
            "owner": "research",
            "capability": "r1",
            "purpose": "valuation",
            "status": "running",
            "baseline_spec_id": baseline_spec_id,
            "baseline_spec_version": baseline_spec_version,
            "baseline_spec_content_hash": baseline_spec_content_hash,
            "baseline_artifact_id": baseline_artifact_id,
            "baseline_artifact_version": baseline_artifact_version,
            "baseline_artifact_content_hash": baseline_artifact_content_hash,
            "split_spec_hash": split_spec_hash,
            "parameter_hash": parameter_hash,
            "calendar_id": calendar_id,
            "calendar_version": calendar_version,
            "calendar_schedule_hash": calendar_schedule_hash,
            "expected_period_ends": expected_period_ends,
            "metric_codes": metric_codes,
            "evaluation_keys": evaluation_keys,
            "evaluation_policy": evaluation_policy,
            "activated_at": activated_at,
            "valid_until": valid_until,
        }
        content_hash = _canonical_hash(_definition_payload(values))
        return cls(
            definition_id=definition_id,
            definition_version=definition_version,
            owner="research",
            capability="r1",
            purpose="valuation",
            status="running",
            baseline_spec_id=baseline_spec_id,
            baseline_spec_version=baseline_spec_version,
            baseline_spec_content_hash=baseline_spec_content_hash,
            baseline_artifact_id=baseline_artifact_id,
            baseline_artifact_version=baseline_artifact_version,
            baseline_artifact_content_hash=baseline_artifact_content_hash,
            split_spec_hash=split_spec_hash,
            parameter_hash=parameter_hash,
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            calendar_schedule_hash=calendar_schedule_hash,
            expected_period_ends=expected_period_ends,
            metric_codes=metric_codes,
            evaluation_keys=evaluation_keys,
            evaluation_policy=evaluation_policy,
            activated_at=activated_at,
            valid_until=valid_until,
            content_hash=content_hash,
        )

    def __post_init__(self) -> None:
        for field_name in (
            "definition_id",
            "definition_version",
            "baseline_spec_id",
            "baseline_spec_version",
            "baseline_artifact_id",
            "baseline_artifact_version",
            "calendar_id",
            "calendar_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        for field_name in (
            "baseline_spec_content_hash",
            "baseline_artifact_content_hash",
            "split_spec_hash",
            "parameter_hash",
            "calendar_schedule_hash",
            "content_hash",
        ):
            _require_hash(getattr(self, field_name), field_name)
        if (self.owner, self.capability, self.purpose, self.status) != (
            "research",
            "r1",
            "valuation",
            "running",
        ):
            raise ValueError("R1 trial definition authority is unsupported")
        if type(self.expected_period_ends) is not tuple or not self.expected_period_ends:
            raise ValueError("expected_period_ends must be a non-empty tuple")
        if any(type(item) is not date for item in self.expected_period_ends):
            raise ValueError("expected_period_ends must contain exact dates")
        if self.expected_period_ends != tuple(sorted(set(self.expected_period_ends))):
            raise ValueError("expected_period_ends must be ordered and unique")
        if type(self.metric_codes) is not tuple or not self.metric_codes:
            raise ValueError("metric_codes must be a non-empty tuple")
        for metric_code in self.metric_codes:
            _require_token(metric_code, "metric_code")
        if self.metric_codes != tuple(sorted(set(self.metric_codes))):
            raise ValueError("metric_codes must be ordered and unique")
        expected_keys = tuple(
            (period_end, metric_code)
            for period_end in self.expected_period_ends
            for metric_code in self.metric_codes
        )
        if type(self.evaluation_keys) is not tuple or self.evaluation_keys != expected_keys:
            raise ValueError("evaluation_keys must be the exact period-metric cross-product")
        if type(self.evaluation_policy) is not ForecastEvaluationPolicy:
            raise TypeError("evaluation_policy must be exact ForecastEvaluationPolicy")
        ForecastEvaluationPolicy.__post_init__(self.evaluation_policy)
        _require_aware(self.activated_at, "activated_at")
        _require_aware(self.valid_until, "valid_until")
        if self.activated_at >= self.valid_until:
            raise ValueError("R1 trial definition time window is invalid")
        if (
            self.research_only is not True
            or self.must_not_use_for_decision is not True
            or self.must_not_execute is not True
        ):
            raise ValueError("R1 trial definition safety flags must remain true")
        expected_hash = _canonical_hash(_definition_payload(self.__dict__))
        if self.content_hash != expected_hash:
            raise ValueError("R1 trial definition content hash mismatch")


@dataclass(frozen=True)
class PersistedR1ForecastTrialEvidence:
    """Immutable preregistration receipt projected to Equity at exact PIT."""

    evidence_id: str
    evidence_version: str
    definition: R1ForecastTrialDefinition
    baseline_spec_approved_at: datetime
    forecast_origin_at: datetime
    recorded_at: datetime
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        evidence_id: str,
        evidence_version: str,
        definition: R1ForecastTrialDefinition,
        baseline_spec_approved_at: datetime,
        forecast_origin_at: datetime,
        recorded_at: datetime,
    ) -> PersistedR1ForecastTrialEvidence:
        """Seal one server-recorded receipt from a validated owner definition."""

        values: dict[str, object] = {
            "evidence_id": evidence_id,
            "evidence_version": evidence_version,
            "definition": definition,
            "baseline_spec_approved_at": baseline_spec_approved_at,
            "forecast_origin_at": forecast_origin_at,
            "recorded_at": recorded_at,
        }
        content_hash = _canonical_hash(_evidence_payload(values))
        return cls(
            evidence_id=evidence_id,
            evidence_version=evidence_version,
            definition=definition,
            baseline_spec_approved_at=baseline_spec_approved_at,
            forecast_origin_at=forecast_origin_at,
            recorded_at=recorded_at,
            content_hash=content_hash,
        )

    def __post_init__(self) -> None:
        _require_token(self.evidence_id, "evidence_id")
        _require_token(self.evidence_version, "evidence_version")
        _require_hash(self.content_hash, "content_hash")
        if type(self.definition) is not R1ForecastTrialDefinition:
            raise TypeError("definition must be exact R1ForecastTrialDefinition")
        R1ForecastTrialDefinition.__post_init__(self.definition)
        for field_name in (
            "baseline_spec_approved_at",
            "forecast_origin_at",
            "recorded_at",
        ):
            _require_aware(getattr(self, field_name), field_name)
        if not (
            self.baseline_spec_approved_at
            <= self.definition.activated_at
            <= self.recorded_at
            <= self.forecast_origin_at
            < self.definition.valid_until
        ):
            raise ValueError("R1 trial preregistration clocks are invalid")
        if (
            self.research_only is not True
            or self.must_not_use_for_decision is not True
            or self.must_not_execute is not True
        ):
            raise ValueError("R1 trial evidence safety flags must remain true")
        expected_hash = _canonical_hash(_evidence_payload(self.__dict__))
        if self.content_hash != expected_hash:
            raise ValueError("R1 trial evidence content hash mismatch")


def _definition_payload(values: object) -> dict[str, object]:
    source = values if isinstance(values, dict) else vars(values)
    policy = source["evaluation_policy"]
    if type(policy) is not ForecastEvaluationPolicy:
        raise TypeError("evaluation_policy must be exact ForecastEvaluationPolicy")
    return {
        "schema": "research-r1-forecast-trial-definition.v1",
        "identity": [source["definition_id"], source["definition_version"]],
        "authority": [source["owner"], source["capability"], source["purpose"], source["status"]],
        "baseline_spec": [
            source["baseline_spec_id"],
            source["baseline_spec_version"],
            source["baseline_spec_content_hash"],
        ],
        "baseline_artifact": [
            source["baseline_artifact_id"],
            source["baseline_artifact_version"],
            source["baseline_artifact_content_hash"],
        ],
        "split_spec_hash": source["split_spec_hash"],
        "parameter_hash": source["parameter_hash"],
        "calendar": [
            source["calendar_id"],
            source["calendar_version"],
            source["calendar_schedule_hash"],
        ],
        "expected_period_ends": [item.isoformat() for item in source["expected_period_ends"]],
        "metric_codes": list(source["metric_codes"]),
        "evaluation_keys": [
            [period_end.isoformat(), metric_code]
            for period_end, metric_code in source["evaluation_keys"]
        ],
        "evaluation_policy_content_hash": policy.policy_content_hash,
        "activated_at": _utc_text(source["activated_at"]),
        "valid_until": _utc_text(source["valid_until"]),
        "safety": [True, True, True],
    }


def _evidence_payload(values: object) -> dict[str, object]:
    source = values if isinstance(values, dict) else vars(values)
    definition = source["definition"]
    if type(definition) is not R1ForecastTrialDefinition:
        raise TypeError("definition must be exact R1ForecastTrialDefinition")
    return {
        "schema": "research-r1-forecast-trial-evidence.v1",
        "identity": [source["evidence_id"], source["evidence_version"]],
        "definition": [
            definition.definition_id,
            definition.definition_version,
            definition.content_hash,
        ],
        "baseline_spec_approved_at": _utc_text(source["baseline_spec_approved_at"]),
        "forecast_origin_at": _utc_text(source["forecast_origin_at"]),
        "activated_at": _utc_text(definition.activated_at),
        "recorded_at": _utc_text(source["recorded_at"]),
        "valid_until": _utc_text(definition.valid_until),
        "safety": [True, True, True],
    }


__all__ = ["PersistedR1ForecastTrialEvidence", "R1ForecastTrialDefinition"]
