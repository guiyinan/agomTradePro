"""Auditable operating-forecast contracts for the R1 research capability.

The module deliberately contains no industry formula or model implementation.
Callers supply governed assumptions and projections; the domain only enforces
lineage, point-in-time, scenario-completeness and evaluation invariants.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum


class ForecastScenario(str, Enum):
    """Required operating forecast scenarios."""

    BASE = "base"
    BULL = "bull"
    BEAR = "bear"


class ForecastInputKind(str, Enum):
    """Mutually exclusive origin of a forecast input."""

    OBSERVED_FACT = "observed_fact"
    HUMAN_ASSUMPTION = "human_assumption"
    MODEL_INFERENCE = "model_inference"


def _require_text(value: str, field_name: str, *, maximum: int) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")


def _require_token(value: str, field_name: str, *, maximum: int) -> None:
    _require_text(value, field_name, maximum=maximum)
    if any(character.isspace() for character in value):
        raise ValueError(f"{field_name} cannot contain whitespace")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


@dataclass(frozen=True)
class OperatingFactEvidence:
    """Frozen snapshot of one Data Center operating PIT fact."""

    version_id: int
    dataset: str
    business_key: str
    metric_code: str
    subject_type: str
    subject_code: str
    effective_at: datetime
    available_at: datetime
    source_record_id: str
    content_hash: str
    value: Decimal
    unit: str

    def __post_init__(self) -> None:
        if isinstance(self.version_id, bool) or self.version_id <= 0:
            raise ValueError("OperatingFactEvidence.version_id must be positive")
        _require_token(self.dataset, "OperatingFactEvidence.dataset", maximum=64)
        _require_text(
            self.business_key,
            "OperatingFactEvidence.business_key",
            maximum=255,
        )
        _require_token(self.metric_code, "OperatingFactEvidence.metric_code", maximum=64)
        _require_token(self.subject_type, "OperatingFactEvidence.subject_type", maximum=40)
        _require_token(self.subject_code, "OperatingFactEvidence.subject_code", maximum=80)
        _require_aware(self.effective_at, "OperatingFactEvidence.effective_at")
        _require_aware(self.available_at, "OperatingFactEvidence.available_at")
        if self.available_at < self.effective_at:
            raise ValueError("operating fact cannot be available before it is effective")
        _require_text(
            self.source_record_id,
            "OperatingFactEvidence.source_record_id",
            maximum=255,
        )
        if len(self.content_hash) != 64 or any(
            character not in "0123456789abcdefABCDEF" for character in self.content_hash
        ):
            raise ValueError("OperatingFactEvidence.content_hash must be a sha256 digest")
        _require_finite(self.value, "OperatingFactEvidence.value")
        _require_text(self.unit, "OperatingFactEvidence.unit", maximum=40)


@dataclass(frozen=True)
class OperatingForecastAssumption:
    """One reconstructible input used by one forecast scenario."""

    scenario: ForecastScenario
    assumption_key: str
    value: Decimal
    unit: str
    input_kind: ForecastInputKind
    rationale: str
    observed_fact_version_id: int | None = None
    human_assumption_ref: str = ""
    model_version: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.scenario, ForecastScenario):
            raise ValueError("OperatingForecastAssumption.scenario is invalid")
        _require_token(
            self.assumption_key,
            "OperatingForecastAssumption.assumption_key",
            maximum=80,
        )
        _require_finite(self.value, "OperatingForecastAssumption.value")
        _require_text(self.unit, "OperatingForecastAssumption.unit", maximum=40)
        if not isinstance(self.input_kind, ForecastInputKind):
            raise ValueError("OperatingForecastAssumption.input_kind is invalid")
        _require_text(self.rationale, "OperatingForecastAssumption.rationale", maximum=500)
        self._validate_lineage()

    def _validate_lineage(self) -> None:
        fact_is_present = self.observed_fact_version_id is not None
        if fact_is_present and (
            isinstance(self.observed_fact_version_id, bool)
            or (self.observed_fact_version_id or 0) <= 0
        ):
            raise ValueError("observed_fact_version_id must be positive")
        populated = {
            ForecastInputKind.OBSERVED_FACT: fact_is_present,
            ForecastInputKind.HUMAN_ASSUMPTION: bool(self.human_assumption_ref.strip()),
            ForecastInputKind.MODEL_INFERENCE: bool(self.model_version.strip()),
        }
        if not populated[self.input_kind] or sum(populated.values()) != 1:
            raise ValueError("forecast input lineage must match exactly one input_kind")

    @property
    def lineage_ref(self) -> str:
        """Return the validated immutable lineage reference."""

        if self.input_kind is ForecastInputKind.OBSERVED_FACT:
            return f"data_center_pit_fact:{self.observed_fact_version_id}"
        if self.input_kind is ForecastInputKind.HUMAN_ASSUMPTION:
            return self.human_assumption_ref
        return self.model_version


@dataclass(frozen=True)
class ValuationSensitivityPoint:
    """One externally calculated, versioned valuation sensitivity result."""

    sensitivity_key: str
    input_value: Decimal
    input_unit: str
    output_value: Decimal
    output_unit: str
    method_version: str

    def __post_init__(self) -> None:
        _require_token(
            self.sensitivity_key,
            "ValuationSensitivityPoint.sensitivity_key",
            maximum=80,
        )
        _require_finite(self.input_value, "ValuationSensitivityPoint.input_value")
        _require_text(self.input_unit, "ValuationSensitivityPoint.input_unit", maximum=40)
        _require_finite(self.output_value, "ValuationSensitivityPoint.output_value")
        _require_text(self.output_unit, "ValuationSensitivityPoint.output_unit", maximum=40)
        _require_token(
            self.method_version,
            "ValuationSensitivityPoint.method_version",
            maximum=128,
        )


@dataclass(frozen=True)
class OperatingForecastProjection:
    """Revenue, profit, margin and sensitivity outputs for one scenario."""

    scenario: ForecastScenario
    revenue: Decimal
    net_profit: Decimal
    currency_unit: str
    sensitivities: tuple[ValuationSensitivityPoint, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.scenario, ForecastScenario):
            raise ValueError("OperatingForecastProjection.scenario is invalid")
        _require_finite(self.revenue, "OperatingForecastProjection.revenue")
        if self.revenue <= 0:
            raise ValueError("OperatingForecastProjection.revenue must be positive")
        _require_finite(self.net_profit, "OperatingForecastProjection.net_profit")
        _require_text(
            self.currency_unit,
            "OperatingForecastProjection.currency_unit",
            maximum=40,
        )
        if not self.sensitivities:
            raise ValueError("each projection requires valuation sensitivity output")
        keys = [point.sensitivity_key for point in self.sensitivities]
        if len(keys) != len(set(keys)):
            raise ValueError("valuation sensitivity keys must be unique per scenario")

    @property
    def profit_margin_percent(self) -> Decimal:
        """Return the exact projected net-profit margin in percent."""

        return self.net_profit / self.revenue * Decimal("100")


@dataclass(frozen=True)
class OperatingForecastVersion:
    """One immutable, research-only version of an operating forecast."""

    forecast_id: str
    forecast_key: str
    forecast_version: int
    subject_code: str
    industry_code: str
    as_of_time: datetime
    target_period_end: date
    horizon_quarters: int
    methodology_ref: str
    created_by_ref: str
    facts: tuple[OperatingFactEvidence, ...]
    assumptions: tuple[OperatingForecastAssumption, ...]
    projections: tuple[OperatingForecastProjection, ...]
    valuation_consumable: bool = False
    promotion_decision_id: str = ""

    def __post_init__(self) -> None:
        _require_token(self.forecast_id, "OperatingForecastVersion.forecast_id", maximum=64)
        _require_token(self.forecast_key, "OperatingForecastVersion.forecast_key", maximum=128)
        if isinstance(self.forecast_version, bool) or self.forecast_version <= 0:
            raise ValueError("forecast_version must be positive")
        _require_token(self.subject_code, "OperatingForecastVersion.subject_code", maximum=80)
        _require_token(self.industry_code, "OperatingForecastVersion.industry_code", maximum=80)
        _require_aware(self.as_of_time, "OperatingForecastVersion.as_of_time")
        if self.target_period_end < self.as_of_time.date():
            raise ValueError("target_period_end cannot precede as_of_time")
        if isinstance(self.horizon_quarters, bool) or self.horizon_quarters <= 0:
            raise ValueError("horizon_quarters must be positive")
        _require_text(
            self.methodology_ref,
            "OperatingForecastVersion.methodology_ref",
            maximum=255,
        )
        _require_token(
            self.created_by_ref,
            "OperatingForecastVersion.created_by_ref",
            maximum=128,
        )
        if not isinstance(self.valuation_consumable, bool):
            raise ValueError("valuation_consumable must be a boolean")
        if self.valuation_consumable and not self.promotion_decision_id.strip():
            raise ValueError("valuation consumption requires a promotion decision")
        self._validate_facts_and_scenarios()

    def _validate_facts_and_scenarios(self) -> None:
        if not self.facts:
            raise ValueError("an operating forecast requires PIT operating facts")
        fact_ids = [fact.version_id for fact in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("operating fact references must be unique")
        if any(fact.available_at > self.as_of_time for fact in self.facts):
            raise ValueError("operating facts must be knowable at forecast as_of_time")

        required = set(ForecastScenario)
        projection_scenarios = [projection.scenario for projection in self.projections]
        if set(projection_scenarios) != required or len(projection_scenarios) != len(required):
            raise ValueError("forecast projections must contain exactly base, bull and bear")

        assumption_keys = [
            (assumption.scenario, assumption.assumption_key) for assumption in self.assumptions
        ]
        if len(assumption_keys) != len(set(assumption_keys)):
            raise ValueError("assumption keys must be unique within each scenario")
        for scenario in required:
            scenario_assumptions = [
                assumption for assumption in self.assumptions if assumption.scenario is scenario
            ]
            if not scenario_assumptions:
                raise ValueError(f"{scenario.value} requires reconstructible assumptions")
            observed_ids = {
                assumption.observed_fact_version_id
                for assumption in scenario_assumptions
                if assumption.input_kind is ForecastInputKind.OBSERVED_FACT
            }
            if not observed_ids:
                raise ValueError(f"{scenario.value} requires observed PIT fact grounding")
            if not observed_ids.issubset(set(fact_ids)):
                raise ValueError("observed assumptions must reference captured operating facts")

    @property
    def contains_model_inference(self) -> bool:
        """Return whether any assumption came from a model."""

        return any(
            assumption.input_kind is ForecastInputKind.MODEL_INFERENCE
            for assumption in self.assumptions
        )

    @property
    def usage_scope(self) -> str:
        """Publish the stable internal consumption scope."""

        return "valuation_approved" if self.valuation_consumable else "research_only"

    @property
    def content_hash(self) -> str:
        """Seal every input, output and lineage field in a canonical digest."""

        payload = {
            "forecast_id": self.forecast_id,
            "forecast_key": self.forecast_key,
            "forecast_version": self.forecast_version,
            "subject_code": self.subject_code,
            "industry_code": self.industry_code,
            "as_of_time": self.as_of_time.astimezone(UTC).isoformat(),
            "target_period_end": self.target_period_end.isoformat(),
            "horizon_quarters": self.horizon_quarters,
            "methodology_ref": self.methodology_ref,
            "created_by_ref": self.created_by_ref,
            "valuation_consumable": self.valuation_consumable,
            "promotion_decision_id": self.promotion_decision_id,
            "facts": [
                {
                    "version_id": fact.version_id,
                    "dataset": fact.dataset,
                    "business_key": fact.business_key,
                    "metric_code": fact.metric_code,
                    "subject_type": fact.subject_type,
                    "subject_code": fact.subject_code,
                    "effective_at": fact.effective_at.astimezone(UTC).isoformat(),
                    "available_at": fact.available_at.astimezone(UTC).isoformat(),
                    "source_record_id": fact.source_record_id,
                    "content_hash": fact.content_hash,
                    "value": _decimal_text(fact.value),
                    "unit": fact.unit,
                }
                for fact in sorted(self.facts, key=lambda item: item.version_id)
            ],
            "assumptions": [
                {
                    "scenario": item.scenario.value,
                    "assumption_key": item.assumption_key,
                    "value": _decimal_text(item.value),
                    "unit": item.unit,
                    "input_kind": item.input_kind.value,
                    "rationale": item.rationale,
                    "lineage_ref": item.lineage_ref,
                }
                for item in sorted(
                    self.assumptions,
                    key=lambda item: (item.scenario.value, item.assumption_key),
                )
            ],
            "projections": [
                {
                    "scenario": item.scenario.value,
                    "revenue": _decimal_text(item.revenue),
                    "net_profit": _decimal_text(item.net_profit),
                    "profit_margin_percent": _decimal_text(item.profit_margin_percent),
                    "currency_unit": item.currency_unit,
                    "sensitivities": [
                        {
                            "sensitivity_key": point.sensitivity_key,
                            "input_value": _decimal_text(point.input_value),
                            "input_unit": point.input_unit,
                            "output_value": _decimal_text(point.output_value),
                            "output_unit": point.output_unit,
                            "method_version": point.method_version,
                        }
                        for point in sorted(
                            item.sensitivities,
                            key=lambda point: point.sensitivity_key,
                        )
                    ],
                }
                for item in sorted(self.projections, key=lambda item: item.scenario.value)
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _absolute_percentage_error(
    forecast_value: Decimal,
    actual_value: Decimal,
) -> Decimal | None:
    if actual_value == 0:
        return None
    return abs(forecast_value - actual_value) / abs(actual_value) * Decimal("100")


@dataclass(frozen=True)
class OperatingForecastEvaluation:
    """Append-only quarterly actual-versus-forecast comparison."""

    forecast_id: str
    scenario: ForecastScenario
    actual_period_end: date
    recorded_at: datetime
    actual_facts: tuple[OperatingFactEvidence, ...]
    forecast_revenue: Decimal
    forecast_net_profit: Decimal
    actual_revenue: Decimal
    actual_net_profit: Decimal
    currency_unit: str

    def __post_init__(self) -> None:
        _require_token(self.forecast_id, "OperatingForecastEvaluation.forecast_id", maximum=64)
        if not isinstance(self.scenario, ForecastScenario):
            raise ValueError("OperatingForecastEvaluation.scenario is invalid")
        _require_aware(self.recorded_at, "OperatingForecastEvaluation.recorded_at")
        if not self.actual_facts:
            raise ValueError("quarterly actual comparison requires PIT fact evidence")
        fact_ids = [fact.version_id for fact in self.actual_facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("actual fact references must be unique")
        if any(fact.available_at > self.recorded_at for fact in self.actual_facts):
            raise ValueError("actual facts must be knowable when the comparison is recorded")
        for field_name, value in (
            ("forecast_revenue", self.forecast_revenue),
            ("forecast_net_profit", self.forecast_net_profit),
            ("actual_revenue", self.actual_revenue),
            ("actual_net_profit", self.actual_net_profit),
        ):
            _require_finite(value, f"OperatingForecastEvaluation.{field_name}")
        if self.forecast_revenue <= 0 or self.actual_revenue <= 0:
            raise ValueError("forecast and actual revenue must be positive")
        _require_text(
            self.currency_unit,
            "OperatingForecastEvaluation.currency_unit",
            maximum=40,
        )

    @property
    def forecast_profit_margin_percent(self) -> Decimal:
        """Return projected net-profit margin."""

        return self.forecast_net_profit / self.forecast_revenue * Decimal("100")

    @property
    def actual_profit_margin_percent(self) -> Decimal:
        """Return realized net-profit margin."""

        return self.actual_net_profit / self.actual_revenue * Decimal("100")

    @property
    def revenue_error(self) -> Decimal:
        """Return signed revenue error as forecast minus actual."""

        return self.forecast_revenue - self.actual_revenue

    @property
    def revenue_absolute_error(self) -> Decimal:
        """Return revenue absolute error (single-observation MAE)."""

        return abs(self.revenue_error)

    @property
    def revenue_absolute_percentage_error(self) -> Decimal | None:
        """Return revenue APE in percent, or ``None`` for zero actual."""

        return _absolute_percentage_error(self.forecast_revenue, self.actual_revenue)

    @property
    def net_profit_error(self) -> Decimal:
        """Return signed net-profit error as forecast minus actual."""

        return self.forecast_net_profit - self.actual_net_profit

    @property
    def net_profit_absolute_error(self) -> Decimal:
        """Return net-profit absolute error (single-observation MAE)."""

        return abs(self.net_profit_error)

    @property
    def net_profit_absolute_percentage_error(self) -> Decimal | None:
        """Return net-profit APE in percent, or ``None`` for zero actual."""

        return _absolute_percentage_error(self.forecast_net_profit, self.actual_net_profit)

    @property
    def profit_margin_error(self) -> Decimal:
        """Return signed margin error in percentage points."""

        return self.forecast_profit_margin_percent - self.actual_profit_margin_percent

    @property
    def profit_margin_absolute_error(self) -> Decimal:
        """Return absolute margin error in percentage points."""

        return abs(self.profit_margin_error)

    @property
    def content_hash(self) -> str:
        """Seal the comparison and its exact actual evidence references."""

        payload = {
            "forecast_id": self.forecast_id,
            "scenario": self.scenario.value,
            "actual_period_end": self.actual_period_end.isoformat(),
            "recorded_at": self.recorded_at.astimezone(UTC).isoformat(),
            "actual_fact_versions": [
                {"version_id": fact.version_id, "content_hash": fact.content_hash}
                for fact in sorted(self.actual_facts, key=lambda item: item.version_id)
            ],
            "forecast_revenue": _decimal_text(self.forecast_revenue),
            "forecast_net_profit": _decimal_text(self.forecast_net_profit),
            "actual_revenue": _decimal_text(self.actual_revenue),
            "actual_net_profit": _decimal_text(self.actual_net_profit),
            "currency_unit": self.currency_unit,
            "revenue_error": _decimal_text(self.revenue_error),
            "net_profit_error": _decimal_text(self.net_profit_error),
            "profit_margin_error": _decimal_text(self.profit_margin_error),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def build_quarterly_evaluations(
    forecast: OperatingForecastVersion,
    *,
    actual_period_end: date,
    recorded_at: datetime,
    actual_facts: tuple[OperatingFactEvidence, ...],
    actual_revenue: Decimal,
    actual_net_profit: Decimal,
    currency_unit: str,
) -> tuple[OperatingForecastEvaluation, ...]:
    """Build one immutable comparison for each required scenario."""

    if actual_period_end != forecast.target_period_end:
        raise ValueError("actual_period_end must match the forecast target period")
    return tuple(
        OperatingForecastEvaluation(
            forecast_id=forecast.forecast_id,
            scenario=projection.scenario,
            actual_period_end=actual_period_end,
            recorded_at=recorded_at,
            actual_facts=actual_facts,
            forecast_revenue=projection.revenue,
            forecast_net_profit=projection.net_profit,
            actual_revenue=actual_revenue,
            actual_net_profit=actual_net_profit,
            currency_unit=currency_unit,
        )
        for projection in sorted(forecast.projections, key=lambda item: item.scenario.value)
    )


__all__ = [
    "ForecastInputKind",
    "ForecastScenario",
    "OperatingFactEvidence",
    "OperatingForecastAssumption",
    "OperatingForecastEvaluation",
    "OperatingForecastProjection",
    "OperatingForecastVersion",
    "ValuationSensitivityPoint",
    "build_quarterly_evaluations",
]
