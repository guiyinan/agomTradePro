"""Exact Operating Forecast and sensitivity references used by R1 artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .forecast_baseline_evidence import (
    BaselineComputationEvidence,
    ForecastPeriodHorizon,
    ForecastScenario,
    _decimal_text,
    _require_aware,
    _require_finite,
    _require_sha256,
    _require_text,
    _require_token,
    _utc_text,
)


@dataclass(frozen=True)
class SensitivityArtifactReference:
    """Exact Sector/Valuation sensitivity artifact authority."""

    owner: str
    artifact_id: str
    artifact_version: str
    artifact_content_hash: str

    def __post_init__(self) -> None:
        if self.owner not in {"sector", "valuation"}:
            raise ValueError("sensitivity artifact owner is invalid")
        _require_token(self.artifact_id, "sensitivity artifact_id")
        _require_token(self.artifact_version, "sensitivity artifact_version")
        _require_sha256(self.artifact_content_hash, "sensitivity artifact_content_hash")


@dataclass(frozen=True)
class BaselinePredictionObservation:
    """One baseline prediction with exact member, fact and vintage evidence."""

    period_end: date
    metric_code: str
    input_role: str
    value: Decimal
    unit: str
    pit_manifest_id: str
    pit_manifest_hash: str
    selected_member_id: str
    selected_member_version: str
    selected_member_content_hash: str
    source_fact_id: str
    source_fact_version: str
    source_fact_content_hash: str
    computation_evidence: BaselineComputationEvidence
    effective_at: datetime
    available_at: datetime
    vintage_id: str
    vintage_version: str
    vintage_content_hash: str

    def __post_init__(self) -> None:
        _require_token(self.metric_code, "baseline metric_code")
        _require_token(self.input_role, "baseline input_role")
        _require_finite(self.value, "baseline prediction value")
        _require_text(self.unit, "baseline prediction unit", maximum=40)
        _require_token(self.pit_manifest_id, "baseline pit_manifest_id")
        _require_sha256(self.pit_manifest_hash, "baseline pit_manifest_hash")
        for field_name, value in (
            ("selected_member_id", self.selected_member_id),
            ("selected_member_version", self.selected_member_version),
            ("source_fact_id", self.source_fact_id),
            ("source_fact_version", self.source_fact_version),
            ("vintage_id", self.vintage_id),
            ("vintage_version", self.vintage_version),
        ):
            _require_token(value, f"baseline {field_name}")
        for field_name, value in (
            ("selected_member_content_hash", self.selected_member_content_hash),
            ("source_fact_content_hash", self.source_fact_content_hash),
            ("vintage_content_hash", self.vintage_content_hash),
        ):
            _require_sha256(value, f"baseline {field_name}")
        if (
            self.value != self.computation_evidence.recompute_value()
            or self.unit != self.computation_evidence.source_unit
            or self.selected_member_id != self.computation_evidence.source_member_id
            or self.selected_member_version != self.computation_evidence.source_member_version
            or self.selected_member_content_hash
            != self.computation_evidence.source_member_content_hash
            or self.source_fact_id != self.computation_evidence.source_fact_id
            or self.source_fact_version != self.computation_evidence.source_fact_version
            or self.source_fact_content_hash != self.computation_evidence.source_fact_content_hash
            or self.vintage_id != self.computation_evidence.source_vintage_id
            or self.vintage_version != self.computation_evidence.source_vintage_version
            or self.vintage_content_hash != self.computation_evidence.source_vintage_content_hash
        ):
            raise ValueError("baseline prediction does not match computation evidence")
        _require_aware(self.effective_at, "baseline effective_at")
        _require_aware(self.available_at, "baseline available_at")
        if self.available_at < self.effective_at:
            raise ValueError("baseline source cannot be available before effective time")


@dataclass(frozen=True)
class ForecastArtifactReference:
    """Exact forecast/template/run/sensitivity identity for one period."""

    forecast_id: str
    forecast_version: int
    forecast_content_hash: str
    subject_code: str
    industry_code: str
    candidate_scenario: ForecastScenario
    horizon_quarters: int
    period_horizon: ForecastPeriodHorizon
    metric_values: tuple[tuple[str, Decimal], ...]
    metric_units: tuple[tuple[str, str], ...]
    as_of_time: datetime
    persisted_at: datetime
    target_period_end: date
    template_owner: str
    template_code: str
    template_version: int
    template_content_hash: str
    template_run_owner: str
    template_run_key: str
    template_run_version: int
    template_run_content_hash: str
    sensitivity_artifacts: tuple[SensitivityArtifactReference, ...]

    def __post_init__(self) -> None:
        for field_name, token_value in (
            ("forecast_id", self.forecast_id),
            ("subject_code", self.subject_code),
            ("industry_code", self.industry_code),
            ("template_code", self.template_code),
            ("template_run_key", self.template_run_key),
        ):
            _require_token(token_value, field_name)
        if self.template_owner != "sector" or self.template_run_owner != "sector":
            raise ValueError("forecast template and run owner must be sector")
        if not isinstance(self.candidate_scenario, ForecastScenario):
            raise ValueError("forecast candidate_scenario must be a ForecastScenario")
        if isinstance(self.horizon_quarters, bool) or self.horizon_quarters < 1:
            raise ValueError("forecast horizon_quarters must be positive")
        metric_codes = tuple(item[0] for item in self.metric_values)
        unit_codes = tuple(item[0] for item in self.metric_units)
        if (
            not metric_codes
            or metric_codes != tuple(sorted(metric_codes))
            or len(metric_codes) != len(set(metric_codes))
            or unit_codes != metric_codes
        ):
            raise ValueError("forecast metric values and units must be aligned and ordered")
        for metric_code, metric_value in self.metric_values:
            _require_token(metric_code, "forecast metric_code")
            _require_finite(metric_value, "forecast metric value")
        for metric_code, unit in self.metric_units:
            _require_token(metric_code, "forecast unit metric_code")
            _require_text(unit, "forecast metric unit", maximum=40)
        for field_name, version_value in (
            ("forecast_version", self.forecast_version),
            ("template_version", self.template_version),
            ("template_run_version", self.template_run_version),
        ):
            if isinstance(version_value, bool) or version_value < 1:
                raise ValueError(f"{field_name} must be positive")
        for field_name, content_hash in (
            ("forecast_content_hash", self.forecast_content_hash),
            ("template_content_hash", self.template_content_hash),
            ("template_run_content_hash", self.template_run_content_hash),
        ):
            _require_sha256(content_hash, field_name)
        _require_aware(self.as_of_time, "forecast as_of_time")
        _require_aware(self.persisted_at, "forecast persisted_at")
        if self.persisted_at < self.as_of_time:
            raise ValueError("forecast cannot be persisted before its as-of time")
        if self.target_period_end < self.as_of_time.date():
            raise ValueError("forecast target cannot predate forecast as-of")
        if (
            self.target_period_end != self.period_horizon.target_period_end
            or self.as_of_time != self.period_horizon.forecast_origin_at
            or self.horizon_quarters != self.period_horizon.horizon_quarters
        ):
            raise ValueError("forecast fields must match the typed period horizon")
        artifact_keys = tuple(
            (item.owner, item.artifact_id, item.artifact_version)
            for item in self.sensitivity_artifacts
        )
        if (
            not artifact_keys
            or artifact_keys != tuple(sorted(artifact_keys))
            or len(artifact_keys) != len(set(artifact_keys))
        ):
            raise ValueError("sensitivity artifact refs must be non-empty, unique and ordered")


def forecast_artifact_reference_payload(
    reference: ForecastArtifactReference,
) -> dict[str, object]:
    """Return the complete canonical forecast reference payload."""

    return {
        "identity": [
            reference.forecast_id,
            reference.forecast_version,
            reference.forecast_content_hash,
        ],
        "scope": [
            reference.subject_code,
            reference.industry_code,
            reference.candidate_scenario.value,
            reference.horizon_quarters,
        ],
        "period_horizon": [
            reference.period_horizon.target_period_end.isoformat(),
            _utc_text(reference.period_horizon.forecast_origin_at),
            reference.period_horizon.origin_period_ordinal,
            reference.period_horizon.target_period_ordinal,
            reference.period_horizon.horizon_quarters,
            reference.period_horizon.calendar_id,
            reference.period_horizon.calendar_version,
            reference.period_horizon.calendar_content_hash,
            reference.period_horizon.schedule_content_hash,
        ],
        "metric_values": [
            [metric, _decimal_text(value)] for metric, value in reference.metric_values
        ],
        "metric_units": [list(item) for item in reference.metric_units],
        "as_of_time": _utc_text(reference.as_of_time),
        "persisted_at": _utc_text(reference.persisted_at),
        "target_period_end": reference.target_period_end.isoformat(),
        "template": [
            reference.template_owner,
            reference.template_code,
            reference.template_version,
            reference.template_content_hash,
        ],
        "template_run": [
            reference.template_run_owner,
            reference.template_run_key,
            reference.template_run_version,
            reference.template_run_content_hash,
        ],
        "sensitivity_artifacts": [
            [
                item.owner,
                item.artifact_id,
                item.artifact_version,
                item.artifact_content_hash,
            ]
            for item in reference.sensitivity_artifacts
        ],
    }


__all__ = [
    "ForecastArtifactReference",
    "BaselinePredictionObservation",
    "SensitivityArtifactReference",
    "forecast_artifact_reference_payload",
]
