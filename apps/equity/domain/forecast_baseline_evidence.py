"""R1 forecast-baseline evidence primitives and canonical seals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum

from .operating_forecast import ForecastScenario


class BaselineFamily(str, Enum):
    """Typed baseline methodology families; parameters remain governed data."""

    SEASONAL_NAIVE = "seasonal_naive"
    LAST_AVAILABLE_ACTUAL = "last_available_actual"
    EXTERNAL_CONSENSUS = "external_consensus"


class BaselineApprovalStatus(str, Enum):
    """Owner approval state accepted by the baseline contract."""

    APPROVED = "approved"


class BaselineComputationMethod(str, Enum):
    """Auditable computation method implemented by the Domain."""

    DIRECT_APPROVED_SOURCE = "direct_approved_source"


class ForecastErrorMetric(str, Enum):
    """Supported paired forecast error semantics."""

    MAE = "mae"
    MAPE = "mape"


class MapeZeroActualRule(str, Enum):
    """Explicit handling of a zero actual in MAPE calculations."""

    BLOCK = "block"
    EXCLUDE_WITH_COVERAGE_PENALTY = "exclude_with_coverage_penalty"


class TieBreakRule(str, Enum):
    """Explicit winner when forecast and baseline errors are identical."""

    BASELINE_WINS = "baseline_wins"
    FORECAST_WINS = "forecast_wins"


class CostApplicability(str, Enum):
    """Whether an evaluation has an approved cost model."""

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"


class InvalidationOperator(str, Enum):
    """Typed comparison operator for a versioned invalidation condition."""

    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"


class InvalidationApplicability(str, Enum):
    """Whether a baseline requires executable invalidation rules."""

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"


def _require_token(value: str, field_name: str, *, maximum: int = 192) -> None:
    if not value or len(value) > maximum or any(character.isspace() for character in value):
        raise ValueError(f"{field_name} must be a bounded token")


def _require_text(value: str, field_name: str, *, maximum: int = 512) -> None:
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be bounded non-blank text")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _decimal_text(value: Decimal) -> str:
    _require_finite(value, "decimal")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _utc_text(value: datetime) -> str:
    _require_aware(value, "datetime")
    return value.astimezone(UTC).isoformat()


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class BaselineComputationEvidence:
    """Exact, canonically hashed inputs for a Domain-recomputable baseline."""

    family: BaselineFamily
    method: BaselineComputationMethod
    code_version: str
    family_parameter_version: str
    family_parameter_hash: str
    seasonal_lag_periods: int | None
    source_value: Decimal
    source_unit: str
    source_member_id: str
    source_member_version: str
    source_member_content_hash: str
    source_fact_id: str
    source_fact_version: str
    source_fact_content_hash: str
    source_vintage_id: str
    source_vintage_version: str
    source_vintage_content_hash: str
    computation_hash: str

    @classmethod
    def create(
        cls,
        *,
        family: BaselineFamily,
        method: BaselineComputationMethod,
        code_version: str,
        family_parameter_version: str,
        family_parameter_hash: str,
        seasonal_lag_periods: int | None,
        source_value: Decimal,
        source_unit: str,
        source_member_id: str,
        source_member_version: str,
        source_member_content_hash: str,
        source_fact_id: str,
        source_fact_version: str,
        source_fact_content_hash: str,
        source_vintage_id: str,
        source_vintage_version: str,
        source_vintage_content_hash: str,
    ) -> BaselineComputationEvidence:
        """Seal exact source evidence for the implemented direct-value method."""

        payload = _baseline_computation_payload(
            family=family,
            method=method,
            code_version=code_version,
            family_parameter_version=family_parameter_version,
            family_parameter_hash=family_parameter_hash,
            seasonal_lag_periods=seasonal_lag_periods,
            source_value=source_value,
            source_unit=source_unit,
            source_member_id=source_member_id,
            source_member_version=source_member_version,
            source_member_content_hash=source_member_content_hash,
            source_fact_id=source_fact_id,
            source_fact_version=source_fact_version,
            source_fact_content_hash=source_fact_content_hash,
            source_vintage_id=source_vintage_id,
            source_vintage_version=source_vintage_version,
            source_vintage_content_hash=source_vintage_content_hash,
        )
        return cls(
            family=family,
            method=method,
            code_version=code_version,
            family_parameter_version=family_parameter_version,
            family_parameter_hash=family_parameter_hash,
            seasonal_lag_periods=seasonal_lag_periods,
            source_value=source_value,
            source_unit=source_unit,
            source_member_id=source_member_id,
            source_member_version=source_member_version,
            source_member_content_hash=source_member_content_hash,
            source_fact_id=source_fact_id,
            source_fact_version=source_fact_version,
            source_fact_content_hash=source_fact_content_hash,
            source_vintage_id=source_vintage_id,
            source_vintage_version=source_vintage_version,
            source_vintage_content_hash=source_vintage_content_hash,
            computation_hash=_hash_payload(payload),
        )

    def __post_init__(self) -> None:
        if self.family not in {
            BaselineFamily.SEASONAL_NAIVE,
            BaselineFamily.EXTERNAL_CONSENSUS,
        }:
            raise ValueError("baseline family has no implemented computation")
        if self.method is not BaselineComputationMethod.DIRECT_APPROVED_SOURCE:
            raise ValueError("baseline computation method is not implemented")
        _require_token(self.code_version, "baseline computation code_version")
        _require_token(self.family_parameter_version, "family_parameter_version")
        _require_sha256(self.family_parameter_hash, "family_parameter_hash")
        if self.family is BaselineFamily.SEASONAL_NAIVE:
            if (
                isinstance(self.seasonal_lag_periods, bool)
                or self.seasonal_lag_periods is None
                or self.seasonal_lag_periods < 1
            ):
                raise ValueError("seasonal computation requires an approved positive lag")
        elif self.seasonal_lag_periods is not None:
            raise ValueError("non-seasonal computation cannot carry a seasonal lag")
        _require_finite(self.source_value, "baseline computation source_value")
        _require_text(self.source_unit, "baseline computation source_unit", maximum=40)
        for field_name, value in (
            ("source_member_id", self.source_member_id),
            ("source_member_version", self.source_member_version),
            ("source_fact_id", self.source_fact_id),
            ("source_fact_version", self.source_fact_version),
            ("source_vintage_id", self.source_vintage_id),
            ("source_vintage_version", self.source_vintage_version),
        ):
            _require_token(value, f"baseline computation {field_name}")
        for field_name, value in (
            ("source_member_content_hash", self.source_member_content_hash),
            ("source_fact_content_hash", self.source_fact_content_hash),
            ("source_vintage_content_hash", self.source_vintage_content_hash),
        ):
            _require_sha256(value, f"baseline computation {field_name}")
        _require_sha256(self.computation_hash, "baseline computation_hash")
        payload = _baseline_computation_payload(
            family=self.family,
            method=self.method,
            code_version=self.code_version,
            family_parameter_version=self.family_parameter_version,
            family_parameter_hash=self.family_parameter_hash,
            seasonal_lag_periods=self.seasonal_lag_periods,
            source_value=self.source_value,
            source_unit=self.source_unit,
            source_member_id=self.source_member_id,
            source_member_version=self.source_member_version,
            source_member_content_hash=self.source_member_content_hash,
            source_fact_id=self.source_fact_id,
            source_fact_version=self.source_fact_version,
            source_fact_content_hash=self.source_fact_content_hash,
            source_vintage_id=self.source_vintage_id,
            source_vintage_version=self.source_vintage_version,
            source_vintage_content_hash=self.source_vintage_content_hash,
        )
        if self.computation_hash != _hash_payload(payload):
            raise ValueError("baseline computation hash mismatch")

    def recompute_value(self) -> Decimal:
        """Return the value defined by the approved direct-source computation."""

        return self.source_value


def _baseline_computation_payload(
    *,
    family: BaselineFamily,
    method: BaselineComputationMethod,
    code_version: str,
    family_parameter_version: str,
    family_parameter_hash: str,
    seasonal_lag_periods: int | None,
    source_value: Decimal,
    source_unit: str,
    source_member_id: str,
    source_member_version: str,
    source_member_content_hash: str,
    source_fact_id: str,
    source_fact_version: str,
    source_fact_content_hash: str,
    source_vintage_id: str,
    source_vintage_version: str,
    source_vintage_content_hash: str,
) -> dict[str, object]:
    return {
        "schema": "r1-baseline-computation.v2",
        "family": family.value,
        "method": method.value,
        "code_version": code_version,
        "family_parameters": [
            family_parameter_version,
            family_parameter_hash,
            seasonal_lag_periods,
        ],
        "source_value": _decimal_text(source_value),
        "source_unit": source_unit,
        "source_member": [
            source_member_id,
            source_member_version,
            source_member_content_hash,
        ],
        "source_fact": [source_fact_id, source_fact_version, source_fact_content_hash],
        "source_vintage": [
            source_vintage_id,
            source_vintage_version,
            source_vintage_content_hash,
        ],
    }


@dataclass(frozen=True)
class BaselinePITSelectedVersion:
    """Typed manifest selection binding member, fact and vintage identities."""

    selected_member_id: str
    selected_member_version: str
    selected_member_content_hash: str
    source_fact_id: str
    source_fact_version: str
    source_fact_content_hash: str
    vintage_id: str
    vintage_version: str
    vintage_content_hash: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("selected_member_id", self.selected_member_id),
            ("selected_member_version", self.selected_member_version),
            ("source_fact_id", self.source_fact_id),
            ("source_fact_version", self.source_fact_version),
            ("vintage_id", self.vintage_id),
            ("vintage_version", self.vintage_version),
        ):
            _require_token(value, field_name)
        for field_name, value in (
            ("selected_member_content_hash", self.selected_member_content_hash),
            ("source_fact_content_hash", self.source_fact_content_hash),
            ("vintage_content_hash", self.vintage_content_hash),
        ):
            _require_sha256(value, field_name)

    @property
    def identity_tuple(self) -> tuple[str, str, str, str, str, str, str, str, str]:
        """Return the canonical three-layer identity tuple."""

        return (
            self.selected_member_id,
            self.selected_member_version,
            self.selected_member_content_hash,
            self.source_fact_id,
            self.source_fact_version,
            self.source_fact_content_hash,
            self.vintage_id,
            self.vintage_version,
            self.vintage_content_hash,
        )


@dataclass(frozen=True)
class BaselinePITManifestMember:
    """Exact immutable manifest member selected for one target metric period."""

    target_period_end: date
    source_period_end: date
    metric_code: str
    selected_member_id: str
    selected_member_version: str
    selected_member_content_hash: str
    source_value: Decimal
    source_unit: str
    source_effective_at: datetime
    source_available_at: datetime
    source_fact_id: str
    source_fact_version: str
    source_fact_content_hash: str
    vintage_id: str
    vintage_version: str
    vintage_content_hash: str

    @property
    def selected_version(self) -> BaselinePITSelectedVersion:
        """Return the exact three-layer identity selected by this member."""

        return BaselinePITSelectedVersion(
            selected_member_id=self.selected_member_id,
            selected_member_version=self.selected_member_version,
            selected_member_content_hash=self.selected_member_content_hash,
            source_fact_id=self.source_fact_id,
            source_fact_version=self.source_fact_version,
            source_fact_content_hash=self.source_fact_content_hash,
            vintage_id=self.vintage_id,
            vintage_version=self.vintage_version,
            vintage_content_hash=self.vintage_content_hash,
        )

    def __post_init__(self) -> None:
        _require_token(self.metric_code, "PIT member metric_code")
        for field_name, value in (
            ("selected_member_id", self.selected_member_id),
            ("selected_member_version", self.selected_member_version),
            ("source_fact_id", self.source_fact_id),
            ("source_fact_version", self.source_fact_version),
            ("vintage_id", self.vintage_id),
            ("vintage_version", self.vintage_version),
        ):
            _require_token(value, f"PIT member {field_name}")
        for field_name, value in (
            ("selected_member_content_hash", self.selected_member_content_hash),
            ("source_fact_content_hash", self.source_fact_content_hash),
            ("vintage_content_hash", self.vintage_content_hash),
        ):
            _require_sha256(value, f"PIT member {field_name}")
        _require_finite(self.source_value, "PIT member source_value")
        _require_text(self.source_unit, "PIT member source_unit", maximum=40)
        _require_aware(self.source_effective_at, "PIT member source_effective_at")
        _require_aware(self.source_available_at, "PIT member source_available_at")
        if self.source_available_at < self.source_effective_at:
            raise ValueError("PIT member source cannot be available before effective time")


@dataclass(frozen=True)
class BaselinePITInputSpec:
    """One governed input dimension bound to exact PIT and calendar identity."""

    input_role: str
    dataset: str
    metric_code: str
    unit: str
    pit_manifest_id: str
    pit_manifest_version: str
    pit_manifest_hash: str
    manifest_as_of_time: datetime
    manifest_produced_at: datetime
    manifest_knowledge_scope: str
    manifest_is_verified: bool
    manifest_coverage_ratio: Decimal
    manifest_missing_count: int
    manifest_estimated_count: int
    manifest_unknown_count: int
    selected_versions: tuple[BaselinePITSelectedVersion, ...]
    selected_versions_hash: str
    members: tuple[BaselinePITManifestMember, ...]
    calendar_id: str
    calendar_version: str
    calendar_content_hash: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("input_role", self.input_role),
            ("dataset", self.dataset),
            ("metric_code", self.metric_code),
            ("pit_manifest_id", self.pit_manifest_id),
            ("pit_manifest_version", self.pit_manifest_version),
            ("manifest_knowledge_scope", self.manifest_knowledge_scope),
            ("calendar_id", self.calendar_id),
            ("calendar_version", self.calendar_version),
        ):
            _require_token(value, field_name)
        _require_text(self.unit, "unit", maximum=40)
        _require_sha256(self.pit_manifest_hash, "pit_manifest_hash")
        if self.manifest_knowledge_scope != "public":
            raise ValueError("baseline PIT manifest must use public knowledge")
        _require_aware(self.manifest_as_of_time, "manifest_as_of_time")
        _require_aware(self.manifest_produced_at, "manifest_produced_at")
        if self.manifest_as_of_time > self.manifest_produced_at:
            raise ValueError("PIT manifest cannot be produced before its as-of time")
        if self.manifest_is_verified is not True:
            raise ValueError("baseline PIT manifest must be verified")
        if self.manifest_coverage_ratio != Decimal("1"):
            raise ValueError("baseline PIT manifest coverage must be complete")
        for field_name, count in (
            ("manifest_missing_count", self.manifest_missing_count),
            ("manifest_estimated_count", self.manifest_estimated_count),
            ("manifest_unknown_count", self.manifest_unknown_count),
        ):
            if isinstance(count, bool) or count != 0:
                raise ValueError(f"{field_name} must be zero")
        member_keys = tuple((item.target_period_end, item.metric_code) for item in self.members)
        if (
            not member_keys
            or member_keys != tuple(sorted(member_keys))
            or len(member_keys) != len(set(member_keys))
            or any(item.metric_code != self.metric_code for item in self.members)
        ):
            raise ValueError("PIT members must be non-empty, ordered, unique and metric-bound")
        if any(item.source_available_at > self.manifest_as_of_time for item in self.members):
            raise ValueError("PIT manifest contains a fact unavailable at its as-of time")
        canonical_versions = tuple(
            sorted(self.selected_versions, key=lambda item: item.identity_tuple)
        )
        member_versions = tuple(
            sorted(
                (item.selected_version for item in self.members),
                key=lambda item: item.identity_tuple,
            )
        )
        if (
            not self.selected_versions
            or self.selected_versions != canonical_versions
            or len(self.selected_versions) != len(set(self.selected_versions))
            or self.selected_versions != member_versions
        ):
            raise ValueError("manifest selected versions must exactly match PIT members")
        _require_sha256(self.selected_versions_hash, "selected_versions_hash")
        selected_payload: dict[str, object] = {
            "schema": "r1-baseline-selected-versions.v1",
            "versions": [list(item.identity_tuple) for item in self.selected_versions],
        }
        if self.selected_versions_hash != _hash_payload(selected_payload):
            raise ValueError("manifest selected versions hash mismatch")
        _require_sha256(self.calendar_content_hash, "calendar_content_hash")


@dataclass(frozen=True)
class ForecastCalendarPeriod:
    """One canonical period and ordinal from the Data Center calendar."""

    period_end: date
    ordinal: int

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError("calendar period ordinal must be non-negative")


@dataclass(frozen=True)
class ForecastCalendarScheduleEvidence:
    """Sealed Data Center calendar schedule used to derive forecast horizons."""

    owner: str
    calendar_id: str
    calendar_version: str
    calendar_content_hash: str
    periods: tuple[ForecastCalendarPeriod, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        owner: str,
        calendar_id: str,
        calendar_version: str,
        calendar_content_hash: str,
        periods: tuple[ForecastCalendarPeriod, ...],
    ) -> ForecastCalendarScheduleEvidence:
        """Seal an ordered canonical calendar schedule without supplying defaults."""

        payload = _calendar_schedule_payload(
            owner=owner,
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            calendar_content_hash=calendar_content_hash,
            periods=periods,
        )
        return cls(
            owner=owner,
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            calendar_content_hash=calendar_content_hash,
            periods=periods,
            content_hash=_hash_payload(payload),
        )

    def __post_init__(self) -> None:
        if self.owner != "data_center":
            raise ValueError("forecast calendar schedule owner must be data_center")
        _require_token(self.calendar_id, "schedule calendar_id")
        _require_token(self.calendar_version, "schedule calendar_version")
        _require_sha256(self.calendar_content_hash, "schedule calendar_content_hash")
        period_ends = tuple(item.period_end for item in self.periods)
        ordinals = tuple(item.ordinal for item in self.periods)
        if (
            not period_ends
            or period_ends != tuple(sorted(period_ends))
            or len(period_ends) != len(set(period_ends))
            or any(right != left + 1 for left, right in zip(ordinals, ordinals[1:], strict=False))
        ):
            raise ValueError("calendar schedule periods and ordinals must be contiguous")
        _require_sha256(self.content_hash, "schedule content_hash")
        if self.content_hash != _hash_payload(
            _calendar_schedule_payload(
                owner=self.owner,
                calendar_id=self.calendar_id,
                calendar_version=self.calendar_version,
                calendar_content_hash=self.calendar_content_hash,
                periods=self.periods,
            )
        ):
            raise ValueError("forecast calendar schedule content hash mismatch")


def _calendar_schedule_payload(
    *,
    owner: str,
    calendar_id: str,
    calendar_version: str,
    calendar_content_hash: str,
    periods: tuple[ForecastCalendarPeriod, ...],
) -> dict[str, object]:
    return {
        "schema": "r1-forecast-calendar-schedule.v1",
        "owner": owner,
        "calendar": [calendar_id, calendar_version, calendar_content_hash],
        "periods": [[item.period_end.isoformat(), item.ordinal] for item in periods],
    }


@dataclass(frozen=True)
class ForecastPeriodHorizon:
    """Governed mapping from one forecast origin to one target calendar period."""

    target_period_end: date
    forecast_origin_at: datetime
    origin_period_ordinal: int
    target_period_ordinal: int
    horizon_quarters: int
    calendar_id: str
    calendar_version: str
    calendar_content_hash: str
    schedule_content_hash: str

    @classmethod
    def create(
        cls,
        *,
        target_period_end: date,
        forecast_origin_at: datetime,
        schedule: ForecastCalendarScheduleEvidence,
    ) -> ForecastPeriodHorizon:
        """Derive an exact horizon from canonical schedule ordinals."""

        origin = _origin_calendar_period(schedule, forecast_origin_at)
        target = next(
            (item for item in schedule.periods if item.period_end == target_period_end),
            None,
        )
        if target is None or target.ordinal <= origin.ordinal:
            raise ValueError("target period is not after the forecast origin period")
        return cls(
            target_period_end=target_period_end,
            forecast_origin_at=forecast_origin_at,
            origin_period_ordinal=origin.ordinal,
            target_period_ordinal=target.ordinal,
            horizon_quarters=target.ordinal - origin.ordinal,
            calendar_id=schedule.calendar_id,
            calendar_version=schedule.calendar_version,
            calendar_content_hash=schedule.calendar_content_hash,
            schedule_content_hash=schedule.content_hash,
        )

    def __post_init__(self) -> None:
        _require_aware(self.forecast_origin_at, "forecast origin")
        if self.target_period_end < self.forecast_origin_at.date():
            raise ValueError("forecast target cannot predate forecast origin")
        if isinstance(self.horizon_quarters, bool) or self.horizon_quarters < 1:
            raise ValueError("period horizon_quarters must be positive")
        if (
            isinstance(self.origin_period_ordinal, bool)
            or isinstance(self.target_period_ordinal, bool)
            or self.origin_period_ordinal < 0
            or self.target_period_ordinal <= self.origin_period_ordinal
        ):
            raise ValueError("period horizon ordinals are invalid")
        _require_token(self.calendar_id, "period horizon calendar_id")
        _require_token(self.calendar_version, "period horizon calendar_version")
        _require_sha256(
            self.calendar_content_hash,
            "period horizon calendar_content_hash",
        )
        _require_sha256(self.schedule_content_hash, "period horizon schedule_content_hash")


def _origin_calendar_period(
    schedule: ForecastCalendarScheduleEvidence,
    forecast_origin_at: datetime,
) -> ForecastCalendarPeriod:
    _require_aware(forecast_origin_at, "forecast origin")
    candidates = tuple(
        item for item in schedule.periods if item.period_end <= forecast_origin_at.date()
    )
    if not candidates:
        raise ValueError("calendar schedule does not cover the forecast origin")
    return candidates[-1]


@dataclass(frozen=True)
class ActualFactObservation:
    """Exact PIT actual fact returned by the future provider boundary."""

    subject_code: str
    industry_code: str
    dataset: str
    period_end: date
    metric_code: str
    value: Decimal
    unit: str
    source_fact_id: str
    source_fact_version: str
    source_fact_content_hash: str
    revision_number: int
    observation_hash: str
    effective_at: datetime
    available_at: datetime
    vintage_id: str
    vintage_version: str
    vintage_content_hash: str
    pit_manifest_id: str
    pit_manifest_hash: str
    manifest_member_id: str
    manifest_member_version: str
    manifest_member_content_hash: str
    calendar_id: str
    calendar_version: str
    calendar_content_hash: str

    @classmethod
    def create(
        cls,
        *,
        subject_code: str,
        industry_code: str,
        dataset: str,
        period_end: date,
        metric_code: str,
        value: Decimal,
        unit: str,
        source_fact_id: str,
        source_fact_version: str,
        source_fact_content_hash: str,
        revision_number: int,
        effective_at: datetime,
        available_at: datetime,
        vintage_id: str,
        vintage_version: str,
        vintage_content_hash: str,
        pit_manifest_id: str,
        pit_manifest_hash: str,
        manifest_member_id: str,
        manifest_member_version: str,
        manifest_member_content_hash: str,
        calendar_id: str,
        calendar_version: str,
        calendar_content_hash: str,
    ) -> ActualFactObservation:
        """Seal an exact provider fact using canonical Decimal and UTC hashing."""

        payload = _actual_fact_payload(
            subject_code=subject_code,
            industry_code=industry_code,
            dataset=dataset,
            period_end=period_end,
            metric_code=metric_code,
            value=value,
            unit=unit,
            source_fact_id=source_fact_id,
            source_fact_version=source_fact_version,
            source_fact_content_hash=source_fact_content_hash,
            revision_number=revision_number,
            effective_at=effective_at,
            available_at=available_at,
            vintage_id=vintage_id,
            vintage_version=vintage_version,
            vintage_content_hash=vintage_content_hash,
            pit_manifest_id=pit_manifest_id,
            pit_manifest_hash=pit_manifest_hash,
            manifest_member_id=manifest_member_id,
            manifest_member_version=manifest_member_version,
            manifest_member_content_hash=manifest_member_content_hash,
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            calendar_content_hash=calendar_content_hash,
        )
        return cls(
            subject_code=subject_code,
            industry_code=industry_code,
            dataset=dataset,
            period_end=period_end,
            metric_code=metric_code,
            value=value,
            unit=unit,
            source_fact_id=source_fact_id,
            source_fact_version=source_fact_version,
            source_fact_content_hash=source_fact_content_hash,
            revision_number=revision_number,
            observation_hash=_hash_payload(payload),
            effective_at=effective_at,
            available_at=available_at,
            vintage_id=vintage_id,
            vintage_version=vintage_version,
            vintage_content_hash=vintage_content_hash,
            pit_manifest_id=pit_manifest_id,
            pit_manifest_hash=pit_manifest_hash,
            manifest_member_id=manifest_member_id,
            manifest_member_version=manifest_member_version,
            manifest_member_content_hash=manifest_member_content_hash,
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            calendar_content_hash=calendar_content_hash,
        )

    def __post_init__(self) -> None:
        _require_token(self.subject_code, "actual subject_code")
        _require_token(self.industry_code, "actual industry_code")
        _require_token(self.dataset, "actual dataset")
        _require_token(self.metric_code, "actual metric_code")
        _require_finite(self.value, "actual value")
        _require_text(self.unit, "actual unit", maximum=40)
        _require_token(self.source_fact_id, "actual source_fact_id")
        _require_token(self.source_fact_version, "actual source_fact_version")
        _require_sha256(self.source_fact_content_hash, "actual source_fact_content_hash")
        if isinstance(self.revision_number, bool) or self.revision_number < 1:
            raise ValueError("actual revision_number must be positive")
        _require_sha256(self.observation_hash, "actual observation_hash")
        _require_aware(self.effective_at, "actual effective_at")
        _require_aware(self.available_at, "actual available_at")
        if self.available_at < self.effective_at:
            raise ValueError("actual cannot be available before effective time")
        _require_token(self.vintage_id, "actual vintage_id")
        _require_token(self.vintage_version, "actual vintage_version")
        _require_sha256(self.vintage_content_hash, "actual vintage_content_hash")
        _require_token(self.pit_manifest_id, "actual pit_manifest_id")
        _require_sha256(self.pit_manifest_hash, "actual pit_manifest_hash")
        _require_token(self.manifest_member_id, "actual manifest_member_id")
        _require_token(self.manifest_member_version, "actual manifest_member_version")
        _require_sha256(
            self.manifest_member_content_hash,
            "actual manifest_member_content_hash",
        )
        _require_token(self.calendar_id, "actual calendar_id")
        _require_token(self.calendar_version, "actual calendar_version")
        _require_sha256(self.calendar_content_hash, "actual calendar_content_hash")
        if self.observation_hash != _hash_payload(
            _actual_fact_payload(
                subject_code=self.subject_code,
                industry_code=self.industry_code,
                dataset=self.dataset,
                period_end=self.period_end,
                metric_code=self.metric_code,
                value=self.value,
                unit=self.unit,
                source_fact_id=self.source_fact_id,
                source_fact_version=self.source_fact_version,
                source_fact_content_hash=self.source_fact_content_hash,
                revision_number=self.revision_number,
                effective_at=self.effective_at,
                available_at=self.available_at,
                vintage_id=self.vintage_id,
                vintage_version=self.vintage_version,
                vintage_content_hash=self.vintage_content_hash,
                pit_manifest_id=self.pit_manifest_id,
                pit_manifest_hash=self.pit_manifest_hash,
                manifest_member_id=self.manifest_member_id,
                manifest_member_version=self.manifest_member_version,
                manifest_member_content_hash=self.manifest_member_content_hash,
                calendar_id=self.calendar_id,
                calendar_version=self.calendar_version,
                calendar_content_hash=self.calendar_content_hash,
            )
        ):
            raise ValueError("actual observation hash mismatch")


def _actual_fact_payload(
    *,
    subject_code: str,
    industry_code: str,
    dataset: str,
    period_end: date,
    metric_code: str,
    value: Decimal,
    unit: str,
    source_fact_id: str,
    source_fact_version: str,
    source_fact_content_hash: str,
    revision_number: int,
    effective_at: datetime,
    available_at: datetime,
    vintage_id: str,
    vintage_version: str,
    vintage_content_hash: str,
    pit_manifest_id: str,
    pit_manifest_hash: str,
    manifest_member_id: str,
    manifest_member_version: str,
    manifest_member_content_hash: str,
    calendar_id: str,
    calendar_version: str,
    calendar_content_hash: str,
) -> dict[str, object]:
    return {
        "schema": "r1-actual-fact-observation.v4",
        "scope": [subject_code, industry_code, dataset],
        "period_end": period_end.isoformat(),
        "metric_code": metric_code,
        "value": _decimal_text(value),
        "unit": unit,
        "source_fact": [source_fact_id, source_fact_version, source_fact_content_hash],
        "revision_number": revision_number,
        "effective_at": _utc_text(effective_at),
        "available_at": _utc_text(available_at),
        "vintage": [vintage_id, vintage_version, vintage_content_hash],
        "pit_manifest": [pit_manifest_id, pit_manifest_hash],
        "manifest_member": [
            manifest_member_id,
            manifest_member_version,
            manifest_member_content_hash,
        ],
        "calendar": [calendar_id, calendar_version, calendar_content_hash],
    }


__all__ = [
    "ActualFactObservation",
    "BaselineApprovalStatus",
    "BaselineComputationEvidence",
    "BaselineComputationMethod",
    "BaselineFamily",
    "BaselinePITInputSpec",
    "BaselinePITManifestMember",
    "BaselinePITSelectedVersion",
    "CostApplicability",
    "ForecastCalendarPeriod",
    "ForecastCalendarScheduleEvidence",
    "ForecastErrorMetric",
    "ForecastPeriodHorizon",
    "ForecastScenario",
    "InvalidationApplicability",
    "InvalidationOperator",
    "MapeZeroActualRule",
    "TieBreakRule",
]
