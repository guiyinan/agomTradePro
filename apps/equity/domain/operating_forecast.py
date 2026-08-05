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


class OperatingMetricRole(str, Enum):
    """Canonical output metrics used by quarterly actual reconciliation."""

    REVENUE = "revenue"
    NET_PROFIT = "net_profit"
    PROFIT_MARGIN_PERCENT = "profit_margin_percent"


class OperatingForecastStage(str, Enum):
    """Required financial stages preserved from one industry-template run."""

    REVENUE = "revenue"
    COST = "cost"
    GROSS_PROFIT = "gross_profit"
    EXPENSE = "expense"
    NET_PROFIT = "net_profit"
    CASH_FLOW = "cash_flow"


class OperatingForecastSourceKind(str, Enum):
    """Auditable origin of an Equity operating-forecast record."""

    LEGACY_MANUAL = "legacy_manual"
    INDUSTRY_TEMPLATE = "industry_template"


class OperatingForecastSourceLineageStatus(str, Enum):
    """Migration-safe evidence lineage state for operating-forecast rows."""

    LEGACY_UNBOUND = "legacy_unbound"
    LEGACY_UNVERIFIED = "legacy_unverified"
    TEMPLATE_BOUND = "template_bound"


class OperatingForecastLegacyHashRecipe(str, Enum):
    """Exact historical canonical payload used by a schema-v1 row."""

    V1_0010_UNTYPED = "v1_0010_untyped"
    V1_0011_TYPED = "v1_0011_typed"
    UNVERIFIED = "unverified"
    NOT_APPLICABLE = "not_applicable"


class OperatingForecastLegacyHashStatus(str, Enum):
    """Whether a preserved schema-v1 digest matched its historical recipe."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    NOT_APPLICABLE = "not_applicable"


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
    observed_metric_code: str = ""
    observed_fact_content_hash: str = ""
    observed_subject_type: str = ""
    observed_subject_code: str = ""

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
        if self.input_kind is ForecastInputKind.OBSERVED_FACT:
            _require_token(
                self.observed_metric_code,
                "OperatingForecastAssumption.observed_metric_code",
                maximum=64,
            )
            if len(self.observed_fact_content_hash) != 64 or any(
                character not in "0123456789abcdefABCDEF"
                for character in self.observed_fact_content_hash
            ):
                raise ValueError("observed_fact_content_hash must be a sha256 digest")
            _require_token(
                self.observed_subject_type,
                "OperatingForecastAssumption.observed_subject_type",
                maximum=40,
            )
            _require_token(
                self.observed_subject_code,
                "OperatingForecastAssumption.observed_subject_code",
                maximum=80,
            )
        elif any(
            (
                self.observed_metric_code,
                self.observed_fact_content_hash,
                self.observed_subject_type,
                self.observed_subject_code,
            )
        ):
            raise ValueError("only observed forecast input may carry PIT fact identity")

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
    source_artifact_ref: str
    source_artifact_hash: str

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
        _require_text(
            self.source_artifact_ref,
            "ValuationSensitivityPoint.source_artifact_ref",
            maximum=255,
        )
        if len(self.source_artifact_hash) != 64 or any(
            character not in "0123456789abcdefABCDEF" for character in self.source_artifact_hash
        ):
            raise ValueError("source_artifact_hash must be a sha256 digest")


@dataclass(frozen=True)
class OperatingForecastStageValue:
    """One immutable six-stage output copied from a governed Sector run."""

    stage: OperatingForecastStage
    node_key: str
    value: Decimal
    unit: str

    def __post_init__(self) -> None:
        if not isinstance(self.stage, OperatingForecastStage):
            raise ValueError("OperatingForecastStageValue.stage is invalid")
        _require_token(
            self.node_key,
            "OperatingForecastStageValue.node_key",
            maximum=80,
        )
        _require_finite(self.value, "OperatingForecastStageValue.value")
        _require_text(self.unit, "OperatingForecastStageValue.unit", maximum=40)


@dataclass(frozen=True)
class OperatingForecastProjection:
    """Revenue, profit, margin and sensitivity outputs for one scenario."""

    scenario: ForecastScenario
    revenue: Decimal
    net_profit: Decimal
    cash_flow: Decimal
    currency_unit: str
    stage_values: tuple[OperatingForecastStageValue, ...]
    sensitivities: tuple[ValuationSensitivityPoint, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.scenario, ForecastScenario):
            raise ValueError("OperatingForecastProjection.scenario is invalid")
        _require_finite(self.revenue, "OperatingForecastProjection.revenue")
        if self.revenue <= 0:
            raise ValueError("OperatingForecastProjection.revenue must be positive")
        _require_finite(self.net_profit, "OperatingForecastProjection.net_profit")
        _require_finite(self.cash_flow, "OperatingForecastProjection.cash_flow")
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
        stages = [point.stage for point in self.stage_values]
        if set(stages) != set(OperatingForecastStage) or len(stages) != len(OperatingForecastStage):
            raise ValueError("projection must preserve every financial stage exactly once")
        by_stage = {point.stage: point for point in self.stage_values}
        for stage, expected_value in (
            (OperatingForecastStage.REVENUE, self.revenue),
            (OperatingForecastStage.NET_PROFIT, self.net_profit),
            (OperatingForecastStage.CASH_FLOW, self.cash_flow),
        ):
            stage_value = by_stage[stage]
            if stage_value.value != expected_value or stage_value.unit != self.currency_unit:
                raise ValueError(
                    "projection headline values must match sealed financial stage values"
                )

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
    source_kind: OperatingForecastSourceKind
    evidence_schema_version: int
    source_lineage_status: OperatingForecastSourceLineageStatus
    template_code: str
    template_version: int
    template_content_hash: str
    template_run_key: str
    template_run_version: int
    template_run_content_hash: str
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
        if self.source_kind is not OperatingForecastSourceKind.INDUSTRY_TEMPLATE:
            raise ValueError("new operating forecasts require an industry-template source")
        if self.evidence_schema_version != 2:
            raise ValueError("industry-template forecasts require evidence schema v2")
        if self.source_lineage_status is not OperatingForecastSourceLineageStatus.TEMPLATE_BOUND:
            raise ValueError("industry-template forecasts require template-bound lineage")
        _require_token(
            self.template_code,
            "OperatingForecastVersion.template_code",
            maximum=80,
        )
        _require_token(
            self.template_run_key,
            "OperatingForecastVersion.template_run_key",
            maximum=128,
        )
        for version_value, field_name in (
            (self.template_version, "template_version"),
            (self.template_run_version, "template_run_version"),
        ):
            if isinstance(version_value, bool) or version_value <= 0:
                raise ValueError(f"OperatingForecastVersion.{field_name} must be positive")
        for hash_value, field_name in (
            (self.template_content_hash, "template_content_hash"),
            (self.template_run_content_hash, "template_run_content_hash"),
        ):
            if len(hash_value) != 64 or any(
                character not in "0123456789abcdefABCDEF" for character in hash_value
            ):
                raise ValueError(f"OperatingForecastVersion.{field_name} must be a sha256 digest")
        if not isinstance(self.valuation_consumable, bool):
            raise ValueError("valuation_consumable must be a boolean")
        if self.valuation_consumable or self.promotion_decision_id.strip():
            raise ValueError(
                "template-bound schema-v2 forecasts remain research-only until exact "
                "promotion-artifact binding is implemented"
            )
        self._validate_facts_and_scenarios()

    def _validate_facts_and_scenarios(self) -> None:
        if not self.facts:
            raise ValueError("an operating forecast requires PIT operating facts")
        fact_ids = [fact.version_id for fact in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("operating fact references must be unique")
        if any(fact.available_at > self.as_of_time for fact in self.facts):
            raise ValueError("operating facts must be knowable at forecast as_of_time")
        if any(
            fact.subject_type != "company" or fact.subject_code != self.subject_code
            for fact in self.facts
        ):
            raise ValueError("operating facts must belong to the forecast company subject")
        facts_by_id = {fact.version_id: fact for fact in self.facts}

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
            for assumption in scenario_assumptions:
                if assumption.input_kind is not ForecastInputKind.OBSERVED_FACT:
                    continue
                fact = facts_by_id[assumption.observed_fact_version_id or 0]
                if (
                    fact.metric_code != assumption.observed_metric_code
                    or fact.content_hash.lower() != assumption.observed_fact_content_hash.lower()
                    or fact.subject_type != assumption.observed_subject_type
                    or fact.subject_code != assumption.observed_subject_code
                    or fact.value != assumption.value
                    or fact.unit != assumption.unit
                ):
                    raise ValueError(
                        "observed assumption must exactly match PIT subject, metric, value and unit"
                    )

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
            "source_kind": self.source_kind.value,
            "evidence_schema_version": self.evidence_schema_version,
            "source_lineage_status": self.source_lineage_status.value,
            "template_code": self.template_code,
            "template_version": self.template_version,
            "template_content_hash": self.template_content_hash.lower(),
            "template_run_key": self.template_run_key,
            "template_run_version": self.template_run_version,
            "template_run_content_hash": self.template_run_content_hash.lower(),
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
                    "observed_metric_code": item.observed_metric_code,
                    "observed_fact_content_hash": item.observed_fact_content_hash.lower(),
                    "observed_subject_type": item.observed_subject_type,
                    "observed_subject_code": item.observed_subject_code,
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
                    "cash_flow": _decimal_text(item.cash_flow),
                    "profit_margin_percent": _decimal_text(item.profit_margin_percent),
                    "currency_unit": item.currency_unit,
                    "stage_values": [
                        {
                            "stage": stage.stage.value,
                            "node_key": stage.node_key,
                            "value": _decimal_text(stage.value),
                            "unit": stage.unit,
                        }
                        for stage in sorted(
                            item.stage_values,
                            key=lambda stage: stage.stage.value,
                        )
                    ],
                    "sensitivities": [
                        {
                            "sensitivity_key": point.sensitivity_key,
                            "input_value": _decimal_text(point.input_value),
                            "input_unit": point.input_unit,
                            "output_value": _decimal_text(point.output_value),
                            "output_unit": point.output_unit,
                            "method_version": point.method_version,
                            "source_artifact_ref": point.source_artifact_ref,
                            "source_artifact_hash": point.source_artifact_hash.lower(),
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


@dataclass(frozen=True)
class LegacyOperatingForecastAssumption:
    """Read-only pre-bridge assumption retaining its original limited identity."""

    scenario: ForecastScenario
    assumption_key: str
    value: Decimal
    unit: str
    input_kind: ForecastInputKind
    rationale: str
    observed_fact_version_id: int | None = None
    human_assumption_ref: str = ""
    model_version: str = ""
    observed_metric_role: str | None = None

    @property
    def lineage_ref(self) -> str:
        """Return the historical lineage reference used by the v1 hash schema."""

        if self.input_kind is ForecastInputKind.OBSERVED_FACT:
            return f"data_center_pit_fact:{self.observed_fact_version_id}"
        if self.input_kind is ForecastInputKind.HUMAN_ASSUMPTION:
            return self.human_assumption_ref
        return self.model_version


@dataclass(frozen=True)
class LegacyValuationSensitivityPoint:
    """Read-only pre-bridge sensitivity without fabricated owner identity."""

    sensitivity_key: str
    input_value: Decimal
    input_unit: str
    output_value: Decimal
    output_unit: str
    method_version: str


@dataclass(frozen=True)
class LegacyOperatingForecastProjection:
    """Read-only projection preserved for rows created before template binding."""

    scenario: ForecastScenario
    revenue: Decimal
    net_profit: Decimal
    currency_unit: str
    sensitivities: tuple[LegacyValuationSensitivityPoint, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.scenario, ForecastScenario):
            raise ValueError("LegacyOperatingForecastProjection.scenario is invalid")
        _require_finite(self.revenue, "LegacyOperatingForecastProjection.revenue")
        if self.revenue <= 0:
            raise ValueError("LegacyOperatingForecastProjection.revenue must be positive")
        _require_finite(self.net_profit, "LegacyOperatingForecastProjection.net_profit")
        _require_text(
            self.currency_unit,
            "LegacyOperatingForecastProjection.currency_unit",
            maximum=40,
        )

    @property
    def profit_margin_percent(self) -> Decimal:
        """Return the historical projection's net-profit margin in percent."""

        return self.net_profit / self.revenue * Decimal("100")


@dataclass(frozen=True)
class LegacyOperatingForecastVersion:
    """Explicit research-only compatibility DTO for unbound pre-bridge rows."""

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
    assumptions: tuple[LegacyOperatingForecastAssumption, ...]
    projections: tuple[LegacyOperatingForecastProjection, ...]
    original_content_hash: str
    historical_valuation_consumable: bool
    promotion_decision_id: str
    legacy_hash_recipe: OperatingForecastLegacyHashRecipe
    legacy_hash_status: OperatingForecastLegacyHashStatus
    source_kind: OperatingForecastSourceKind = OperatingForecastSourceKind.LEGACY_MANUAL
    evidence_schema_version: int = 1
    source_lineage_status: OperatingForecastSourceLineageStatus = (
        OperatingForecastSourceLineageStatus.LEGACY_UNBOUND
    )
    valuation_consumable: bool = False

    def __post_init__(self) -> None:
        if self.source_kind is not OperatingForecastSourceKind.LEGACY_MANUAL:
            raise ValueError("legacy forecast source_kind is invalid")
        if self.evidence_schema_version != 1:
            raise ValueError("legacy forecast evidence schema must remain v1")
        if self.source_lineage_status not in {
            OperatingForecastSourceLineageStatus.LEGACY_UNBOUND,
            OperatingForecastSourceLineageStatus.LEGACY_UNVERIFIED,
        }:
            raise ValueError("legacy forecast lineage status is invalid")
        if self.valuation_consumable:
            raise ValueError("legacy unbound forecasts must remain research-only")
        if self.legacy_hash_status is OperatingForecastLegacyHashStatus.VERIFIED:
            if self.legacy_hash_recipe not in {
                OperatingForecastLegacyHashRecipe.V1_0010_UNTYPED,
                OperatingForecastLegacyHashRecipe.V1_0011_TYPED,
            }:
                raise ValueError("verified legacy hash requires an exact historical recipe")
        elif (
            self.legacy_hash_status is not OperatingForecastLegacyHashStatus.UNVERIFIED
            or self.legacy_hash_recipe is not OperatingForecastLegacyHashRecipe.UNVERIFIED
            or self.source_lineage_status
            is not OperatingForecastSourceLineageStatus.LEGACY_UNVERIFIED
        ):
            raise ValueError("unverified legacy hash state is inconsistent")
        if len(self.original_content_hash) != 64 or any(
            character not in "0123456789abcdefABCDEF" for character in self.original_content_hash
        ):
            raise ValueError("legacy forecast content hash must be a sha256 digest")
        scenarios = [projection.scenario for projection in self.projections]
        if set(scenarios) != set(ForecastScenario) or len(scenarios) != len(ForecastScenario):
            raise ValueError("legacy forecast must contain exactly base, bull and bear")

    @property
    def content_hash(self) -> str:
        """Return the verified pre-bridge content hash without changing its semantics."""

        return self.original_content_hash

    @property
    def usage_scope(self) -> str:
        """Keep legacy unbound rows outside approved valuation reads."""

        return "legacy_research_only"


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
    subject_code: str
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
        _require_token(self.subject_code, "OperatingForecastEvaluation.subject_code", maximum=80)
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
        facts_by_metric = {fact.metric_code: fact for fact in self.actual_facts}
        if len(facts_by_metric) != len(self.actual_facts):
            raise ValueError("actual facts must contain unique typed metric roles")
        if set(facts_by_metric) != {
            OperatingMetricRole.REVENUE.value,
            OperatingMetricRole.NET_PROFIT.value,
        }:
            raise ValueError("actual facts must contain exactly revenue and net_profit roles")
        for role, expected_value in (
            (OperatingMetricRole.REVENUE, self.actual_revenue),
            (OperatingMetricRole.NET_PROFIT, self.actual_net_profit),
        ):
            fact = facts_by_metric.get(role.value)
            if (
                fact is None
                or fact.subject_type != "company"
                or fact.subject_code != self.subject_code
                or fact.value != expected_value
                or fact.unit != self.currency_unit
            ):
                raise ValueError(
                    "quarterly actual must exactly match PIT subject, metric, value and unit"
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
            "subject_code": self.subject_code,
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
    forecast: OperatingForecastVersion | LegacyOperatingForecastVersion,
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
    if isinstance(forecast, OperatingForecastVersion):
        return tuple(
            OperatingForecastEvaluation(
                forecast_id=forecast.forecast_id,
                subject_code=forecast.subject_code,
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
            for projection in sorted(
                forecast.projections,
                key=lambda item: item.scenario.value,
            )
        )
    return tuple(
        OperatingForecastEvaluation(
            forecast_id=forecast.forecast_id,
            subject_code=forecast.subject_code,
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
        for projection in sorted(
            forecast.projections,
            key=lambda item: item.scenario.value,
        )
    )


__all__ = [
    "ForecastInputKind",
    "ForecastScenario",
    "LegacyOperatingForecastProjection",
    "LegacyOperatingForecastAssumption",
    "LegacyOperatingForecastVersion",
    "LegacyValuationSensitivityPoint",
    "OperatingMetricRole",
    "OperatingFactEvidence",
    "OperatingForecastAssumption",
    "OperatingForecastEvaluation",
    "OperatingForecastProjection",
    "OperatingForecastLegacyHashRecipe",
    "OperatingForecastLegacyHashStatus",
    "OperatingForecastSourceKind",
    "OperatingForecastSourceLineageStatus",
    "OperatingForecastStage",
    "OperatingForecastStageValue",
    "OperatingForecastVersion",
    "ValuationSensitivityPoint",
    "build_quarterly_evaluations",
]
