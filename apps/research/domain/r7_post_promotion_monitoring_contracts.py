"""Canonical owner projections and period contracts for R7 monitoring."""

from __future__ import annotations

from dataclasses import InitVar, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from apps.research.domain.r7_research_result_lifecycle import (
    R7ResultLifecycleEvent,
    R7ResultLifecycleStatus,
    derive_r7_result_lifecycle_state,
)
from apps.research.domain.r7_research_result_persistence import (
    PersistedR7ResearchResult,
)
from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
)
from apps.research.domain.scenario_research_hashing import (
    hash_components,
    require_sha256,
    require_token,
)

_ACTIVE_VERSION = "r7-monitoring-active-result.v1"
_LIFECYCLE_ATTESTATION_VERSION = "r7-lifecycle-stream-owner-evidence.v1"
_PREDICTION_VERSION = "r7-monitoring-prediction-member.v1"
_PERIOD_VERSION = "r7-monitoring-period.v1"
_CALENDAR_VERSION = "r7-monitoring-calendar.v1"
_MAX_PERIODS = 128
_ACTIVE_MINT_TOKEN = object()


def _aware(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be a timezone-aware datetime")
    return value


def _utc_text(value: datetime) -> str:
    return _aware(value, "timestamp").astimezone(UTC).isoformat()


def _uuid_text(value: UUID | None) -> str:
    return "" if value is None else str(value)


def _decimal_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("probability must be a finite Decimal")
    return format(value, "f")


@dataclass(frozen=True)
class R7MonitoringPredictionMember:
    """Pre-outcome projection of one exact Forecast Ledger observation."""

    prediction_version: str
    observation_version: str
    entry_id: str
    forecast_group_id: str
    scenario_revision_id: UUID
    scenario_set_revision_id: UUID | None
    subjective_probability: Decimal
    subjective_probability_source_version: str
    model_probability: Decimal | None
    model_probability_source_version: str | None
    model_promotion_decision_id: str | None
    pit_manifest_id: str
    pit_manifest_version: str
    pit_manifest_hash: str
    censoring_rule_version: str
    published_at: datetime
    horizon_end: datetime
    content_hash: str

    @classmethod
    def from_observation(
        cls,
        observation: ForecastLedgerOutcomeObservation,
    ) -> R7MonitoringPredictionMember:
        """Strip post-period outcome fields from a live-validated owner row."""

        if type(observation) is not ForecastLedgerOutcomeObservation:
            raise TypeError("R7 monitoring prediction requires an exact forecast row")
        observation.__post_init__()
        binding = observation.binding
        values = (
            _PREDICTION_VERSION,
            observation.observation_version,
            observation.entry_id,
            observation.forecast_group_id,
            binding.scenario_revision_id,
            binding.scenario_set_revision_id,
            binding.subjective_probability,
            binding.subjective_probability_source_version,
            binding.model_probability,
            binding.model_probability_source_version,
            binding.model_promotion_decision_id,
            observation.pit_manifest_id,
            observation.pit_manifest_version,
            observation.pit_manifest_hash.lower(),
            observation.censoring_rule_version,
            observation.published_at,
            observation.horizon_end,
        )
        return cls(*values, _prediction_hash(*values))

    def __post_init__(self) -> None:
        if self.prediction_version != _PREDICTION_VERSION:
            raise ValueError("R7 monitoring prediction version is unsupported")
        for label, value in (
            ("observation_version", self.observation_version),
            ("entry_id", self.entry_id),
            ("forecast_group_id", self.forecast_group_id),
            (
                "subjective_probability_source_version",
                self.subjective_probability_source_version,
            ),
            ("pit_manifest_id", self.pit_manifest_id),
            ("pit_manifest_version", self.pit_manifest_version),
            ("censoring_rule_version", self.censoring_rule_version),
        ):
            require_token(value, f"R7 monitoring prediction {label}", maximum=192)
        if type(self.scenario_revision_id) is not UUID:
            raise TypeError("R7 monitoring prediction scenario revision is invalid")
        if (
            self.scenario_set_revision_id is not None
            and type(self.scenario_set_revision_id) is not UUID
        ):
            raise TypeError("R7 monitoring prediction scenario-set revision is invalid")
        if (
            type(self.subjective_probability) is not Decimal
            or not self.subjective_probability.is_finite()
            or not Decimal("0") <= self.subjective_probability <= Decimal("1")
        ):
            raise ValueError("R7 subjective probability is invalid")
        model_fields = (
            self.model_probability,
            self.model_probability_source_version,
            self.model_promotion_decision_id,
        )
        if any(value is None for value in model_fields) and not all(
            value is None for value in model_fields
        ):
            raise ValueError("R7 model probability projection is incomplete")
        if self.model_probability is not None:
            if (
                type(self.model_probability) is not Decimal
                or not self.model_probability.is_finite()
                or not Decimal("0") <= self.model_probability <= Decimal("1")
            ):
                raise ValueError("R7 model probability is invalid")
            assert self.model_probability_source_version is not None
            assert self.model_promotion_decision_id is not None
            require_token(
                self.model_probability_source_version,
                "R7 model probability source version",
                maximum=192,
            )
            require_token(
                self.model_promotion_decision_id,
                "R7 model promotion decision",
                maximum=192,
            )
        require_sha256(self.pit_manifest_hash, "R7 prediction PIT manifest hash")
        _aware(self.published_at, "R7 prediction published_at")
        _aware(self.horizon_end, "R7 prediction horizon_end")
        if self.published_at >= self.horizon_end:
            raise ValueError("R7 monitoring prediction horizon is invalid")
        require_sha256(self.content_hash, "R7 monitoring prediction content_hash")
        if self.content_hash != prediction_member_hash(self):
            raise ValueError("R7 monitoring prediction content hash mismatch")


def prediction_member_hash(value: R7MonitoringPredictionMember) -> str:
    """Recompute one outcome-free prediction seal."""

    return _prediction_hash(
        value.prediction_version,
        value.observation_version,
        value.entry_id,
        value.forecast_group_id,
        value.scenario_revision_id,
        value.scenario_set_revision_id,
        value.subjective_probability,
        value.subjective_probability_source_version,
        value.model_probability,
        value.model_probability_source_version,
        value.model_promotion_decision_id,
        value.pit_manifest_id,
        value.pit_manifest_version,
        value.pit_manifest_hash,
        value.censoring_rule_version,
        value.published_at,
        value.horizon_end,
    )


def _prediction_hash(
    prediction_version: str,
    observation_version: str,
    entry_id: str,
    forecast_group_id: str,
    scenario_revision_id: UUID,
    scenario_set_revision_id: UUID | None,
    subjective_probability: Decimal,
    subjective_probability_source_version: str,
    model_probability: Decimal | None,
    model_probability_source_version: str | None,
    model_promotion_decision_id: str | None,
    pit_manifest_id: str,
    pit_manifest_version: str,
    pit_manifest_hash: str,
    censoring_rule_version: str,
    published_at: datetime,
    horizon_end: datetime,
) -> str:
    return hash_components(
        prediction_version,
        observation_version,
        entry_id,
        forecast_group_id,
        str(scenario_revision_id),
        _uuid_text(scenario_set_revision_id),
        _decimal_text(subjective_probability),
        subjective_probability_source_version,
        _decimal_text(model_probability),
        model_probability_source_version or "",
        model_promotion_decision_id or "",
        pit_manifest_id,
        pit_manifest_version,
        pit_manifest_hash.lower(),
        censoring_rule_version,
        _utc_text(published_at),
        _utc_text(horizon_end),
    )


@dataclass(frozen=True)
class R7LifecycleStreamOwnerEvidence:
    """Research-owned exact stream-head evidence supplied independently of events."""

    attestation_id: str
    attestation_version: str
    owner: str
    result_id: str
    result_version: str
    result_hash: str
    event_count: int
    head_event_id: str
    head_event_version: str
    head_event_hash: str
    recorded_at: datetime
    valid_until: datetime
    evidence_ref: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        attestation_id: str,
        attestation_version: str,
        owner: str,
        lifecycle_stream: tuple[R7ResultLifecycleEvent, ...],
        recorded_at: datetime,
        valid_until: datetime,
        evidence_ref: str,
    ) -> R7LifecycleStreamOwnerEvidence:
        """Seal an owner-supplied complete stream identity without changing it."""

        if type(lifecycle_stream) is not tuple or not lifecycle_stream:
            raise ValueError("R7 lifecycle owner evidence requires a complete stream")
        if any(type(event) is not R7ResultLifecycleEvent for event in lifecycle_stream):
            raise TypeError("R7 lifecycle owner evidence contains an invalid event")
        for event in lifecycle_stream:
            event.__post_init__()
        head = lifecycle_stream[-1]
        result_ref = head.result_ref
        values = (
            attestation_id,
            attestation_version,
            owner,
            result_ref.result_id,
            result_ref.result_version,
            result_ref.content_hash,
            len(lifecycle_stream),
            head.event_id,
            head.event_version,
            head.content_hash,
            recorded_at,
            valid_until,
            evidence_ref,
        )
        return cls(*values, _lifecycle_owner_evidence_hash(*values))

    def __post_init__(self) -> None:
        require_token(self.attestation_id, "R7 lifecycle attestation_id", maximum=192)
        if self.attestation_version != _LIFECYCLE_ATTESTATION_VERSION:
            raise ValueError("R7 lifecycle attestation version is unsupported")
        if self.owner != "research":
            raise ValueError("R7 lifecycle attestation owner must be research")
        for label, value in (
            ("result_id", self.result_id),
            ("result_version", self.result_version),
            ("head_event_id", self.head_event_id),
            ("head_event_version", self.head_event_version),
            ("evidence_ref", self.evidence_ref),
        ):
            require_token(value, f"R7 lifecycle attestation {label}", maximum=300)
        require_sha256(self.result_hash, "R7 lifecycle attestation result_hash")
        require_sha256(self.head_event_hash, "R7 lifecycle attestation head_event_hash")
        require_sha256(self.content_hash, "R7 lifecycle attestation content_hash")
        if type(self.event_count) is not int or self.event_count < 1:
            raise ValueError("R7 lifecycle attestation event count is invalid")
        _aware(self.recorded_at, "R7 lifecycle attestation recorded_at")
        _aware(self.valid_until, "R7 lifecycle attestation valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("R7 lifecycle attestation is already expired")
        if self.content_hash != lifecycle_owner_evidence_hash(self):
            raise ValueError("R7 lifecycle attestation content hash mismatch")

    def validate_stream(
        self,
        lifecycle_stream: tuple[R7ResultLifecycleEvent, ...],
    ) -> None:
        """Verify exact count, result selector, and head identity against live events."""

        self.__post_init__()
        if type(lifecycle_stream) is not tuple or not lifecycle_stream:
            raise ValueError("R7 lifecycle attestation stream is incomplete")
        if any(type(event) is not R7ResultLifecycleEvent for event in lifecycle_stream):
            raise TypeError("R7 lifecycle attestation stream contains an invalid event")
        for event in lifecycle_stream:
            event.__post_init__()
        head = lifecycle_stream[-1]
        actual = (
            len(lifecycle_stream),
            head.result_ref.result_id,
            head.result_ref.result_version,
            head.result_ref.content_hash,
            head.event_id,
            head.event_version,
            head.content_hash,
        )
        expected = (
            self.event_count,
            self.result_id,
            self.result_version,
            self.result_hash,
            self.head_event_id,
            self.head_event_version,
            self.head_event_hash,
        )
        if actual != expected:
            raise ValueError("R7 lifecycle stream does not match exact owner attestation")
        if head.recorded_at > self.recorded_at:
            raise ValueError("R7 lifecycle attestation predates its exact head")


def lifecycle_owner_evidence_hash(value: R7LifecycleStreamOwnerEvidence) -> str:
    """Recompute the full owner stream attestation seal."""

    return _lifecycle_owner_evidence_hash(
        value.attestation_id,
        value.attestation_version,
        value.owner,
        value.result_id,
        value.result_version,
        value.result_hash,
        value.event_count,
        value.head_event_id,
        value.head_event_version,
        value.head_event_hash,
        value.recorded_at,
        value.valid_until,
        value.evidence_ref,
    )


def _lifecycle_owner_evidence_hash(
    attestation_id: str,
    attestation_version: str,
    owner: str,
    result_id: str,
    result_version: str,
    result_hash: str,
    event_count: int,
    head_event_id: str,
    head_event_version: str,
    head_event_hash: str,
    recorded_at: datetime,
    valid_until: datetime,
    evidence_ref: str,
) -> str:
    return hash_components(
        attestation_version,
        attestation_id,
        owner,
        result_id,
        result_version,
        result_hash.lower(),
        str(event_count),
        head_event_id,
        head_event_version,
        head_event_hash.lower(),
        _utc_text(recorded_at),
        _utc_text(valid_until),
        evidence_ref,
    )


@dataclass(frozen=True)
class R7MonitoringActiveResult:
    """Exact result plus a fully replayed, currently promoted lifecycle head."""

    active_version: str
    result_id: str
    result_version: str
    result_hash: str
    input_receipt_hash: str
    scope_hash: str
    calibration_hash: str
    analogy_hash: str
    path_hash: str
    lifecycle_attestation_id: str
    lifecycle_attestation_version: str
    lifecycle_attestation_hash: str
    lifecycle_event_count: int
    lifecycle_sequence: int
    lifecycle_head_event_id: str
    lifecycle_head_event_version: str
    lifecycle_head_hash: str
    promoted_at: datetime
    lifecycle_recorded_at: datetime
    lifecycle_valid_until: datetime
    predictions: tuple[R7MonitoringPredictionMember, ...]
    content_hash: str
    _mint_token: InitVar[object | None] = None

    @classmethod
    def from_owner_graph(
        cls,
        *,
        result: PersistedR7ResearchResult,
        lifecycle_stream: tuple[R7ResultLifecycleEvent, ...],
        lifecycle_owner_evidence: R7LifecycleStreamOwnerEvidence,
    ) -> R7MonitoringActiveResult:
        """Replay the complete stream and project only pre-outcome forecast fields."""

        if type(result) is not PersistedR7ResearchResult:
            raise TypeError("R7 monitoring result owner object is invalid")
        result.__post_init__()
        if type(lifecycle_owner_evidence) is not R7LifecycleStreamOwnerEvidence:
            raise TypeError("R7 monitoring lifecycle owner evidence is invalid")
        if type(lifecycle_stream) is not tuple or not lifecycle_stream:
            raise ValueError("R7 monitoring lifecycle stream is incomplete")
        if any(type(item) is not R7ResultLifecycleEvent for item in lifecycle_stream):
            raise TypeError("R7 monitoring lifecycle stream contains an invalid event")
        lifecycle_owner_evidence.validate_stream(lifecycle_stream)
        for event in lifecycle_stream:
            event.__post_init__()
        if tuple(event.sequence for event in lifecycle_stream) != tuple(
            range(1, len(lifecycle_stream) + 1)
        ):
            raise ValueError("R7 monitoring lifecycle stream is not canonical")
        state = derive_r7_result_lifecycle_state(
            lifecycle_stream,
            evaluated_at=lifecycle_owner_evidence.recorded_at,
        )
        if state.status is not R7ResultLifecycleStatus.PROMOTED:
            raise ValueError("R7 monitoring lifecycle is not currently promoted")
        expected_ref = (
            result.result_id,
            result.result_version,
            result.content_hash,
        )
        actual_ref = (
            state.result_ref.result_id,
            state.result_ref.result_version,
            state.result_ref.content_hash,
        )
        if actual_ref != expected_ref:
            raise ValueError("R7 monitoring lifecycle result substitution")
        if result.recorded_at > state.promoted_at:
            raise ValueError("R7 monitoring Promotion predates its result")
        predictions = tuple(
            R7MonitoringPredictionMember.from_observation(observation)
            for observation in result.evidence_graph.forecast_observations
        )
        if not predictions:
            raise ValueError("R7 monitoring active result has no forecast predictions")
        values = (
            _ACTIVE_VERSION,
            result.result_id,
            result.result_version,
            result.content_hash,
            result.input_receipt.content_hash,
            result.input_receipt.scope_content_hash,
            result.calibration.content_hash,
            result.historical_analogy.content_hash,
            result.path_research.content_hash,
            lifecycle_owner_evidence.attestation_id,
            lifecycle_owner_evidence.attestation_version,
            lifecycle_owner_evidence.content_hash,
            lifecycle_owner_evidence.event_count,
            state.sequence,
            lifecycle_owner_evidence.head_event_id,
            lifecycle_owner_evidence.head_event_version,
            state.head_event_hash,
            state.promoted_at,
            lifecycle_owner_evidence.recorded_at,
            lifecycle_owner_evidence.valid_until,
            predictions,
        )
        return cls(
            *values,
            _active_hash(*values),
            _mint_token=_ACTIVE_MINT_TOKEN,
        )

    @staticmethod
    def prediction_hash_from_observation(
        observation: ForecastLedgerOutcomeObservation,
    ) -> str:
        """Return the outcome-free hash used by active monitoring."""

        return R7MonitoringPredictionMember.from_observation(observation).content_hash

    def __post_init__(self, _mint_token: object | None) -> None:
        if _mint_token is not _ACTIVE_MINT_TOKEN:
            raise TypeError("R7 monitoring active result must be minted from owner graph")
        self._validate_live()

    def validate_live(self) -> None:
        """Recheck all top-level and nested seals after owner-graph minting."""

        self._validate_live()

    def _validate_live(self) -> None:
        if self.active_version != _ACTIVE_VERSION:
            raise ValueError("R7 monitoring active-result version is unsupported")
        require_token(self.result_id, "R7 monitoring result_id", maximum=192)
        require_token(self.result_version, "R7 monitoring result_version", maximum=192)
        for label, digest in (
            ("result_hash", self.result_hash),
            ("input_receipt_hash", self.input_receipt_hash),
            ("scope_hash", self.scope_hash),
            ("calibration_hash", self.calibration_hash),
            ("analogy_hash", self.analogy_hash),
            ("path_hash", self.path_hash),
            ("lifecycle_attestation_hash", self.lifecycle_attestation_hash),
            ("lifecycle_head_hash", self.lifecycle_head_hash),
            ("content_hash", self.content_hash),
        ):
            require_sha256(digest, f"R7 monitoring {label}")
        for label, value in (
            ("lifecycle_attestation_id", self.lifecycle_attestation_id),
            ("lifecycle_attestation_version", self.lifecycle_attestation_version),
            ("lifecycle_head_event_id", self.lifecycle_head_event_id),
            ("lifecycle_head_event_version", self.lifecycle_head_event_version),
        ):
            require_token(value, f"R7 monitoring {label}", maximum=192)
        if self.lifecycle_attestation_version != _LIFECYCLE_ATTESTATION_VERSION:
            raise ValueError("R7 monitoring lifecycle attestation version is unsupported")
        if type(self.lifecycle_event_count) is not int or self.lifecycle_event_count < 1:
            raise ValueError("R7 monitoring lifecycle event count is invalid")
        if type(self.lifecycle_sequence) is not int or self.lifecycle_sequence < 1:
            raise ValueError("R7 monitoring lifecycle sequence is invalid")
        if self.lifecycle_event_count != self.lifecycle_sequence:
            raise ValueError("R7 monitoring lifecycle count and sequence diverge")
        _aware(self.promoted_at, "R7 monitoring promoted_at")
        _aware(self.lifecycle_recorded_at, "R7 monitoring lifecycle_recorded_at")
        _aware(self.lifecycle_valid_until, "R7 monitoring lifecycle_valid_until")
        if not self.promoted_at <= self.lifecycle_recorded_at < self.lifecycle_valid_until:
            raise ValueError("R7 monitoring lifecycle clocks are invalid")
        if type(self.predictions) is not tuple or not self.predictions:
            raise ValueError("R7 monitoring prediction projection is empty")
        identities = tuple((item.entry_id, item.observation_version) for item in self.predictions)
        if identities != tuple(sorted(identities)) or len(identities) != len(set(identities)):
            raise ValueError("R7 monitoring predictions are not canonical and unique")
        for prediction in self.predictions:
            if type(prediction) is not R7MonitoringPredictionMember:
                raise TypeError("R7 monitoring prediction member type is invalid")
            prediction.__post_init__()
        if self.content_hash != active_result_hash(self):
            raise ValueError("R7 monitoring active-result content hash mismatch")


def active_result_hash(value: R7MonitoringActiveResult) -> str:
    """Recompute the active owner-graph projection seal."""

    return _active_hash(
        value.active_version,
        value.result_id,
        value.result_version,
        value.result_hash,
        value.input_receipt_hash,
        value.scope_hash,
        value.calibration_hash,
        value.analogy_hash,
        value.path_hash,
        value.lifecycle_attestation_id,
        value.lifecycle_attestation_version,
        value.lifecycle_attestation_hash,
        value.lifecycle_event_count,
        value.lifecycle_sequence,
        value.lifecycle_head_event_id,
        value.lifecycle_head_event_version,
        value.lifecycle_head_hash,
        value.promoted_at,
        value.lifecycle_recorded_at,
        value.lifecycle_valid_until,
        value.predictions,
    )


def _active_hash(
    active_version: str,
    result_id: str,
    result_version: str,
    result_hash: str,
    input_receipt_hash: str,
    scope_hash: str,
    calibration_hash: str,
    analogy_hash: str,
    path_hash: str,
    lifecycle_attestation_id: str,
    lifecycle_attestation_version: str,
    lifecycle_attestation_hash: str,
    lifecycle_event_count: int,
    lifecycle_sequence: int,
    lifecycle_head_event_id: str,
    lifecycle_head_event_version: str,
    lifecycle_head_hash: str,
    promoted_at: datetime,
    lifecycle_recorded_at: datetime,
    lifecycle_valid_until: datetime,
    predictions: tuple[R7MonitoringPredictionMember, ...],
) -> str:
    return hash_components(
        active_version,
        result_id,
        result_version,
        result_hash.lower(),
        input_receipt_hash.lower(),
        scope_hash.lower(),
        calibration_hash.lower(),
        analogy_hash.lower(),
        path_hash.lower(),
        lifecycle_attestation_id,
        lifecycle_attestation_version,
        lifecycle_attestation_hash.lower(),
        str(lifecycle_event_count),
        str(lifecycle_sequence),
        lifecycle_head_event_id,
        lifecycle_head_event_version,
        lifecycle_head_hash.lower(),
        _utc_text(promoted_at),
        _utc_text(lifecycle_recorded_at),
        _utc_text(lifecycle_valid_until),
        *(item.content_hash for item in predictions),
    )


@dataclass(frozen=True)
class R7MonitoringPeriodEntry:
    """One content-addressed half-open monitoring period."""

    period_id: str
    period_version: str
    calendar_id: str
    calendar_version: str
    period_start: datetime
    period_end: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        calendar_id: str,
        calendar_version: str,
        period_start: datetime,
        period_end: datetime,
    ) -> R7MonitoringPeriodEntry:
        """Derive identity from the complete calendar member."""

        digest = _period_hash(
            _PERIOD_VERSION,
            calendar_id,
            calendar_version,
            period_start,
            period_end,
        )
        return cls(
            period_id=f"r7-monitoring-period:{digest[:24]}",
            period_version=_PERIOD_VERSION,
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            period_start=period_start,
            period_end=period_end,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        require_token(self.period_id, "R7 monitoring period_id", maximum=192)
        if self.period_version != _PERIOD_VERSION:
            raise ValueError("R7 monitoring period version is unsupported")
        require_token(self.calendar_id, "R7 monitoring calendar_id", maximum=192)
        require_token(
            self.calendar_version,
            "R7 monitoring calendar_version",
            maximum=192,
        )
        _aware(self.period_start, "R7 monitoring period_start")
        _aware(self.period_end, "R7 monitoring period_end")
        if self.period_start >= self.period_end:
            raise ValueError("R7 monitoring period must be a non-empty half-open interval")
        require_sha256(self.content_hash, "R7 monitoring period content_hash")
        expected = period_entry_hash(self)
        if self.content_hash != expected or self.period_id != (
            f"r7-monitoring-period:{expected[:24]}"
        ):
            raise ValueError("R7 monitoring period identity or hash mismatch")


def period_entry_hash(value: R7MonitoringPeriodEntry) -> str:
    """Recompute one exact period-member seal."""

    return _period_hash(
        value.period_version,
        value.calendar_id,
        value.calendar_version,
        value.period_start,
        value.period_end,
    )


def _period_hash(
    period_version: str,
    calendar_id: str,
    calendar_version: str,
    period_start: datetime,
    period_end: datetime,
) -> str:
    return hash_components(
        period_version,
        calendar_id,
        calendar_version,
        _utc_text(period_start),
        _utc_text(period_end),
    )


@dataclass(frozen=True)
class R7MonitoringPeriodCalendar:
    """Complete contiguous calendar; no missing member may be synthesized."""

    calendar_id: str
    calendar_version: str
    periods: tuple[R7MonitoringPeriodEntry, ...]
    recorded_at: datetime
    valid_from: datetime
    valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        calendar_id: str,
        calendar_version: str,
        periods: tuple[R7MonitoringPeriodEntry, ...],
        recorded_at: datetime,
        valid_from: datetime,
        valid_until: datetime,
    ) -> R7MonitoringPeriodCalendar:
        """Seal already-declared exact membership without filling gaps."""

        values = (
            calendar_id,
            calendar_version,
            periods,
            recorded_at,
            valid_from,
            valid_until,
        )
        return cls(*values, _calendar_hash(*values))

    def __post_init__(self) -> None:
        require_token(self.calendar_id, "R7 calendar_id", maximum=192)
        require_token(self.calendar_version, "R7 calendar_version", maximum=192)
        if type(self.periods) is not tuple or not 1 <= len(self.periods) <= _MAX_PERIODS:
            raise ValueError("R7 monitoring calendar membership is incomplete")
        previous_end: datetime | None = None
        for period in self.periods:
            if type(period) is not R7MonitoringPeriodEntry:
                raise TypeError("R7 monitoring calendar member is invalid")
            period.__post_init__()
            if (period.calendar_id, period.calendar_version) != (
                self.calendar_id,
                self.calendar_version,
            ):
                raise ValueError("R7 monitoring calendar member substitution")
            if previous_end is not None and period.period_start != previous_end:
                raise ValueError("R7 monitoring calendar is not contiguous")
            previous_end = period.period_end
        _aware(self.recorded_at, "R7 monitoring calendar recorded_at")
        _aware(self.valid_from, "R7 monitoring calendar valid_from")
        _aware(self.valid_until, "R7 monitoring calendar valid_until")
        if self.recorded_at > self.valid_from:
            raise ValueError("R7 monitoring calendar was not recorded before use")
        if self.periods[0].period_start != self.valid_from:
            raise ValueError("R7 monitoring calendar does not start at valid_from")
        if self.periods[-1].period_end != self.valid_until:
            raise ValueError("R7 monitoring calendar does not end at valid_until")
        require_sha256(self.content_hash, "R7 monitoring calendar content_hash")
        if self.content_hash != monitoring_calendar_hash(self):
            raise ValueError("R7 monitoring calendar content hash mismatch")

    def require_exact_member(
        self,
        period: R7MonitoringPeriodEntry,
    ) -> R7MonitoringPeriodEntry:
        """Return one live exact member or reject an alias/replacement."""

        self.__post_init__()
        if type(period) is not R7MonitoringPeriodEntry:
            raise TypeError("R7 monitoring calendar candidate type is invalid")
        period.__post_init__()
        matches = tuple(item for item in self.periods if item.period_id == period.period_id)
        if len(matches) != 1 or matches[0] != period:
            raise ValueError("R7 monitoring period is not an exact calendar member")
        return matches[0]


def monitoring_calendar_hash(value: R7MonitoringPeriodCalendar) -> str:
    """Recompute the complete ordered calendar seal."""

    return _calendar_hash(
        value.calendar_id,
        value.calendar_version,
        value.periods,
        value.recorded_at,
        value.valid_from,
        value.valid_until,
    )


def _calendar_hash(
    calendar_id: str,
    calendar_version: str,
    periods: tuple[R7MonitoringPeriodEntry, ...],
    recorded_at: datetime,
    valid_from: datetime,
    valid_until: datetime,
) -> str:
    return hash_components(
        _CALENDAR_VERSION,
        calendar_id,
        calendar_version,
        *(period.content_hash for period in periods),
        _utc_text(recorded_at),
        _utc_text(valid_from),
        _utc_text(valid_until),
    )


__all__ = [
    "R7LifecycleStreamOwnerEvidence",
    "R7MonitoringActiveResult",
    "R7MonitoringPeriodCalendar",
    "R7MonitoringPeriodEntry",
    "R7MonitoringPredictionMember",
    "active_result_hash",
    "lifecycle_owner_evidence_hash",
    "monitoring_calendar_hash",
    "period_entry_hash",
    "prediction_member_hash",
]
