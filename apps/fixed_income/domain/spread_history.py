"""PIT historical spread percentile contracts for R5 fixed-income research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from apps.fixed_income.domain.evidence import (
    EvidenceRole,
    ExactEvidence,
    canonical_hash,
    require_aware,
    require_finite,
    require_sha256,
    require_token,
)


class SpreadObservationState(StrEnum):
    """Quality state of one versioned spread observation."""

    OBSERVED = "observed"
    ESTIMATED = "estimated"
    MISSING = "missing"


class SpreadTieConvention(StrEnum):
    """Versioned percentile tie convention."""

    MID_RANK = "mid_rank"
    STRICT_LESS = "strict_less"
    WEAK_LESS_EQUAL = "weak_less_equal"


class TargetSampleConvention(StrEnum):
    """Whether the target/current point participates in the reference sample."""

    EXCLUDED = "excluded"


class RevisionSelection(StrEnum):
    """PIT revision selection rule for a calendar period."""

    LATEST_AVAILABLE_AT_CUTOFF = "latest_available_at_cutoff"


class SpreadAssessmentStatus(StrEnum):
    """Availability state for one research-only percentile assessment."""

    AVAILABLE = "available"
    BLOCKED = "blocked"


class SpreadBlockerCode(StrEnum):
    """Stable fail-closed reasons for historical spread percentiles."""

    INPUT_HASH_MISMATCH = "fixed_income.spread.input.hash_mismatch"
    POLICY_INACTIVE = "fixed_income.spread.policy.inactive"
    CALENDAR_ROLE_MISMATCH = "fixed_income.spread.calendar.role_mismatch"
    CALENDAR_FROM_FUTURE = "fixed_income.spread.calendar.from_future"
    CALENDAR_STALE = "fixed_income.spread.calendar.stale"
    PUBLICATION_ROLE_MISMATCH = "fixed_income.spread.publication.role_mismatch"
    EVIDENCE_FROM_FUTURE = "fixed_income.spread.evidence.from_future"
    EVIDENCE_STALE = "fixed_income.spread.evidence.stale"
    SCOPE_MISMATCH = "fixed_income.spread.scope.mismatch"
    DEFINITION_MISMATCH = "fixed_income.spread.definition.mismatch"
    CURRENCY_MISMATCH = "fixed_income.spread.currency.mismatch"
    CURVE_ROLE_MISMATCH = "fixed_income.spread.curve_role.mismatch"
    PERIOD_OUTSIDE_CALENDAR = "fixed_income.spread.period.outside_calendar"
    PERIOD_DUPLICATE_REVISION = "fixed_income.spread.period.duplicate_revision"
    TARGET_IN_REFERENCE_SAMPLE = "fixed_income.spread.target.in_reference_sample"
    ESTIMATED_NOT_ALLOWED = "fixed_income.spread.estimated.not_allowed"
    EMPTY_REFERENCE_SAMPLE = "fixed_income.spread.reference.empty"
    MINIMUM_SAMPLE_NOT_MET = "fixed_income.spread.reference.minimum_sample"
    COVERAGE_INSUFFICIENT = "fixed_income.spread.reference.coverage"
    RELEASE_LAG_EXCEEDED = "fixed_income.spread.release_lag.exceeded"
    LOOKBACK_CUTOFF_INVALID = "fixed_income.spread.lookback.cutoff_invalid"
    TARGET_PERIOD_IN_REFERENCE = "fixed_income.spread.target.period_in_reference"
    TARGET_MISSING = "fixed_income.spread.target.missing"
    TARGET_ESTIMATED_NOT_ALLOWED = "fixed_income.spread.target.estimated_not_allowed"
    REVISION_CHRONOLOGY_INVALID = "fixed_income.spread.revision.chronology_invalid"


@dataclass(frozen=True)
class SpreadBlocker:
    """Stable blocker with bounded diagnostic detail."""

    code: SpreadBlockerCode
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, SpreadBlockerCode):
            raise ValueError("SpreadBlocker.code is invalid")
        require_token(self.detail.replace(" ", "_"), "SpreadBlocker.detail", maximum=240)


@dataclass(frozen=True)
class CalendarPeriod:
    """One expected observation period supplied by authoritative calendar evidence."""

    period_id: str
    starts_at: datetime
    ends_at: datetime
    expected_release_at: datetime

    def __post_init__(self) -> None:
        require_token(self.period_id, "CalendarPeriod.period_id")
        require_aware(self.starts_at, "CalendarPeriod.starts_at")
        require_aware(self.ends_at, "CalendarPeriod.ends_at")
        require_aware(self.expected_release_at, "CalendarPeriod.expected_release_at")
        if self.ends_at <= self.starts_at:
            raise ValueError("CalendarPeriod.ends_at must follow starts_at")
        if self.expected_release_at < self.ends_at:
            raise ValueError("expected_release_at cannot precede period end")


@dataclass(frozen=True)
class ExpectedObservationCalendar:
    """Exact owner-supplied denominator for spread-history coverage."""

    scope_id: str
    evidence: ExactEvidence
    periods: tuple[CalendarPeriod, ...]

    def __post_init__(self) -> None:
        require_token(self.scope_id, "ExpectedObservationCalendar.scope_id")
        if self.evidence.role is not EvidenceRole.CALENDAR:
            raise ValueError("expected observation calendar requires calendar evidence")
        if self.evidence.subject_id != self.scope_id:
            raise ValueError("calendar owner evidence subject must match calendar scope")
        if self.evidence.curve_role != "spread_observation_calendar":
            raise ValueError("calendar evidence semantic role is invalid")
        if not self.periods:
            raise ValueError("expected observation calendar requires periods")
        period_ids = tuple(period.period_id for period in self.periods)
        if len(period_ids) != len(set(period_ids)):
            raise ValueError("calendar period ids cannot repeat")
        ordered = tuple(sorted(self.periods, key=lambda period: period.starts_at))
        if ordered != self.periods:
            raise ValueError("calendar periods must be ordered by starts_at")
        for previous, current in zip(self.periods, self.periods[1:], strict=False):
            if current.starts_at < previous.ends_at:
                raise ValueError("calendar periods cannot overlap")
        if self.evidence.content_hash != self.raw_manifest_hash:
            raise ValueError("calendar content hash must attest every expected period")

    @property
    def raw_manifest_hash(self) -> str:
        """Hash raw calendar content without recursively including its owner seal."""

        return canonical_hash({"scope_id": self.scope_id, "periods": self.periods})

    @property
    def calendar_hash(self) -> str:
        """Hash the exact owner seal and complete expected-period denominator."""

        return canonical_hash(
            {
                "scope_id": self.scope_id,
                "evidence_hash": self.evidence.seal_hash,
                "periods": self.periods,
            }
        )


@dataclass(frozen=True)
class SpreadObservation:
    """One exact period/revision spread observation known at a PIT cutoff."""

    observation_id: str
    observation_version: str
    revision_number: int
    period_id: str
    scope_id: str
    spread_definition_id: str
    spread_definition_version: str
    currency: str
    numerator_curve_role: str
    denominator_curve_role: str
    state: SpreadObservationState
    value_bp: Decimal | None
    observed_at: datetime
    available_at: datetime
    record_hash: str
    publication: ExactEvidence

    def __post_init__(self) -> None:
        for name in (
            "observation_id",
            "observation_version",
            "period_id",
            "scope_id",
            "spread_definition_id",
            "spread_definition_version",
            "currency",
            "numerator_curve_role",
            "denominator_curve_role",
        ):
            require_token(str(getattr(self, name)), f"SpreadObservation.{name}")
        if self.revision_number < 0:
            raise ValueError("SpreadObservation.revision_number cannot be negative")
        if not isinstance(self.state, SpreadObservationState):
            raise ValueError("SpreadObservation.state is invalid")
        if self.state is SpreadObservationState.MISSING:
            if self.value_bp is not None:
                raise ValueError("missing spread observation cannot carry a value")
        else:
            if self.value_bp is None:
                raise ValueError("observed/estimated spread observation requires a value")
            require_finite(self.value_bp, "SpreadObservation.value_bp")
        require_aware(self.observed_at, "SpreadObservation.observed_at")
        require_aware(self.available_at, "SpreadObservation.available_at")
        if self.available_at < self.observed_at:
            raise ValueError("spread available_at cannot precede observed_at")
        require_sha256(self.record_hash, "SpreadObservation.record_hash")
        if self.publication.role is not EvidenceRole.PUBLICATION:
            raise ValueError("spread observation requires publication evidence")
        expected_curve_role = f"{self.numerator_curve_role}:{self.denominator_curve_role}"
        if self.publication.subject_id != self.scope_id:
            raise ValueError("spread publication subject must match observation scope")
        if (
            self.publication.evidence_id != self.observation_id
            or self.publication.version != self.observation_version
        ):
            raise ValueError("spread Publication locator must match observation id/version")
        if self.publication.currency != self.currency:
            raise ValueError("spread publication currency must match observation currency")
        if self.publication.curve_role != expected_curve_role:
            raise ValueError("spread publication curve_role must bind both spread legs")
        if (
            self.publication.observed_at != self.observed_at
            or self.publication.available_at != self.available_at
        ):
            raise ValueError("spread clocks must match exact publication clocks")
        if (
            self.record_hash != self.publication.content_hash
            and self.record_hash not in self.publication.upstream_hashes
        ):
            raise ValueError("spread record hash must be bound by publication provenance")

    @property
    def identity(self) -> tuple[str, str, int, str]:
        """Return the exact period/revision/content identity."""

        return (
            self.period_id,
            self.observation_version,
            self.revision_number,
            self.record_hash.lower(),
        )

    @property
    def seal_hash(self) -> str:
        """Hash the complete observation and its exact publication seal."""

        return canonical_hash(
            {
                "observation_id": self.observation_id,
                "observation_version": self.observation_version,
                "revision_number": self.revision_number,
                "period_id": self.period_id,
                "scope_id": self.scope_id,
                "spread_definition_id": self.spread_definition_id,
                "spread_definition_version": self.spread_definition_version,
                "currency": self.currency,
                "numerator_curve_role": self.numerator_curve_role,
                "denominator_curve_role": self.denominator_curve_role,
                "state": self.state,
                "value_bp": self.value_bp,
                "observed_at": self.observed_at,
                "available_at": self.available_at,
                "record_hash": self.record_hash.lower(),
                "publication_hash": self.publication.seal_hash,
            }
        )


@dataclass(frozen=True)
class SpreadPercentilePolicy:
    """Versioned lookback, coverage, revision, and tie semantics."""

    policy_id: str
    policy_version: str
    lookback_starts_at: datetime
    lookback_ends_at: datetime
    minimum_observation_count: int
    minimum_coverage_ratio: Decimal
    tie_convention: SpreadTieConvention
    target_sample_convention: TargetSampleConvention
    revision_selection: RevisionSelection
    revision_policy_version: str
    maximum_release_lag_seconds: int
    allow_estimated: bool
    allow_estimated_target: bool
    evidence: ExactEvidence

    def __post_init__(self) -> None:
        require_token(self.policy_id, "SpreadPercentilePolicy.policy_id")
        require_token(self.policy_version, "SpreadPercentilePolicy.policy_version")
        require_token(
            self.revision_policy_version,
            "SpreadPercentilePolicy.revision_policy_version",
        )
        require_aware(self.lookback_starts_at, "SpreadPercentilePolicy.lookback_starts_at")
        require_aware(self.lookback_ends_at, "SpreadPercentilePolicy.lookback_ends_at")
        if self.lookback_ends_at <= self.lookback_starts_at:
            raise ValueError("spread lookback end must follow start")
        if self.minimum_observation_count <= 0:
            raise ValueError("minimum_observation_count must be positive")
        require_finite(
            self.minimum_coverage_ratio,
            "SpreadPercentilePolicy.minimum_coverage_ratio",
        )
        if not Decimal("0") < self.minimum_coverage_ratio <= Decimal("1"):
            raise ValueError("minimum_coverage_ratio must be in (0, 1]")
        if not isinstance(self.tie_convention, SpreadTieConvention):
            raise ValueError("tie_convention is invalid")
        if self.target_sample_convention is not TargetSampleConvention.EXCLUDED:
            raise ValueError("R5 target must remain separate from its reference sample")
        if self.revision_selection is not RevisionSelection.LATEST_AVAILABLE_AT_CUTOFF:
            raise ValueError("revision_selection is invalid")
        if self.maximum_release_lag_seconds < 0:
            raise ValueError("maximum_release_lag_seconds cannot be negative")
        if self.evidence.role is not EvidenceRole.POLICY:
            raise ValueError("spread percentile policy requires Research policy evidence")
        if (
            self.evidence.evidence_id != self.policy_id
            or self.evidence.version != self.policy_version
            or self.evidence.subject_id != self.policy_id
            or self.evidence.curve_role != "spread_percentile_policy"
        ):
            raise ValueError("spread policy evidence id/version/subject/role mismatch")

    @property
    def policy_hash(self) -> str:
        """Hash every statistical and PIT selection semantic."""

        return canonical_hash(
            {
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "lookback_starts_at": self.lookback_starts_at,
                "lookback_ends_at": self.lookback_ends_at,
                "minimum_observation_count": self.minimum_observation_count,
                "minimum_coverage_ratio": self.minimum_coverage_ratio,
                "tie_convention": self.tie_convention,
                "target_sample_convention": self.target_sample_convention,
                "revision_selection": self.revision_selection,
                "revision_policy_version": self.revision_policy_version,
                "maximum_release_lag_seconds": self.maximum_release_lag_seconds,
                "allow_estimated": self.allow_estimated,
                "allow_estimated_target": self.allow_estimated_target,
                "evidence_hash": self.evidence.seal_hash,
            }
        )


@dataclass(frozen=True)
class SpreadPercentileEvidence:
    """Target and historical revisions returned by one exact PIT input provider."""

    evidence_id: str
    evidence_version: str
    scope_id: str
    spread_definition_id: str
    spread_definition_version: str
    currency: str
    numerator_curve_role: str
    denominator_curve_role: str
    target: SpreadObservation
    reference_observations: tuple[SpreadObservation, ...]
    source: ExactEvidence

    def __post_init__(self) -> None:
        for name in (
            "evidence_id",
            "evidence_version",
            "scope_id",
            "spread_definition_id",
            "spread_definition_version",
            "currency",
            "numerator_curve_role",
            "denominator_curve_role",
        ):
            require_token(str(getattr(self, name)), f"SpreadPercentileEvidence.{name}")
        if self.source.role is not EvidenceRole.EXACT_PIT_INPUT:
            raise ValueError("spread percentile evidence requires exact PIT input evidence")
        expected_curve_role = (
            "spread_percentile:" f"{self.numerator_curve_role}:{self.denominator_curve_role}"
        )
        if (
            self.source.evidence_id != self.evidence_id
            or self.source.version != self.evidence_version
            or self.source.subject_id != self.scope_id
            or self.source.curve_role != expected_curve_role
        ):
            raise ValueError("spread PIT source must match id/version/scope/role")
        if self.source.currency != self.currency:
            raise ValueError("spread PIT source must bind currency and both curve roles")
        ordered = tuple(
            sorted(
                self.reference_observations,
                key=lambda observation: (
                    observation.period_id,
                    observation.revision_number,
                    observation.available_at,
                    observation.observation_id,
                    observation.observation_version,
                    observation.record_hash,
                ),
            )
        )
        if ordered != self.reference_observations:
            raise ValueError("spread reference observations must use canonical order")
        observation_hashes = {
            self.target.seal_hash,
            *(observation.seal_hash for observation in self.reference_observations),
        }
        if not observation_hashes.issubset(set(self.source.upstream_hashes)):
            raise ValueError("spread PIT source must attest target/reference hashes")
        if self.source.content_hash != self.raw_manifest_hash:
            raise ValueError("spread PIT source content hash must equal raw manifest")

    @property
    def raw_manifest_hash(self) -> str:
        """Hash target/reference content without recursively including source seal."""

        return canonical_hash(
            {
                "evidence_id": self.evidence_id,
                "evidence_version": self.evidence_version,
                "scope_id": self.scope_id,
                "spread_definition_id": self.spread_definition_id,
                "spread_definition_version": self.spread_definition_version,
                "currency": self.currency,
                "numerator_curve_role": self.numerator_curve_role,
                "denominator_curve_role": self.denominator_curve_role,
                "target_hash": self.target.seal_hash,
                "reference_hashes": tuple(
                    observation.seal_hash for observation in self.reference_observations
                ),
            }
        )

    @property
    def evidence_hash(self) -> str:
        """Hash the target and every supplied historical revision."""

        return canonical_hash(
            {
                "evidence_id": self.evidence_id,
                "evidence_version": self.evidence_version,
                "scope_id": self.scope_id,
                "spread_definition_id": self.spread_definition_id,
                "spread_definition_version": self.spread_definition_version,
                "currency": self.currency,
                "numerator_curve_role": self.numerator_curve_role,
                "denominator_curve_role": self.denominator_curve_role,
                "target_hash": self.target.seal_hash,
                "reference_hashes": tuple(
                    observation.seal_hash for observation in self.reference_observations
                ),
                "source_hash": self.source.seal_hash,
            }
        )


@dataclass(frozen=True)
class SelectedSpreadObservation:
    """Exact selected period/revision identity sealed into the result."""

    period_id: str
    observation_id: str
    observation_version: str
    revision_number: int
    record_hash: str
    value_bp: Decimal

    def __post_init__(self) -> None:
        require_token(self.period_id, "SelectedSpreadObservation.period_id")
        require_token(self.observation_id, "SelectedSpreadObservation.observation_id")
        require_token(
            self.observation_version,
            "SelectedSpreadObservation.observation_version",
        )
        if self.revision_number < 0:
            raise ValueError("selected spread revision cannot be negative")
        require_sha256(self.record_hash, "SelectedSpreadObservation.record_hash")
        require_finite(self.value_bp, "SelectedSpreadObservation.value_bp")


@dataclass(frozen=True)
class SpreadPercentileAssessment:
    """Recomputable, triple-blocked historical percentile result."""

    status: SpreadAssessmentStatus
    evaluated_at: datetime
    input_hash: str
    output_hash: str
    policy_hash: str
    calendar_hash: str
    tie_convention: SpreadTieConvention
    minimum_observation_count: int
    minimum_coverage_ratio: Decimal
    target_value_bp: Decimal | None
    expected_period_count: int
    coverage_numerator: int
    coverage_ratio: Decimal
    reference_count: int
    less_count: int
    equal_count: int
    greater_count: int
    percentile: Decimal | None
    selected_observations: tuple[SelectedSpreadObservation, ...]
    blockers: tuple[SpreadBlocker, ...]
    research_only: bool
    must_not_execute: bool
    must_not_use_for_decision: bool

    def __post_init__(self) -> None:
        require_aware(self.evaluated_at, "SpreadPercentileAssessment.evaluated_at")
        require_sha256(self.input_hash, "SpreadPercentileAssessment.input_hash")
        require_sha256(self.output_hash, "SpreadPercentileAssessment.output_hash")
        require_sha256(self.policy_hash, "SpreadPercentileAssessment.policy_hash")
        require_sha256(self.calendar_hash, "SpreadPercentileAssessment.calendar_hash")
        if not isinstance(self.tie_convention, SpreadTieConvention):
            raise ValueError("SpreadPercentileAssessment.tie_convention is invalid")
        if self.minimum_observation_count <= 0:
            raise ValueError("minimum_observation_count must be positive")
        require_finite(
            self.minimum_coverage_ratio,
            "SpreadPercentileAssessment.minimum_coverage_ratio",
        )
        if not Decimal("0") < self.minimum_coverage_ratio <= Decimal("1"):
            raise ValueError("minimum_coverage_ratio must be in (0, 1]")
        if not (self.research_only and self.must_not_execute and self.must_not_use_for_decision):
            raise ValueError("spread percentile assessment must remain research-only")
        for name in (
            "expected_period_count",
            "coverage_numerator",
            "reference_count",
            "less_count",
            "equal_count",
            "greater_count",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        require_finite(self.coverage_ratio, "SpreadPercentileAssessment.coverage_ratio")
        expected_coverage = (
            Decimal(self.reference_count) / Decimal(self.expected_period_count)
            if self.expected_period_count > 0
            else Decimal("0")
        )
        if self.coverage_ratio != expected_coverage:
            raise ValueError("spread coverage ratio is not recomputable")
        if (
            not Decimal("0") <= self.coverage_ratio <= Decimal("1")
            or self.reference_count > self.expected_period_count
        ):
            raise ValueError("spread coverage cannot exceed its expected denominator")
        if len(self.selected_observations) != self.reference_count:
            raise ValueError("selected observations must equal reference_count")
        if self.selected_observations != tuple(
            sorted(
                self.selected_observations,
                key=lambda row: (
                    row.period_id,
                    row.observation_id,
                    row.revision_number,
                    row.record_hash,
                ),
            )
        ):
            raise ValueError("selected observations must use canonical order")
        period_ids = tuple(row.period_id for row in self.selected_observations)
        if len(period_ids) != len(set(period_ids)):
            raise ValueError("selected spread periods cannot repeat")
        if self.less_count + self.equal_count + self.greater_count != self.reference_count:
            raise ValueError("spread comparison counts must sum to reference_count")
        if self.coverage_numerator != self.reference_count:
            raise ValueError("coverage numerator must equal usable reference_count")
        if self.percentile is not None:
            require_finite(self.percentile, "SpreadPercentileAssessment.percentile")
            if not Decimal("0") <= self.percentile <= Decimal("1"):
                raise ValueError("spread percentile must be in [0, 1]")
        if self.blockers != tuple(
            sorted(set(self.blockers), key=lambda item: (item.code.value, item.detail))
        ):
            raise ValueError("spread blockers must be unique and canonically ordered")
        if self.target_value_bp is None or self.reference_count == 0:
            if (
                self.less_count != 0
                or self.equal_count != 0
                or self.greater_count != 0
                or self.percentile is not None
            ):
                raise ValueError("unavailable spread sample cannot carry statistics")
        if self.target_value_bp is not None:
            require_finite(
                self.target_value_bp,
                "SpreadPercentileAssessment.target_value_bp",
            )
            calculated_less = sum(
                row.value_bp < self.target_value_bp for row in self.selected_observations
            )
            calculated_equal = sum(
                row.value_bp == self.target_value_bp for row in self.selected_observations
            )
            calculated_greater = sum(
                row.value_bp > self.target_value_bp for row in self.selected_observations
            )
            if (
                calculated_less,
                calculated_equal,
                calculated_greater,
            ) != (self.less_count, self.equal_count, self.greater_count):
                raise ValueError("spread comparison counts are not recomputable")
            if self.reference_count > 0:
                if self.tie_convention is SpreadTieConvention.MID_RANK:
                    calculated_percentile = (
                        Decimal(calculated_less) + Decimal("0.5") * Decimal(calculated_equal)
                    ) / Decimal(self.reference_count)
                elif self.tie_convention is SpreadTieConvention.STRICT_LESS:
                    calculated_percentile = Decimal(calculated_less) / Decimal(self.reference_count)
                else:
                    calculated_percentile = Decimal(calculated_less + calculated_equal) / Decimal(
                        self.reference_count
                    )
                if self.percentile != calculated_percentile:
                    raise ValueError("spread percentile is not recomputable")
        if self.status is SpreadAssessmentStatus.AVAILABLE:
            if self.blockers or self.percentile is None or self.target_value_bp is None:
                raise ValueError("available spread percentile has inconsistent output")
            if self.reference_count < self.minimum_observation_count:
                raise ValueError("available spread percentile violates minimum sample")
            if self.coverage_ratio < self.minimum_coverage_ratio:
                raise ValueError("available spread percentile violates coverage policy")
        elif not self.blockers:
            raise ValueError("blocked spread percentile requires blockers")
        if self.output_hash.lower() != self.calculated_output_hash:
            raise ValueError("spread percentile output hash mismatch")

    @property
    def calculated_output_hash(self) -> str:
        """Recompute the complete output and safety digest."""

        return canonical_hash(
            {
                "status": self.status,
                "evaluated_at": self.evaluated_at,
                "input_hash": self.input_hash.lower(),
                "policy_hash": self.policy_hash,
                "calendar_hash": self.calendar_hash,
                "tie_convention": self.tie_convention,
                "minimum_observation_count": self.minimum_observation_count,
                "minimum_coverage_ratio": self.minimum_coverage_ratio,
                "target_value_bp": self.target_value_bp,
                "expected_period_count": self.expected_period_count,
                "coverage_numerator": self.coverage_numerator,
                "coverage_ratio": self.coverage_ratio,
                "reference_count": self.reference_count,
                "less_count": self.less_count,
                "equal_count": self.equal_count,
                "greater_count": self.greater_count,
                "percentile": self.percentile,
                "selected_observations": self.selected_observations,
                "blockers": self.blockers,
                "research_only": self.research_only,
                "must_not_execute": self.must_not_execute,
                "must_not_use_for_decision": self.must_not_use_for_decision,
            }
        )


def spread_percentile_input_hash(
    evidence: SpreadPercentileEvidence,
    policy: SpreadPercentilePolicy,
    calendar: ExpectedObservationCalendar,
    *,
    evaluated_at: datetime,
) -> str:
    """Hash the complete spread evidence, policy, calendar, and PIT cutoff."""

    require_aware(evaluated_at, "evaluated_at")
    return canonical_hash(
        {
            "evidence_hash": evidence.evidence_hash,
            "policy_hash": policy.policy_hash,
            "calendar_hash": calendar.calendar_hash,
            "evaluated_at": evaluated_at,
        }
    )


def _blocker(code: SpreadBlockerCode, detail: str) -> SpreadBlocker:
    return SpreadBlocker(code=code, detail=detail)


def _reference_matches_scope(
    evidence: SpreadPercentileEvidence,
    observation: SpreadObservation,
) -> tuple[SpreadBlocker, ...]:
    blockers: list[SpreadBlocker] = []
    if observation.scope_id != evidence.scope_id:
        blockers.append(_blocker(SpreadBlockerCode.SCOPE_MISMATCH, "scope mismatch"))
    if (
        observation.spread_definition_id != evidence.spread_definition_id
        or observation.spread_definition_version != evidence.spread_definition_version
    ):
        blockers.append(_blocker(SpreadBlockerCode.DEFINITION_MISMATCH, "definition mismatch"))
    if observation.currency != evidence.currency:
        blockers.append(_blocker(SpreadBlockerCode.CURRENCY_MISMATCH, "currency mismatch"))
    if (
        observation.numerator_curve_role != evidence.numerator_curve_role
        or observation.denominator_curve_role != evidence.denominator_curve_role
    ):
        blockers.append(_blocker(SpreadBlockerCode.CURVE_ROLE_MISMATCH, "curve role mismatch"))
    return tuple(blockers)


def _result(
    *,
    status: SpreadAssessmentStatus,
    evaluated_at: datetime,
    input_hash: str,
    policy: SpreadPercentilePolicy,
    calendar: ExpectedObservationCalendar,
    target_value_bp: Decimal | None,
    expected_period_count: int,
    selected: tuple[SelectedSpreadObservation, ...],
    less_count: int,
    equal_count: int,
    greater_count: int,
    percentile: Decimal | None,
    blockers: tuple[SpreadBlocker, ...],
) -> SpreadPercentileAssessment:
    reference_count = len(selected)
    coverage = (
        Decimal(reference_count) / Decimal(expected_period_count)
        if expected_period_count > 0
        else Decimal("0")
    )
    payload = {
        "status": status,
        "evaluated_at": evaluated_at,
        "input_hash": input_hash.lower(),
        "policy_hash": policy.policy_hash,
        "calendar_hash": calendar.calendar_hash,
        "tie_convention": policy.tie_convention,
        "minimum_observation_count": policy.minimum_observation_count,
        "minimum_coverage_ratio": policy.minimum_coverage_ratio,
        "target_value_bp": target_value_bp,
        "expected_period_count": expected_period_count,
        "coverage_numerator": reference_count,
        "coverage_ratio": coverage,
        "reference_count": reference_count,
        "less_count": less_count,
        "equal_count": equal_count,
        "greater_count": greater_count,
        "percentile": percentile,
        "selected_observations": selected,
        "blockers": blockers,
        "research_only": True,
        "must_not_execute": True,
        "must_not_use_for_decision": True,
    }
    return SpreadPercentileAssessment(
        status=status,
        evaluated_at=evaluated_at,
        input_hash=input_hash,
        output_hash=canonical_hash(payload),
        policy_hash=policy.policy_hash,
        calendar_hash=calendar.calendar_hash,
        tie_convention=policy.tie_convention,
        minimum_observation_count=policy.minimum_observation_count,
        minimum_coverage_ratio=policy.minimum_coverage_ratio,
        target_value_bp=target_value_bp,
        expected_period_count=expected_period_count,
        coverage_numerator=reference_count,
        coverage_ratio=coverage,
        reference_count=reference_count,
        less_count=less_count,
        equal_count=equal_count,
        greater_count=greater_count,
        percentile=percentile,
        selected_observations=selected,
        blockers=blockers,
        research_only=True,
        must_not_execute=True,
        must_not_use_for_decision=True,
    )


from apps.fixed_income.domain.spread_history_evaluation import (  # noqa: E402
    evaluate_spread_percentile,
)

__all__ = [
    "CalendarPeriod",
    "ExpectedObservationCalendar",
    "RevisionSelection",
    "SelectedSpreadObservation",
    "SpreadAssessmentStatus",
    "SpreadBlocker",
    "SpreadBlockerCode",
    "SpreadObservation",
    "SpreadObservationState",
    "SpreadPercentileAssessment",
    "SpreadPercentileEvidence",
    "SpreadPercentilePolicy",
    "SpreadTieConvention",
    "TargetSampleConvention",
    "evaluate_spread_percentile",
    "spread_percentile_input_hash",
]
