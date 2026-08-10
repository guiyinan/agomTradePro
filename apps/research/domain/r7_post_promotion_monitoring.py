"""Fail-closed R7 forecast monitoring over exact owner-sealed outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from apps.research.domain.r7_post_promotion_monitoring_contracts import (
    R7MonitoringActiveResult,
    R7MonitoringPeriodCalendar,
    R7MonitoringPeriodEntry,
    R7MonitoringPredictionMember,
    _aware,
    _decimal_text,
    _utc_text,
)
from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
)
from apps.research.domain.scenario_research_hashing import (
    hash_components,
    require_sha256,
    require_token,
)
from apps.signal.domain.forecast_scenario_evidence import ScenarioProbabilitySource

_REALIZATION_MEMBER_VERSION = "r7-monitoring-realization-member.v1"
_REALIZATION_OWNER_VERSION = "r7-monitoring-realization-owner-record.v1"
_REALIZATION_FACT_VERSION = "r7-monitoring-realization-fact.v1"
_ASSESSMENT_VERSION = "r7-post-promotion-monitoring-assessment.v1"
_FORECAST_OWNER = "signal.forecast_ledger"


class R7MonitoringStatus(StrEnum):
    """Research-only state; no member performs a lifecycle mutation."""

    HEALTHY = "healthy"
    BREACHED = "breached"
    RETIREMENT_REVIEW_REQUIRED = "retirement_review_required"
    BLOCKED = "blocked"


class R7MonitoringBlockerCode(StrEnum):
    """Stable blockers for evidence that is absent or cannot be replayed."""

    ACTIVE_RESULT_INVALID = "active_result_invalid"
    PERIOD_INVALID = "period_invalid"
    CALENDAR_INVALID = "calendar_invalid"
    REALIZATION_INVALID = "realization_invalid"
    REALIZATION_FUTURE_OR_EXPIRED = "realization_future_or_expired"
    FORECAST_OUTCOME_INCOMPLETE = "forecast_outcome_incomplete"
    CALIBRATION_EVIDENCE_UNAVAILABLE = "calibration_evidence_unavailable"
    HISTORICAL_ANALOGY_EVIDENCE_UNAVAILABLE = "historical_analogy_evidence_unavailable"
    PATH_EVIDENCE_UNAVAILABLE = "path_evidence_unavailable"


@dataclass(frozen=True)
class R7ForecastRealizationMember:
    """One exact Forecast Ledger outcome row plus its owner-availability clocks."""

    member_version: str
    observation_id: str
    observation_version: str
    observation_hash: str
    prediction_hash: str
    entry_id: str
    forecast_group_id: str
    scenario_revision_id: UUID
    published_at: datetime
    horizon_end: datetime
    realized: bool | None
    invalidated: bool
    available_at: datetime
    recorded_at: datetime
    evidence_ref: str
    content_hash: str

    @classmethod
    def from_owner_observation(
        cls,
        *,
        observation: ForecastLedgerOutcomeObservation,
        available_at: datetime,
        recorded_at: datetime,
        evidence_ref: str,
    ) -> R7ForecastRealizationMember:
        """Project one independently read owner row without deriving an outcome."""

        if type(observation) is not ForecastLedgerOutcomeObservation:
            raise TypeError("R7 realization requires an exact Forecast Ledger row")
        observation.__post_init__()
        outcome_available_at = observation.outcome_recorded_at
        invalidated = observation.invalidation is not None
        if invalidated:
            assert observation.invalidation is not None
            outcome_available_at = observation.invalidation.invalidated_at
        if outcome_available_at is None:
            outcome_available_at = observation.horizon_end
        prediction_hash = R7MonitoringActiveResult.prediction_hash_from_observation(observation)
        values = (
            _REALIZATION_MEMBER_VERSION,
            observation.entry_id,
            observation.observation_version,
            observation.content_hash,
            prediction_hash,
            observation.entry_id,
            observation.forecast_group_id,
            observation.binding.scenario_revision_id,
            observation.published_at,
            observation.horizon_end,
            observation.scenario_realized,
            invalidated,
            available_at,
            recorded_at,
            evidence_ref,
        )
        member = cls(*values, _realization_member_hash(*values))
        if member.available_at < outcome_available_at:
            raise ValueError("R7 realization availability predates its owner outcome")
        return member

    def __post_init__(self) -> None:
        if self.member_version != _REALIZATION_MEMBER_VERSION:
            raise ValueError("R7 realization member version is unsupported")
        for label, value in (
            ("observation_id", self.observation_id),
            ("observation_version", self.observation_version),
            ("entry_id", self.entry_id),
            ("forecast_group_id", self.forecast_group_id),
            ("evidence_ref", self.evidence_ref),
        ):
            require_token(value, f"R7 realization {label}", maximum=300)
        if self.observation_id != self.entry_id:
            raise ValueError("R7 realization observation identity is aliased")
        require_sha256(self.observation_hash, "R7 realization observation_hash")
        require_sha256(self.prediction_hash, "R7 realization prediction_hash")
        require_sha256(self.content_hash, "R7 realization member content_hash")
        if type(self.scenario_revision_id) is not UUID:
            raise TypeError("R7 realization scenario revision is invalid")
        if self.realized is not None and type(self.realized) is not bool:
            raise TypeError("R7 realized outcome must be an exact bool or None")
        if type(self.invalidated) is not bool:
            raise TypeError("R7 invalidation flag must be an exact bool")
        if self.realized is not None and self.invalidated:
            raise ValueError("R7 realized and invalidated outcomes are mutually exclusive")
        for label, clock_value in (
            ("published_at", self.published_at),
            ("horizon_end", self.horizon_end),
            ("available_at", self.available_at),
            ("recorded_at", self.recorded_at),
        ):
            _aware(clock_value, f"R7 realization {label}")
        if not self.published_at < self.horizon_end <= self.available_at <= self.recorded_at:
            raise ValueError("R7 realization member clocks are invalid")
        if self.content_hash != realization_member_hash(self):
            raise ValueError("R7 realization member content hash mismatch")

    def validated_copy(self) -> R7ForecastRealizationMember:
        """Rebuild and revalidate the complete owner projection."""

        self.__post_init__()
        return R7ForecastRealizationMember(
            member_version=self.member_version,
            observation_id=self.observation_id,
            observation_version=self.observation_version,
            observation_hash=self.observation_hash,
            prediction_hash=self.prediction_hash,
            entry_id=self.entry_id,
            forecast_group_id=self.forecast_group_id,
            scenario_revision_id=self.scenario_revision_id,
            published_at=self.published_at,
            horizon_end=self.horizon_end,
            realized=self.realized,
            invalidated=self.invalidated,
            available_at=self.available_at,
            recorded_at=self.recorded_at,
            evidence_ref=self.evidence_ref,
            content_hash=self.content_hash,
        )


def realization_member_hash(value: R7ForecastRealizationMember) -> str:
    """Recompute one full owner-observation projection seal."""

    return _realization_member_hash(
        value.member_version,
        value.observation_id,
        value.observation_version,
        value.observation_hash,
        value.prediction_hash,
        value.entry_id,
        value.forecast_group_id,
        value.scenario_revision_id,
        value.published_at,
        value.horizon_end,
        value.realized,
        value.invalidated,
        value.available_at,
        value.recorded_at,
        value.evidence_ref,
    )


def _realization_member_hash(
    member_version: str,
    observation_id: str,
    observation_version: str,
    observation_hash: str,
    prediction_hash: str,
    entry_id: str,
    forecast_group_id: str,
    scenario_revision_id: UUID,
    published_at: datetime,
    horizon_end: datetime,
    realized: bool | None,
    invalidated: bool,
    available_at: datetime,
    recorded_at: datetime,
    evidence_ref: str,
) -> str:
    outcome_token = "unresolved" if realized is None else ("true" if realized else "false")
    return hash_components(
        member_version,
        observation_id,
        observation_version,
        observation_hash.lower(),
        prediction_hash.lower(),
        entry_id,
        forecast_group_id,
        str(scenario_revision_id),
        _utc_text(published_at),
        _utc_text(horizon_end),
        outcome_token,
        "true" if invalidated else "false",
        _utc_text(available_at),
        _utc_text(recorded_at),
        evidence_ref,
    )


@dataclass(frozen=True)
class R7ForecastRealizationOwnerRecord:
    """Independent Forecast Ledger record that seals complete PIT membership."""

    record_version: str
    owner: str
    owner_record_id: str
    owner_record_version: str
    period_id: str
    period_hash: str
    period_start: datetime
    period_end: datetime
    pit_as_of: datetime
    available_at: datetime
    recorded_at: datetime
    valid_until: datetime
    evidence_ref: str
    members: tuple[R7ForecastRealizationMember, ...]
    payload_hash: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        owner_record_id: str,
        owner_record_version: str,
        period: R7MonitoringPeriodEntry,
        pit_as_of: datetime,
        available_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
        evidence_ref: str,
        members: tuple[R7ForecastRealizationMember, ...],
    ) -> R7ForecastRealizationOwnerRecord:
        """Seal an already-read owner payload; no outcome is synthesized here."""

        if type(period) is not R7MonitoringPeriodEntry:
            raise TypeError("R7 realization owner period type is invalid")
        period.__post_init__()
        if type(members) is not tuple or not members:
            raise ValueError("R7 realization owner requires complete members")
        canonical = tuple(
            sorted(
                members,
                key=lambda item: (
                    item.entry_id,
                    item.observation_version,
                    item.observation_id,
                ),
            )
        )
        for member in canonical:
            if type(member) is not R7ForecastRealizationMember:
                raise TypeError("R7 realization owner member type is invalid")
            member.__post_init__()
        payload_hash = hash_components(
            "r7-monitoring-realization-owner-payload.v1",
            period.content_hash,
            *(member.content_hash for member in canonical),
        )
        values = (
            _REALIZATION_OWNER_VERSION,
            _FORECAST_OWNER,
            owner_record_id,
            owner_record_version,
            period.period_id,
            period.content_hash,
            period.period_start,
            period.period_end,
            pit_as_of,
            available_at,
            recorded_at,
            valid_until,
            evidence_ref,
            canonical,
            payload_hash,
        )
        return cls(*values, _realization_owner_hash(*values))

    def __post_init__(self) -> None:
        if self.record_version != _REALIZATION_OWNER_VERSION:
            raise ValueError("R7 realization owner record version is unsupported")
        if self.owner != _FORECAST_OWNER:
            raise ValueError("R7 realization owner must be Forecast Ledger")
        for label, value in (
            ("owner_record_id", self.owner_record_id),
            ("owner_record_version", self.owner_record_version),
            ("period_id", self.period_id),
            ("evidence_ref", self.evidence_ref),
        ):
            require_token(value, f"R7 realization owner {label}", maximum=300)
        for label, value in (
            ("period_hash", self.period_hash),
            ("payload_hash", self.payload_hash),
            ("content_hash", self.content_hash),
        ):
            require_sha256(value, f"R7 realization owner {label}")
        for label, clock_value in (
            ("period_start", self.period_start),
            ("period_end", self.period_end),
            ("pit_as_of", self.pit_as_of),
            ("available_at", self.available_at),
            ("recorded_at", self.recorded_at),
            ("valid_until", self.valid_until),
        ):
            _aware(clock_value, f"R7 realization owner {label}")
        if not (
            self.period_start
            < self.period_end
            <= self.available_at
            <= self.recorded_at
            <= self.pit_as_of
            < self.valid_until
        ):
            raise ValueError("R7 realization owner PIT clocks are invalid")
        if type(self.members) is not tuple or not self.members:
            raise ValueError("R7 realization owner membership is incomplete")
        identities = tuple(
            (item.entry_id, item.observation_version, item.observation_id) for item in self.members
        )
        if identities != tuple(sorted(identities)) or len(identities) != len(set(identities)):
            raise ValueError("R7 realization owner members are not canonical and unique")
        if len({member.entry_id for member in self.members}) != len(self.members):
            raise ValueError("R7 realization owner contains duplicate forecast entries")
        for member in self.members:
            if type(member) is not R7ForecastRealizationMember:
                raise TypeError("R7 realization owner member type is invalid")
            member.__post_init__()
            if member.horizon_end != self.period_end:
                raise ValueError("R7 realization member horizon does not match period")
            if member.available_at > self.available_at or member.recorded_at > self.recorded_at:
                raise ValueError("R7 realization owner predates one of its members")
        expected_payload = hash_components(
            "r7-monitoring-realization-owner-payload.v1",
            self.period_hash,
            *(member.content_hash for member in self.members),
        )
        if self.payload_hash != expected_payload:
            raise ValueError("R7 realization owner payload seal mismatch")
        if self.content_hash != realization_owner_record_hash(self):
            raise ValueError("R7 realization owner content hash mismatch")

    def validated_copy(self) -> R7ForecastRealizationOwnerRecord:
        """Rebuild the independent owner evidence and all nested members."""

        self.__post_init__()
        return R7ForecastRealizationOwnerRecord(
            record_version=self.record_version,
            owner=self.owner,
            owner_record_id=self.owner_record_id,
            owner_record_version=self.owner_record_version,
            period_id=self.period_id,
            period_hash=self.period_hash,
            period_start=self.period_start,
            period_end=self.period_end,
            pit_as_of=self.pit_as_of,
            available_at=self.available_at,
            recorded_at=self.recorded_at,
            valid_until=self.valid_until,
            evidence_ref=self.evidence_ref,
            members=tuple(member.validated_copy() for member in self.members),
            payload_hash=self.payload_hash,
            content_hash=self.content_hash,
        )


def realization_owner_record_hash(value: R7ForecastRealizationOwnerRecord) -> str:
    """Recompute the full Forecast Ledger owner record seal."""

    return _realization_owner_hash(
        value.record_version,
        value.owner,
        value.owner_record_id,
        value.owner_record_version,
        value.period_id,
        value.period_hash,
        value.period_start,
        value.period_end,
        value.pit_as_of,
        value.available_at,
        value.recorded_at,
        value.valid_until,
        value.evidence_ref,
        value.members,
        value.payload_hash,
    )


def _realization_owner_hash(
    record_version: str,
    owner: str,
    owner_record_id: str,
    owner_record_version: str,
    period_id: str,
    period_hash: str,
    period_start: datetime,
    period_end: datetime,
    pit_as_of: datetime,
    available_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
    evidence_ref: str,
    members: tuple[R7ForecastRealizationMember, ...],
    payload_hash: str,
) -> str:
    return hash_components(
        record_version,
        owner,
        owner_record_id,
        owner_record_version,
        period_id,
        period_hash.lower(),
        _utc_text(period_start),
        _utc_text(period_end),
        _utc_text(pit_as_of),
        _utc_text(available_at),
        _utc_text(recorded_at),
        _utc_text(valid_until),
        evidence_ref,
        *(member.content_hash for member in members),
        payload_hash.lower(),
    )


@dataclass(frozen=True)
class R7ForecastRealizationFact:
    """Period-bound view of one independent owner-sealed realization record."""

    fact_version: str
    period_id: str
    period_hash: str
    period_start: datetime
    period_end: datetime
    owner_record: R7ForecastRealizationOwnerRecord
    content_hash: str

    @classmethod
    def from_owner_record(
        cls,
        *,
        period: R7MonitoringPeriodEntry,
        owner_record: R7ForecastRealizationOwnerRecord,
    ) -> R7ForecastRealizationFact:
        """Bind an independently supplied owner record to one exact period."""

        if type(period) is not R7MonitoringPeriodEntry:
            raise TypeError("R7 realization fact period type is invalid")
        if type(owner_record) is not R7ForecastRealizationOwnerRecord:
            raise TypeError("R7 realization fact owner record type is invalid")
        period.__post_init__()
        owner_copy = owner_record.validated_copy()
        values = (
            _REALIZATION_FACT_VERSION,
            period.period_id,
            period.content_hash,
            period.period_start,
            period.period_end,
            owner_copy,
        )
        return cls(*values, _realization_fact_hash(*values))

    @property
    def members(self) -> tuple[R7ForecastRealizationMember, ...]:
        """Expose immutable owner members for pure evaluation."""

        return self.owner_record.members

    def __post_init__(self) -> None:
        if self.fact_version != _REALIZATION_FACT_VERSION:
            raise ValueError("R7 realization fact version is unsupported")
        require_token(self.period_id, "R7 realization fact period_id", maximum=192)
        require_sha256(self.period_hash, "R7 realization fact period_hash")
        require_sha256(self.content_hash, "R7 realization fact content_hash")
        _aware(self.period_start, "R7 realization fact period_start")
        _aware(self.period_end, "R7 realization fact period_end")
        if type(self.owner_record) is not R7ForecastRealizationOwnerRecord:
            raise TypeError("R7 realization fact owner record type is invalid")
        self.owner_record.__post_init__()
        if (
            self.period_id,
            self.period_hash,
            self.period_start,
            self.period_end,
        ) != (
            self.owner_record.period_id,
            self.owner_record.period_hash,
            self.owner_record.period_start,
            self.owner_record.period_end,
        ):
            raise ValueError("R7 realization owner period substitution")
        if self.content_hash != realization_fact_hash(self):
            raise ValueError("R7 realization fact content hash mismatch")

    def validated_copy(self) -> R7ForecastRealizationFact:
        """Rebuild the fact without inventing calendar selectors."""

        self.__post_init__()
        return R7ForecastRealizationFact(
            fact_version=self.fact_version,
            period_id=self.period_id,
            period_hash=self.period_hash,
            period_start=self.period_start,
            period_end=self.period_end,
            owner_record=self.owner_record.validated_copy(),
            content_hash=self.content_hash,
        )


def realization_fact_hash(value: R7ForecastRealizationFact) -> str:
    """Recompute the period-to-owner binding seal."""

    return _realization_fact_hash(
        value.fact_version,
        value.period_id,
        value.period_hash,
        value.period_start,
        value.period_end,
        value.owner_record,
    )


def _realization_fact_hash(
    fact_version: str,
    period_id: str,
    period_hash: str,
    period_start: datetime,
    period_end: datetime,
    owner_record: R7ForecastRealizationOwnerRecord,
) -> str:
    return hash_components(
        fact_version,
        period_id,
        period_hash.lower(),
        _utc_text(period_start),
        _utc_text(period_end),
        owner_record.content_hash,
    )


def _matched_pairs(
    *,
    active: R7MonitoringActiveResult,
    period: R7MonitoringPeriodEntry,
    realization: R7ForecastRealizationFact,
) -> tuple[tuple[R7MonitoringPredictionMember, R7ForecastRealizationMember], ...]:
    if type(active) is not R7MonitoringActiveResult:
        raise TypeError("R7 monitoring active result type is invalid")
    if type(period) is not R7MonitoringPeriodEntry:
        raise TypeError("R7 monitoring period type is invalid")
    if type(realization) is not R7ForecastRealizationFact:
        raise TypeError("R7 monitoring realization type is invalid")
    active.validate_live()
    period.__post_init__()
    realization.__post_init__()
    if (
        realization.period_id,
        realization.period_hash,
        realization.period_start,
        realization.period_end,
    ) != (
        period.period_id,
        period.content_hash,
        period.period_start,
        period.period_end,
    ):
        raise ValueError("R7 realization period substitution")
    predictions = tuple(
        item
        for item in active.predictions
        if item.published_at < period.period_start and item.horizon_end == period.period_end
    )
    if not predictions:
        raise ValueError("R7 monitoring period has no strict pre-period forecast members")
    if any(
        item.horizon_end == period.period_end and item.published_at >= period.period_start
        for item in active.predictions
    ):
        raise ValueError("R7 monitoring contains a non-pre-period prediction")
    expected = tuple(
        (
            item.entry_id,
            item.observation_version,
            item.content_hash,
            item.forecast_group_id,
            item.scenario_revision_id,
            item.published_at,
            item.horizon_end,
        )
        for item in predictions
    )
    actual = tuple(
        (
            item.observation_id,
            item.observation_version,
            item.prediction_hash,
            item.forecast_group_id,
            item.scenario_revision_id,
            item.published_at,
            item.horizon_end,
        )
        for item in realization.members
    )
    if actual != expected:
        raise ValueError("R7 realization members do not match exact predictions")
    return tuple(zip(predictions, realization.members, strict=True))


def calculate_r7_forecast_outcome_coverage(
    *,
    active: R7MonitoringActiveResult,
    period: R7MonitoringPeriodEntry,
    realization: R7ForecastRealizationFact,
) -> Decimal:
    """Derive the exact resolved-or-invalidated denominator from owner members."""

    pairs = _matched_pairs(active=active, period=period, realization=realization)
    resolved = sum(member.realized is not None or member.invalidated for _, member in pairs)
    return Decimal(resolved) / Decimal(len(pairs))


def calculate_r7_probability_coverage(
    *,
    active: R7MonitoringActiveResult,
    period: R7MonitoringPeriodEntry,
    realization: R7ForecastRealizationFact,
    source: ScenarioProbabilitySource,
) -> Decimal:
    """Derive one source's exact usable-member coverage over the same denominator."""

    if type(source) is not ScenarioProbabilitySource:
        raise TypeError("R7 probability source is invalid")
    pairs = _matched_pairs(active=active, period=period, realization=realization)
    usable = 0
    for prediction, member in pairs:
        probability = (
            prediction.subjective_probability
            if source is ScenarioProbabilitySource.SUBJECTIVE
            else prediction.model_probability
        )
        if probability is not None and member.realized is not None:
            usable += 1
    return Decimal(usable) / Decimal(len(pairs))


def calculate_r7_brier_score(
    *,
    active: R7MonitoringActiveResult,
    period: R7MonitoringPeriodEntry,
    realization: R7ForecastRealizationFact,
    source: ScenarioProbabilitySource,
) -> Decimal | None:
    """Calculate one source-specific mean Brier score over exact usable members."""

    if type(source) is not ScenarioProbabilitySource:
        raise TypeError("R7 probability source is invalid")
    pairs = _matched_pairs(active=active, period=period, realization=realization)
    if any(member.realized is None for _, member in pairs):
        return None
    probabilities: tuple[Decimal | None, ...]
    if source is ScenarioProbabilitySource.SUBJECTIVE:
        source_versions = {
            prediction.subjective_probability_source_version for prediction, _ in pairs
        }
        if len(source_versions) != 1:
            raise ValueError("R7 subjective probability source versions are mixed")
        probabilities = tuple(prediction.subjective_probability for prediction, _ in pairs)
    else:
        model_fields = tuple(
            (
                prediction.model_probability,
                prediction.model_probability_source_version,
                prediction.model_promotion_decision_id,
            )
            for prediction, _ in pairs
        )
        if all(values[0] is None for values in model_fields):
            return None
        if any(values[0] is None for values in model_fields):
            raise ValueError("R7 model probability coverage is incomplete")
        if len({(values[1], values[2]) for values in model_fields}) != 1:
            raise ValueError("R7 model probability owner versions are mixed")
        probabilities = tuple(values[0] for values in model_fields)
    scores: list[Decimal] = []
    for probability, (_, outcome) in zip(probabilities, pairs, strict=True):
        assert probability is not None
        assert outcome.realized is not None
        realized = Decimal(1 if outcome.realized else 0)
        scores.append((probability - realized) ** 2)
    return sum(scores, start=Decimal("0")) / Decimal(len(scores))


@dataclass(frozen=True)
class R7PostPromotionMonitoringAssessment:
    """Research-only assessment whose incomplete roadmap evidence stays blocked."""

    assessment_id: str
    assessment_version: str
    result_id: str
    result_hash: str
    calendar_hash: str
    period_id: str
    realization_hash: str
    subjective_brier_score: Decimal | None
    model_brier_score: Decimal | None
    forecast_outcome_coverage: Decimal
    subjective_probability_coverage: Decimal
    model_probability_coverage: Decimal
    blocker_codes: tuple[R7MonitoringBlockerCode, ...]
    status: R7MonitoringStatus
    evaluated_at: datetime
    manual_retirement_review_required: bool
    automatic_retirement: bool
    trains_probability_model: bool
    publishes_model_probability: bool
    publishes_probability_current: bool
    produces_decision: bool
    executes_orders: bool
    research_only: bool
    must_not_use_for_decision: bool
    must_not_execute: bool
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        result_id: str,
        result_hash: str,
        calendar_hash: str,
        period_id: str,
        realization_hash: str,
        subjective_brier_score: Decimal | None,
        model_brier_score: Decimal | None,
        forecast_outcome_coverage: Decimal,
        subjective_probability_coverage: Decimal,
        model_probability_coverage: Decimal,
        blocker_codes: tuple[R7MonitoringBlockerCode, ...],
        threshold_breached: bool,
        falsification_detected: bool,
        evaluated_at: datetime,
    ) -> R7PostPromotionMonitoringAssessment:
        """Derive status and every safety flag rather than accepting caller flags."""

        canonical_blockers = tuple(sorted(set(blocker_codes), key=lambda item: item.value))
        status = derive_r7_monitoring_status(
            blocker_codes=canonical_blockers,
            threshold_breached=threshold_breached,
            falsification_detected=falsification_detected,
        )
        values = (
            _ASSESSMENT_VERSION,
            result_id,
            result_hash,
            calendar_hash,
            period_id,
            realization_hash,
            subjective_brier_score,
            model_brier_score,
            forecast_outcome_coverage,
            subjective_probability_coverage,
            model_probability_coverage,
            canonical_blockers,
            status,
            evaluated_at,
            status is R7MonitoringStatus.RETIREMENT_REVIEW_REQUIRED,
            False,
            False,
            False,
            False,
            False,
            False,
            True,
            True,
            True,
        )
        digest = _assessment_hash(*values)
        return cls(
            assessment_id=f"r7-monitoring-assessment:{digest[:24]}",
            assessment_version=values[0],
            result_id=values[1],
            result_hash=values[2],
            calendar_hash=values[3],
            period_id=values[4],
            realization_hash=values[5],
            subjective_brier_score=values[6],
            model_brier_score=values[7],
            forecast_outcome_coverage=values[8],
            subjective_probability_coverage=values[9],
            model_probability_coverage=values[10],
            blocker_codes=values[11],
            status=values[12],
            evaluated_at=values[13],
            manual_retirement_review_required=values[14],
            automatic_retirement=values[15],
            trains_probability_model=values[16],
            publishes_model_probability=values[17],
            publishes_probability_current=values[18],
            produces_decision=values[19],
            executes_orders=values[20],
            research_only=values[21],
            must_not_use_for_decision=values[22],
            must_not_execute=values[23],
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        require_token(self.assessment_id, "R7 monitoring assessment_id", maximum=192)
        if self.assessment_version != _ASSESSMENT_VERSION:
            raise ValueError("R7 monitoring assessment version is unsupported")
        require_token(self.result_id, "R7 monitoring assessment result_id", maximum=192)
        require_token(self.period_id, "R7 monitoring assessment period_id", maximum=192)
        for label, digest in (
            ("result_hash", self.result_hash),
            ("calendar_hash", self.calendar_hash),
            ("realization_hash", self.realization_hash),
            ("content_hash", self.content_hash),
        ):
            require_sha256(digest, f"R7 monitoring assessment {label}")
        for label, metric in (
            ("subjective_brier_score", self.subjective_brier_score),
            ("model_brier_score", self.model_brier_score),
            ("forecast_outcome_coverage", self.forecast_outcome_coverage),
            ("subjective_probability_coverage", self.subjective_probability_coverage),
            ("model_probability_coverage", self.model_probability_coverage),
        ):
            if metric is not None and (
                type(metric) is not Decimal
                or not metric.is_finite()
                or not Decimal("0") <= metric <= Decimal("1")
            ):
                raise ValueError(f"R7 monitoring {label} is invalid")
        if type(self.blocker_codes) is not tuple or any(
            type(item) is not R7MonitoringBlockerCode for item in self.blocker_codes
        ):
            raise TypeError("R7 monitoring blockers are invalid")
        if self.blocker_codes != tuple(
            sorted(set(self.blocker_codes), key=lambda item: item.value)
        ):
            raise ValueError("R7 monitoring blockers are not canonical")
        if type(self.status) is not R7MonitoringStatus:
            raise TypeError("R7 monitoring assessment status is invalid")
        _aware(self.evaluated_at, "R7 monitoring evaluated_at")
        strict_flags = (
            self.automatic_retirement is False
            and self.trains_probability_model is False
            and self.publishes_model_probability is False
            and self.publishes_probability_current is False
            and self.produces_decision is False
            and self.executes_orders is False
            and self.research_only is True
            and self.must_not_use_for_decision is True
            and self.must_not_execute is True
        )
        if not strict_flags:
            raise ValueError("R7 monitoring assessment must remain research-only")
        if self.manual_retirement_review_required != (
            self.status is R7MonitoringStatus.RETIREMENT_REVIEW_REQUIRED
        ):
            raise ValueError("R7 monitoring manual-review flag diverges from status")
        if self.content_hash != monitoring_assessment_hash(self):
            raise ValueError("R7 monitoring assessment content hash mismatch")


def derive_r7_monitoring_status(
    *,
    blocker_codes: tuple[R7MonitoringBlockerCode, ...],
    threshold_breached: bool,
    falsification_detected: bool,
) -> R7MonitoringStatus:
    """Apply fail-closed, manual-review, and ordinary breach precedence."""

    if type(blocker_codes) is not tuple or any(
        type(item) is not R7MonitoringBlockerCode for item in blocker_codes
    ):
        raise TypeError("R7 monitoring blockers are invalid")
    if type(threshold_breached) is not bool or type(falsification_detected) is not bool:
        raise TypeError("R7 monitoring status inputs must be exact booleans")
    if blocker_codes:
        return R7MonitoringStatus.BLOCKED
    if falsification_detected:
        return R7MonitoringStatus.RETIREMENT_REVIEW_REQUIRED
    if threshold_breached:
        return R7MonitoringStatus.BREACHED
    return R7MonitoringStatus.HEALTHY


def evaluate_r7_post_promotion_monitoring(
    *,
    active: R7MonitoringActiveResult,
    calendar: R7MonitoringPeriodCalendar,
    period: R7MonitoringPeriodEntry,
    realization: R7ForecastRealizationFact,
    evaluated_at: datetime,
    maximum_subjective_brier_score: Decimal,
    maximum_model_brier_score: Decimal,
    minimum_forecast_outcome_coverage: Decimal,
) -> R7PostPromotionMonitoringAssessment:
    """Evaluate proven metrics while absent roadmap owner evidence stays blocked."""

    if type(active) is not R7MonitoringActiveResult:
        raise TypeError("R7 monitoring active result type is invalid")
    if type(calendar) is not R7MonitoringPeriodCalendar:
        raise TypeError("R7 monitoring calendar type is invalid")
    if type(period) is not R7MonitoringPeriodEntry:
        raise TypeError("R7 monitoring period type is invalid")
    if type(realization) is not R7ForecastRealizationFact:
        raise TypeError("R7 monitoring realization type is invalid")
    active.validate_live()
    calendar.__post_init__()
    calendar.require_exact_member(period)
    realization.__post_init__()
    _aware(evaluated_at, "R7 monitoring evaluated_at")
    for label, threshold in (
        ("maximum subjective Brier", maximum_subjective_brier_score),
        ("maximum model Brier", maximum_model_brier_score),
        ("minimum forecast outcome coverage", minimum_forecast_outcome_coverage),
    ):
        if (
            type(threshold) is not Decimal
            or not threshold.is_finite()
            or not Decimal("0") <= threshold <= Decimal("1")
        ):
            raise ValueError(f"R7 {label} threshold is invalid")
    blockers: list[R7MonitoringBlockerCode] = []
    if not active.lifecycle_recorded_at <= evaluated_at < active.lifecycle_valid_until:
        blockers.append(R7MonitoringBlockerCode.ACTIVE_RESULT_INVALID)
    if calendar.recorded_at > period.period_start:
        blockers.append(R7MonitoringBlockerCode.CALENDAR_INVALID)
    owner_record = realization.owner_record
    if owner_record.recorded_at > evaluated_at or evaluated_at >= owner_record.valid_until:
        blockers.append(R7MonitoringBlockerCode.REALIZATION_FUTURE_OR_EXPIRED)
    coverage = calculate_r7_forecast_outcome_coverage(
        active=active,
        period=period,
        realization=realization,
    )
    subjective_coverage = calculate_r7_probability_coverage(
        active=active,
        period=period,
        realization=realization,
        source=ScenarioProbabilitySource.SUBJECTIVE,
    )
    model_coverage = calculate_r7_probability_coverage(
        active=active,
        period=period,
        realization=realization,
        source=ScenarioProbabilitySource.MODEL_INFERRED,
    )
    subjective = calculate_r7_brier_score(
        active=active,
        period=period,
        realization=realization,
        source=ScenarioProbabilitySource.SUBJECTIVE,
    )
    model = calculate_r7_brier_score(
        active=active,
        period=period,
        realization=realization,
        source=ScenarioProbabilitySource.MODEL_INFERRED,
    )
    if coverage < minimum_forecast_outcome_coverage or subjective is None:
        blockers.append(R7MonitoringBlockerCode.FORECAST_OUTCOME_INCOMPLETE)
    blockers.extend(
        (
            R7MonitoringBlockerCode.CALIBRATION_EVIDENCE_UNAVAILABLE,
            R7MonitoringBlockerCode.HISTORICAL_ANALOGY_EVIDENCE_UNAVAILABLE,
            R7MonitoringBlockerCode.PATH_EVIDENCE_UNAVAILABLE,
        )
    )
    threshold_breached = bool(
        (subjective is not None and subjective > maximum_subjective_brier_score)
        or (model is not None and model > maximum_model_brier_score)
        or coverage < minimum_forecast_outcome_coverage
    )
    falsification_detected = any(member.invalidated for member in realization.members)
    return R7PostPromotionMonitoringAssessment.create(
        result_id=active.result_id,
        result_hash=active.result_hash,
        calendar_hash=calendar.content_hash,
        period_id=period.period_id,
        realization_hash=realization.content_hash,
        subjective_brier_score=subjective,
        model_brier_score=model,
        forecast_outcome_coverage=coverage,
        subjective_probability_coverage=subjective_coverage,
        model_probability_coverage=model_coverage,
        blocker_codes=tuple(blockers),
        threshold_breached=threshold_breached,
        falsification_detected=falsification_detected,
        evaluated_at=evaluated_at,
    )


def monitoring_assessment_hash(value: R7PostPromotionMonitoringAssessment) -> str:
    """Recompute the complete assessment seal."""

    return _assessment_hash(
        value.assessment_version,
        value.result_id,
        value.result_hash,
        value.calendar_hash,
        value.period_id,
        value.realization_hash,
        value.subjective_brier_score,
        value.model_brier_score,
        value.forecast_outcome_coverage,
        value.subjective_probability_coverage,
        value.model_probability_coverage,
        value.blocker_codes,
        value.status,
        value.evaluated_at,
        value.manual_retirement_review_required,
        value.automatic_retirement,
        value.trains_probability_model,
        value.publishes_model_probability,
        value.publishes_probability_current,
        value.produces_decision,
        value.executes_orders,
        value.research_only,
        value.must_not_use_for_decision,
        value.must_not_execute,
    )


def _assessment_hash(
    assessment_version: str,
    result_id: str,
    result_hash: str,
    calendar_hash: str,
    period_id: str,
    realization_hash: str,
    subjective_brier_score: Decimal | None,
    model_brier_score: Decimal | None,
    forecast_outcome_coverage: Decimal,
    subjective_probability_coverage: Decimal,
    model_probability_coverage: Decimal,
    blocker_codes: tuple[R7MonitoringBlockerCode, ...],
    status: R7MonitoringStatus,
    evaluated_at: datetime,
    manual_retirement_review_required: bool,
    automatic_retirement: bool,
    trains_probability_model: bool,
    publishes_model_probability: bool,
    publishes_probability_current: bool,
    produces_decision: bool,
    executes_orders: bool,
    research_only: bool,
    must_not_use_for_decision: bool,
    must_not_execute: bool,
) -> str:
    return hash_components(
        assessment_version,
        result_id,
        result_hash.lower(),
        calendar_hash.lower(),
        period_id,
        realization_hash.lower(),
        _decimal_text(subjective_brier_score),
        _decimal_text(model_brier_score),
        _decimal_text(forecast_outcome_coverage),
        _decimal_text(subjective_probability_coverage),
        _decimal_text(model_probability_coverage),
        *(item.value for item in blocker_codes),
        status.value,
        _utc_text(evaluated_at),
        *(
            "true" if item else "false"
            for item in (
                manual_retirement_review_required,
                automatic_retirement,
                trains_probability_model,
                publishes_model_probability,
                publishes_probability_current,
                produces_decision,
                executes_orders,
                research_only,
                must_not_use_for_decision,
                must_not_execute,
            )
        ),
    )


__all__ = [
    "R7ForecastRealizationFact",
    "R7ForecastRealizationMember",
    "R7ForecastRealizationOwnerRecord",
    "R7MonitoringBlockerCode",
    "R7MonitoringStatus",
    "R7PostPromotionMonitoringAssessment",
    "calculate_r7_brier_score",
    "calculate_r7_forecast_outcome_coverage",
    "calculate_r7_probability_coverage",
    "derive_r7_monitoring_status",
    "evaluate_r7_post_promotion_monitoring",
    "monitoring_assessment_hash",
    "realization_fact_hash",
    "realization_member_hash",
    "realization_owner_record_hash",
]
