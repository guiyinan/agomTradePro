"""PIT rating-taxonomy and migration contracts for R5 research."""

from __future__ import annotations

from collections import Counter
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

_CENSORED_LABEL = "CENSORED"
_MISSING_LABEL = "MISSING"
_UNRESOLVED_ORIGIN = "UNRESOLVED_ORIGIN"


class RatingTerminalKind(StrEnum):
    """Mutually exclusive terminal state for one origin-cohort member."""

    LIVE_GRADE = "live_grade"
    DEFAULT = "default"
    WITHDRAWN = "withdrawn"
    CENSORED = "censored"
    MISSING = "missing"


class RatingDenominatorConvention(StrEnum):
    """Explicit transition-row denominator convention."""

    ORIGIN_COHORT_ALL = "origin_cohort_all"


class RatingCensoringConvention(StrEnum):
    """Explicit handling of right-censored cohort members."""

    RETAIN_AS_BUCKET = "retain_as_bucket"


class RatingTerminalSelection(StrEnum):
    """Versioned terminal-event selection semantics."""

    EARLIEST_EVENT_DEFAULT_PRECEDENCE = "earliest_event_default_precedence"


class RatingMigrationStatus(StrEnum):
    """Availability state of one research-only transition matrix."""

    AVAILABLE = "available"
    BLOCKED = "blocked"


class RatingMigrationBlockerCode(StrEnum):
    """Stable fail-closed reasons for rating migration evidence."""

    INPUT_HASH_MISMATCH = "fixed_income.rating.input.hash_mismatch"
    POLICY_NOT_PREREGISTERED = "fixed_income.rating.policy.not_preregistered"
    EVIDENCE_FROM_FUTURE = "fixed_income.rating.evidence.from_future"
    EVIDENCE_STALE = "fixed_income.rating.evidence.stale"
    TAXONOMY_MISMATCH = "fixed_income.rating.taxonomy.mismatch"
    TAXONOMY_GRADE_UNKNOWN = "fixed_income.rating.taxonomy.grade_unknown"
    COHORT_HORIZON_MISMATCH = "fixed_income.rating.cohort.horizon_mismatch"
    COHORT_INCOMPLETE = "fixed_income.rating.cohort.incomplete"
    COHORT_TOO_SMALL = "fixed_income.rating.cohort.too_small"
    COHORT_MEMBER_DUPLICATE = "fixed_income.rating.cohort.member_duplicate"
    COHORT_MEMBER_MISSING = "fixed_income.rating.cohort.member_missing"
    COHORT_MEMBER_UNEXPECTED = "fixed_income.rating.cohort.member_unexpected"
    ORIGIN_AFTER_FORMATION = "fixed_income.rating.origin.after_formation"
    OUTCOME_FROM_FUTURE = "fixed_income.rating.outcome.from_future"
    OUTCOME_AFTER_HORIZON = "fixed_income.rating.outcome.after_horizon"
    OUTCOME_AVAILABLE_LATE = "fixed_income.rating.outcome.available_late"
    CENSORING_INVALID = "fixed_income.rating.censoring.invalid"
    DEFAULT_NOT_ABSORBING = "fixed_income.rating.default.not_absorbing"
    TERMINAL_SELECTION_MISMATCH = "fixed_income.rating.terminal_selection.mismatch"
    COVERAGE_INSUFFICIENT = "fixed_income.rating.coverage.insufficient"


@dataclass(frozen=True)
class RatingMigrationBlocker:
    """Stable blocker with bounded diagnostic detail."""

    code: RatingMigrationBlockerCode
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, RatingMigrationBlockerCode):
            raise ValueError("RatingMigrationBlocker.code is invalid")
        require_token(
            self.detail.replace(" ", "_"),
            "RatingMigrationBlocker.detail",
            maximum=240,
        )


@dataclass(frozen=True)
class RatingTaxonomy:
    """Exact agency scale with ordered live, DEFAULT, and WITHDRAWN labels."""

    agency_id: str
    taxonomy_id: str
    taxonomy_version: str
    ordered_live_grades: tuple[str, ...]
    default_label: str
    withdrawn_label: str
    evidence: ExactEvidence

    def __post_init__(self) -> None:
        for name in (
            "agency_id",
            "taxonomy_id",
            "taxonomy_version",
            "default_label",
            "withdrawn_label",
        ):
            require_token(str(getattr(self, name)), f"RatingTaxonomy.{name}")
        if not self.ordered_live_grades:
            raise ValueError("rating taxonomy requires ordered live grades")
        for index, grade in enumerate(self.ordered_live_grades):
            require_token(grade, f"RatingTaxonomy.ordered_live_grades[{index}]")
        labels = (*self.ordered_live_grades, self.default_label, self.withdrawn_label)
        if len(labels) != len(set(labels)):
            raise ValueError("rating taxonomy labels must be unique")
        if any(label in {_CENSORED_LABEL, _MISSING_LABEL, _UNRESOLVED_ORIGIN} for label in labels):
            raise ValueError("rating taxonomy cannot use reserved result labels")
        if self.evidence.role is not EvidenceRole.PUBLICATION:
            raise ValueError("rating taxonomy requires Publication evidence")
        if (
            self.evidence.subject_id != self.taxonomy_id
            or self.evidence.version != self.taxonomy_version
            or self.evidence.curve_role != "rating_taxonomy"
        ):
            raise ValueError("taxonomy Publication must match subject/version/semantic role")

    @property
    def taxonomy_hash(self) -> str:
        """Hash the complete ordered taxonomy and exact owner evidence."""

        return canonical_hash(
            {
                "agency_id": self.agency_id,
                "taxonomy_id": self.taxonomy_id,
                "taxonomy_version": self.taxonomy_version,
                "ordered_live_grades": self.ordered_live_grades,
                "default_label": self.default_label,
                "withdrawn_label": self.withdrawn_label,
                "evidence_hash": self.evidence.seal_hash,
            }
        )


@dataclass(frozen=True)
class RatingCohort:
    """Exact formation cohort and expected denominator from an authoritative owner."""

    cohort_id: str
    cohort_version: str
    formation_at: datetime
    horizon_ends_at: datetime
    expected_member_ids: tuple[str, ...]
    evidence: ExactEvidence

    def __post_init__(self) -> None:
        require_token(self.cohort_id, "RatingCohort.cohort_id")
        require_token(self.cohort_version, "RatingCohort.cohort_version")
        require_aware(self.formation_at, "RatingCohort.formation_at")
        require_aware(self.horizon_ends_at, "RatingCohort.horizon_ends_at")
        if self.horizon_ends_at <= self.formation_at:
            raise ValueError("rating cohort horizon must follow formation")
        if not self.expected_member_ids:
            raise ValueError("rating cohort requires expected members")
        for index, member_id in enumerate(self.expected_member_ids):
            require_token(member_id, f"RatingCohort.expected_member_ids[{index}]")
        if self.expected_member_ids != tuple(sorted(set(self.expected_member_ids))):
            raise ValueError("rating cohort member ids must be unique and canonical")
        if self.evidence.role is not EvidenceRole.EXACT_PIT_INPUT:
            raise ValueError("rating cohort requires exact PIT input evidence")
        if (
            self.evidence.evidence_id != self.cohort_id
            or self.evidence.version != self.cohort_version
            or self.evidence.subject_id != self.cohort_id
            or self.evidence.curve_role != "rating_cohort"
        ):
            raise ValueError("cohort PIT evidence must match id/version/semantic role")

    @property
    def cohort_hash(self) -> str:
        """Hash formation, horizon, every expected member, and owner evidence."""

        return canonical_hash(
            {
                "cohort_id": self.cohort_id,
                "cohort_version": self.cohort_version,
                "formation_at": self.formation_at,
                "horizon_ends_at": self.horizon_ends_at,
                "expected_member_ids": self.expected_member_ids,
                "evidence_hash": self.evidence.seal_hash,
            }
        )


@dataclass(frozen=True)
class RatingMemberTransition:
    """Independent origin and terminal-selection owner evidence for one member."""

    member_id: str
    taxonomy_id: str
    taxonomy_version: str
    origin_grade: str
    terminal_kind: RatingTerminalKind
    destination_label: str | None
    origin_observed_at: datetime
    origin_available_at: datetime
    outcome_observed_at: datetime | None
    outcome_available_at: datetime | None
    censored_at: datetime | None
    selection_observed_at: datetime
    selection_available_at: datetime
    origin_record_hash: str
    terminal_record_hash: str
    origin_publication: ExactEvidence
    terminal_publication: ExactEvidence

    def __post_init__(self) -> None:
        for name in ("member_id", "taxonomy_id", "taxonomy_version", "origin_grade"):
            require_token(str(getattr(self, name)), f"RatingMemberTransition.{name}")
        if not isinstance(self.terminal_kind, RatingTerminalKind):
            raise ValueError("rating terminal kind is invalid")
        for name in (
            "origin_observed_at",
            "origin_available_at",
            "selection_observed_at",
            "selection_available_at",
        ):
            require_aware(getattr(self, name), f"RatingMemberTransition.{name}")
        if self.origin_available_at < self.origin_observed_at:
            raise ValueError("origin availability cannot precede observation")
        if self.selection_available_at < self.selection_observed_at:
            raise ValueError("selection availability cannot precede observation")
        observed_terminal = self.terminal_kind in {
            RatingTerminalKind.LIVE_GRADE,
            RatingTerminalKind.DEFAULT,
            RatingTerminalKind.WITHDRAWN,
        }
        if observed_terminal:
            if self.destination_label is None:
                raise ValueError("observed terminal outcome requires destination label")
            require_token(self.destination_label, "RatingMemberTransition.destination_label")
            if self.outcome_observed_at is None or self.outcome_available_at is None:
                raise ValueError("observed terminal outcome requires both outcome clocks")
            require_aware(self.outcome_observed_at, "outcome_observed_at")
            require_aware(self.outcome_available_at, "outcome_available_at")
            if self.outcome_available_at < self.outcome_observed_at:
                raise ValueError("outcome availability cannot precede observation")
            if self.censored_at is not None:
                raise ValueError("observed outcome cannot also be censored")
        elif self.terminal_kind is RatingTerminalKind.CENSORED:
            if self.censored_at is None:
                raise ValueError("censored member requires censor clock")
            require_aware(self.censored_at, "RatingMemberTransition.censored_at")
            if any(
                value is not None
                for value in (
                    self.destination_label,
                    self.outcome_observed_at,
                    self.outcome_available_at,
                )
            ):
                raise ValueError("censored member cannot carry terminal outcome")
        elif any(
            value is not None
            for value in (
                self.destination_label,
                self.outcome_observed_at,
                self.outcome_available_at,
                self.censored_at,
            )
        ):
            raise ValueError("missing member cannot carry synthesized outcome")
        require_sha256(self.origin_record_hash, "origin_record_hash")
        require_sha256(self.terminal_record_hash, "terminal_record_hash")
        if (
            self.origin_publication.role is not EvidenceRole.PUBLICATION
            or self.terminal_publication.role is not EvidenceRole.PUBLICATION
        ):
            raise ValueError("rating member records require Publication evidence")
        if (
            self.origin_publication.subject_id != self.member_id
            or self.origin_publication.curve_role != "rating_origin"
            or self.origin_publication.observed_at != self.origin_observed_at
            or self.origin_publication.available_at != self.origin_available_at
        ):
            raise ValueError("origin rating clocks/subject/role must match Publication")
        if (
            self.terminal_publication.subject_id != self.member_id
            or self.terminal_publication.curve_role is None
            or not self.terminal_publication.curve_role.startswith("rating_terminal_selection:")
            or self.terminal_publication.observed_at != self.selection_observed_at
            or self.terminal_publication.available_at != self.selection_available_at
        ):
            raise ValueError("terminal selection clocks/subject/role must match Publication")
        if (
            self.origin_record_hash != self.origin_publication.content_hash
            and self.origin_record_hash not in self.origin_publication.upstream_hashes
        ):
            raise ValueError("origin record hash is not bound by Publication provenance")
        if (
            self.terminal_record_hash != self.terminal_publication.content_hash
            and self.terminal_record_hash not in self.terminal_publication.upstream_hashes
        ):
            raise ValueError("terminal record hash is not bound by Publication provenance")

    @property
    def seal_hash(self) -> str:
        """Hash both exact owner records and every outcome/censoring clock."""

        return canonical_hash(
            {
                "member_id": self.member_id,
                "taxonomy_id": self.taxonomy_id,
                "taxonomy_version": self.taxonomy_version,
                "origin_grade": self.origin_grade,
                "terminal_kind": self.terminal_kind,
                "destination_label": self.destination_label,
                "origin_observed_at": self.origin_observed_at,
                "origin_available_at": self.origin_available_at,
                "outcome_observed_at": self.outcome_observed_at,
                "outcome_available_at": self.outcome_available_at,
                "censored_at": self.censored_at,
                "selection_observed_at": self.selection_observed_at,
                "selection_available_at": self.selection_available_at,
                "origin_record_hash": self.origin_record_hash,
                "terminal_record_hash": self.terminal_record_hash,
                "origin_publication_hash": self.origin_publication.seal_hash,
                "terminal_publication_hash": self.terminal_publication.seal_hash,
            }
        )


@dataclass(frozen=True)
class RatingMigrationPolicy:
    """Versioned horizon, full-cohort denominator, and terminal selection policy."""

    policy_id: str
    policy_version: str
    formation_cutoff: datetime
    horizon_days: int
    outcome_availability_grace_seconds: int
    minimum_cohort_size: int
    minimum_terminal_coverage_ratio: Decimal
    denominator_convention: RatingDenominatorConvention
    censoring_convention: RatingCensoringConvention
    terminal_selection: RatingTerminalSelection
    evidence: ExactEvidence

    def __post_init__(self) -> None:
        require_token(self.policy_id, "RatingMigrationPolicy.policy_id")
        require_token(self.policy_version, "RatingMigrationPolicy.policy_version")
        require_aware(self.formation_cutoff, "RatingMigrationPolicy.formation_cutoff")
        if self.horizon_days <= 0 or self.outcome_availability_grace_seconds < 0:
            raise ValueError("rating horizon/grace values are invalid")
        if self.minimum_cohort_size <= 0:
            raise ValueError("minimum rating cohort size must be positive")
        require_finite(
            self.minimum_terminal_coverage_ratio,
            "RatingMigrationPolicy.minimum_terminal_coverage_ratio",
        )
        if not Decimal("0") < self.minimum_terminal_coverage_ratio <= Decimal("1"):
            raise ValueError("minimum terminal coverage must be in (0, 1]")
        if self.denominator_convention is not RatingDenominatorConvention.ORIGIN_COHORT_ALL:
            raise ValueError("rating denominator must retain the full origin cohort")
        if self.censoring_convention is not RatingCensoringConvention.RETAIN_AS_BUCKET:
            raise ValueError("censored members must remain a denominator bucket")
        if self.terminal_selection is not RatingTerminalSelection.EARLIEST_EVENT_DEFAULT_PRECEDENCE:
            raise ValueError("rating terminal selection semantics are invalid")
        if self.evidence.role is not EvidenceRole.POLICY:
            raise ValueError("rating migration policy requires Research evidence")
        if (
            self.evidence.evidence_id != self.policy_id
            or self.evidence.version != self.policy_version
            or self.evidence.subject_id != self.policy_id
            or self.evidence.curve_role != "rating_migration_policy"
        ):
            raise ValueError("rating policy evidence must match id/version/semantic role")

    @property
    def policy_hash(self) -> str:
        """Hash every denominator, censoring, coverage, lag, and selection semantic."""

        return canonical_hash(
            {
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "formation_cutoff": self.formation_cutoff,
                "horizon_days": self.horizon_days,
                "outcome_availability_grace_seconds": (self.outcome_availability_grace_seconds),
                "minimum_cohort_size": self.minimum_cohort_size,
                "minimum_terminal_coverage_ratio": (self.minimum_terminal_coverage_ratio),
                "denominator_convention": self.denominator_convention,
                "censoring_convention": self.censoring_convention,
                "terminal_selection": self.terminal_selection,
                "evidence_hash": self.evidence.seal_hash,
            }
        )


@dataclass(frozen=True)
class RatingMigrationEvidence:
    """Exact taxonomy, expected cohort, and explicit member terminal selections."""

    evidence_id: str
    evidence_version: str
    taxonomy: RatingTaxonomy
    cohort: RatingCohort
    transitions: tuple[RatingMemberTransition, ...]
    source: ExactEvidence

    def __post_init__(self) -> None:
        require_token(self.evidence_id, "RatingMigrationEvidence.evidence_id")
        require_token(self.evidence_version, "RatingMigrationEvidence.evidence_version")
        if self.source.role is not EvidenceRole.EXACT_PIT_INPUT:
            raise ValueError("rating migration requires exact PIT input evidence")
        if (
            self.source.evidence_id != self.evidence_id
            or self.source.version != self.evidence_version
            or self.source.subject_id != self.cohort.cohort_id
            or self.source.curve_role != "rating_migration"
        ):
            raise ValueError("rating source must match id/version/cohort/semantic role")
        if self.transitions != tuple(
            sorted(
                self.transitions,
                key=lambda item: (item.member_id, item.seal_hash),
            )
        ):
            raise ValueError("rating transitions must use canonical member/hash order")
        required_upstreams = {
            self.taxonomy.taxonomy_hash,
            self.cohort.cohort_hash,
            *(transition.seal_hash for transition in self.transitions),
        }
        if not required_upstreams.issubset(set(self.source.upstream_hashes)):
            raise ValueError("rating PIT source must attest all taxonomy/cohort/member hashes")

    @property
    def evidence_hash(self) -> str:
        """Hash the complete taxonomy, denominator, member records, and source seal."""

        return canonical_hash(
            {
                "evidence_id": self.evidence_id,
                "evidence_version": self.evidence_version,
                "taxonomy_hash": self.taxonomy.taxonomy_hash,
                "cohort_hash": self.cohort.cohort_hash,
                "transition_hashes": tuple(item.seal_hash for item in self.transitions),
                "source_hash": self.source.seal_hash,
            }
        )


@dataclass(frozen=True)
class RatingBucketCount:
    """One exact destination bucket count/rate within an origin row."""

    label: str
    kind: RatingTerminalKind
    count: int
    rate: Decimal

    def __post_init__(self) -> None:
        require_token(self.label, "RatingBucketCount.label")
        if self.count < 0:
            raise ValueError("rating bucket count cannot be negative")
        require_finite(self.rate, "RatingBucketCount.rate")
        if not Decimal("0") <= self.rate <= Decimal("1"):
            raise ValueError("rating bucket rate must be in [0, 1]")


@dataclass(frozen=True)
class RatingTransitionRow:
    """One full origin row including live/default/withdrawn/censored/missing."""

    origin_grade: str
    origin_count: int
    buckets: tuple[RatingBucketCount, ...]

    def __post_init__(self) -> None:
        require_token(self.origin_grade, "RatingTransitionRow.origin_grade")
        if self.origin_count <= 0:
            raise ValueError("rating origin denominator must be positive")
        labels = tuple(bucket.label for bucket in self.buckets)
        if len(labels) != len(set(labels)):
            raise ValueError("rating destination bucket labels cannot repeat")
        if sum(bucket.count for bucket in self.buckets) != self.origin_count:
            raise ValueError("rating destination counts must equal origin denominator")
        if any(
            bucket.rate != Decimal(bucket.count) / Decimal(self.origin_count)
            for bucket in self.buckets
        ):
            raise ValueError("rating destination rates are not recomputable")
        if sum((bucket.rate for bucket in self.buckets), start=Decimal("0")) != Decimal("1"):
            raise ValueError("rating destination rates must sum to one")


@dataclass(frozen=True)
class RatingMigrationAssessment:
    """Fully sealed transition matrix retaining the complete origin denominator."""

    status: RatingMigrationStatus
    evaluated_at: datetime
    input_hash: str
    output_hash: str
    policy_hash: str
    taxonomy_hash: str
    cohort_hash: str
    ordered_live_grades: tuple[str, ...]
    default_label: str
    withdrawn_label: str
    destination_labels: tuple[str, ...]
    minimum_cohort_size: int
    minimum_terminal_coverage_ratio: Decimal
    expected_count: int
    live_terminal_count: int
    default_count: int
    withdrawn_count: int
    censored_count: int
    missing_count: int
    terminal_coverage_ratio: Decimal
    missing_evidence_member_ids: tuple[str, ...]
    rows: tuple[RatingTransitionRow, ...]
    blockers: tuple[RatingMigrationBlocker, ...]
    research_only: bool
    must_not_execute: bool
    must_not_use_for_decision: bool

    def __post_init__(self) -> None:
        require_aware(self.evaluated_at, "RatingMigrationAssessment.evaluated_at")
        for name in ("input_hash", "output_hash", "policy_hash", "taxonomy_hash", "cohort_hash"):
            require_sha256(str(getattr(self, name)), f"RatingMigrationAssessment.{name}")
        if not (self.research_only and self.must_not_execute and self.must_not_use_for_decision):
            raise ValueError("rating migration assessment must remain research-only")
        expected_destinations = (
            *self.ordered_live_grades,
            self.default_label,
            self.withdrawn_label,
            _CENSORED_LABEL,
            _MISSING_LABEL,
        )
        if self.destination_labels != expected_destinations:
            raise ValueError("rating destination universe must match taxonomy projection")
        if not self.ordered_live_grades:
            raise ValueError("assessment taxonomy requires live grades")
        taxonomy_labels = (
            *self.ordered_live_grades,
            self.default_label,
            self.withdrawn_label,
        )
        if len(taxonomy_labels) != len(set(taxonomy_labels)):
            raise ValueError("assessment taxonomy projection labels must be unique")
        for label in taxonomy_labels:
            require_token(label, "RatingMigrationAssessment.taxonomy_label")
            if label in {_CENSORED_LABEL, _MISSING_LABEL, _UNRESOLVED_ORIGIN}:
                raise ValueError("assessment taxonomy uses a reserved label")
        if self.minimum_cohort_size <= 0:
            raise ValueError("minimum cohort size must be positive")
        require_finite(self.minimum_terminal_coverage_ratio, "minimum coverage")
        if not Decimal("0") < self.minimum_terminal_coverage_ratio <= Decimal("1"):
            raise ValueError("minimum coverage must be in (0, 1]")
        counts = (
            self.live_terminal_count,
            self.default_count,
            self.withdrawn_count,
            self.censored_count,
            self.missing_count,
        )
        if self.expected_count < 0 or any(count < 0 for count in counts):
            raise ValueError("rating assessment counts cannot be negative")
        if sum(counts) != self.expected_count:
            raise ValueError("rating terminal buckets must always equal expected cohort")
        if sum(row.origin_count for row in self.rows) != self.expected_count:
            raise ValueError("rating origin rows must always equal expected cohort")
        for row in self.rows:
            if tuple(bucket.label for bucket in row.buckets) != self.destination_labels:
                raise ValueError("rating rows must use the exact destination universe")
            for bucket, label in zip(row.buckets, self.destination_labels, strict=True):
                if bucket.kind is not _bucket_kind(
                    label,
                    default_label=self.default_label,
                    withdrawn_label=self.withdrawn_label,
                ):
                    raise ValueError("rating bucket kind does not match destination label")
        if self.rows != tuple(sorted(self.rows, key=lambda row: row.origin_grade)):
            raise ValueError("rating rows must use canonical origin order")
        valid_origins = {
            *self.ordered_live_grades,
            self.default_label,
            _UNRESOLVED_ORIGIN,
        }
        if any(row.origin_grade not in valid_origins for row in self.rows):
            raise ValueError("rating row origin falls outside taxonomy projection")
        covered = self.live_terminal_count + self.default_count + self.withdrawn_count
        totals = {
            label: sum(
                next(bucket.count for bucket in row.buckets if bucket.label == label)
                for row in self.rows
            )
            for label in self.destination_labels
        }
        if (
            self.live_terminal_count != sum(totals[grade] for grade in self.ordered_live_grades)
            or self.default_count != totals[self.default_label]
            or self.withdrawn_count != totals[self.withdrawn_label]
            or self.censored_count != totals[_CENSORED_LABEL]
            or self.missing_count != totals[_MISSING_LABEL]
        ):
            raise ValueError("rating top-level bucket counts must equal matrix rows")
        expected_coverage = (
            Decimal(covered) / Decimal(self.expected_count)
            if self.expected_count > 0
            else Decimal("0")
        )
        require_finite(self.terminal_coverage_ratio, "terminal_coverage_ratio")
        if self.terminal_coverage_ratio != expected_coverage:
            raise ValueError("rating terminal coverage is not recomputable")
        if not Decimal("0") <= self.terminal_coverage_ratio <= Decimal("1"):
            raise ValueError("rating terminal coverage must be in [0, 1]")
        if self.missing_evidence_member_ids != tuple(sorted(set(self.missing_evidence_member_ids))):
            raise ValueError("missing member ids must be unique and canonical")
        if self.blockers != tuple(
            sorted(set(self.blockers), key=lambda item: (item.code.value, item.detail))
        ):
            raise ValueError("rating blockers must be unique and canonical")
        if self.status is RatingMigrationStatus.AVAILABLE:
            if (
                self.blockers
                or self.expected_count < self.minimum_cohort_size
                or self.terminal_coverage_ratio < self.minimum_terminal_coverage_ratio
            ):
                raise ValueError("available rating matrix violates policy gates")
        elif not self.blockers:
            raise ValueError("blocked rating matrix requires blockers")
        if self.output_hash != self.calculated_output_hash:
            raise ValueError("rating migration output hash mismatch")

    @property
    def calculated_output_hash(self) -> str:
        """Recompute every row/count/coverage/blocker and safety field."""

        return canonical_hash(
            {
                "status": self.status,
                "evaluated_at": self.evaluated_at,
                "input_hash": self.input_hash,
                "policy_hash": self.policy_hash,
                "taxonomy_hash": self.taxonomy_hash,
                "cohort_hash": self.cohort_hash,
                "ordered_live_grades": self.ordered_live_grades,
                "default_label": self.default_label,
                "withdrawn_label": self.withdrawn_label,
                "destination_labels": self.destination_labels,
                "minimum_cohort_size": self.minimum_cohort_size,
                "minimum_terminal_coverage_ratio": self.minimum_terminal_coverage_ratio,
                "expected_count": self.expected_count,
                "live_terminal_count": self.live_terminal_count,
                "default_count": self.default_count,
                "withdrawn_count": self.withdrawn_count,
                "censored_count": self.censored_count,
                "missing_count": self.missing_count,
                "terminal_coverage_ratio": self.terminal_coverage_ratio,
                "missing_evidence_member_ids": self.missing_evidence_member_ids,
                "rows": self.rows,
                "blockers": self.blockers,
                "research_only": self.research_only,
                "must_not_execute": self.must_not_execute,
                "must_not_use_for_decision": self.must_not_use_for_decision,
            }
        )


def _bucket_kind(
    label: str,
    *,
    default_label: str,
    withdrawn_label: str,
) -> RatingTerminalKind:
    if label == _CENSORED_LABEL:
        return RatingTerminalKind.CENSORED
    if label == _MISSING_LABEL:
        return RatingTerminalKind.MISSING
    if label == default_label:
        return RatingTerminalKind.DEFAULT
    if label == withdrawn_label:
        return RatingTerminalKind.WITHDRAWN
    return RatingTerminalKind.LIVE_GRADE


def rating_migration_input_hash(
    evidence: RatingMigrationEvidence,
    policy: RatingMigrationPolicy,
    *,
    evaluated_at: datetime,
) -> str:
    """Hash taxonomy, cohort, all owner records, policy, and PIT cutoff."""

    require_aware(evaluated_at, "evaluated_at")
    return canonical_hash(
        {
            "evidence_hash": evidence.evidence_hash,
            "policy_hash": policy.policy_hash,
            "evaluated_at": evaluated_at,
        }
    )


def _blocker(
    code: RatingMigrationBlockerCode,
    detail: str,
) -> RatingMigrationBlocker:
    return RatingMigrationBlocker(code=code, detail=detail)


def _normalized_terminal_label(
    transition: RatingMemberTransition,
    taxonomy: RatingTaxonomy,
) -> str:
    if transition.terminal_kind is RatingTerminalKind.DEFAULT:
        return taxonomy.default_label
    if transition.terminal_kind is RatingTerminalKind.WITHDRAWN:
        return taxonomy.withdrawn_label
    if transition.terminal_kind is RatingTerminalKind.CENSORED:
        return _CENSORED_LABEL
    if transition.terminal_kind is RatingTerminalKind.MISSING:
        return _MISSING_LABEL
    if transition.destination_label in taxonomy.ordered_live_grades:
        return transition.destination_label
    return _MISSING_LABEL


def _build_rows(
    evidence: RatingMigrationEvidence,
) -> tuple[
    tuple[RatingTransitionRow, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    taxonomy = evidence.taxonomy
    destination_labels = (
        *taxonomy.ordered_live_grades,
        taxonomy.default_label,
        taxonomy.withdrawn_label,
        _CENSORED_LABEL,
        _MISSING_LABEL,
    )
    by_member: dict[str, list[RatingMemberTransition]] = {}
    for transition in evidence.transitions:
        by_member.setdefault(transition.member_id, []).append(transition)
    normalized: list[tuple[str, str]] = []
    missing_ids: list[str] = []
    known_origins = {*taxonomy.ordered_live_grades, taxonomy.default_label}
    for member_id in evidence.cohort.expected_member_ids:
        records = by_member.get(member_id, [])
        if len(records) != 1:
            normalized.append((_UNRESOLVED_ORIGIN, _MISSING_LABEL))
            missing_ids.append(member_id)
            continue
        transition = records[0]
        origin = (
            transition.origin_grade
            if transition.origin_grade in known_origins
            else _UNRESOLVED_ORIGIN
        )
        normalized.append((origin, _normalized_terminal_label(transition, taxonomy)))
    rows: list[RatingTransitionRow] = []
    for origin in sorted({item[0] for item in normalized}):
        origin_items = tuple(item for item in normalized if item[0] == origin)
        origin_count = len(origin_items)
        buckets = tuple(
            RatingBucketCount(
                label=label,
                kind=_bucket_kind(
                    label,
                    default_label=taxonomy.default_label,
                    withdrawn_label=taxonomy.withdrawn_label,
                ),
                count=sum(item[1] == label for item in origin_items),
                rate=Decimal(sum(item[1] == label for item in origin_items))
                / Decimal(origin_count),
            )
            for label in destination_labels
        )
        rows.append(
            RatingTransitionRow(
                origin_grade=origin,
                origin_count=origin_count,
                buckets=buckets,
            )
        )
    return tuple(rows), destination_labels, tuple(missing_ids)


def _make_result(
    *,
    status: RatingMigrationStatus,
    evaluated_at: datetime,
    input_hash: str,
    policy: RatingMigrationPolicy,
    evidence: RatingMigrationEvidence,
    blockers: tuple[RatingMigrationBlocker, ...],
) -> RatingMigrationAssessment:
    rows, destination_labels, missing_member_ids = _build_rows(evidence)
    totals = Counter[str]()
    for row in rows:
        for bucket in row.buckets:
            totals[bucket.label] += bucket.count
    live_count = sum(totals[grade] for grade in evidence.taxonomy.ordered_live_grades)
    expected_count = len(evidence.cohort.expected_member_ids)
    default_count = totals[evidence.taxonomy.default_label]
    withdrawn_count = totals[evidence.taxonomy.withdrawn_label]
    censored_count = totals[_CENSORED_LABEL]
    missing_count = totals[_MISSING_LABEL]
    coverage = Decimal(live_count + default_count + withdrawn_count) / Decimal(expected_count)
    payload = {
        "status": status,
        "evaluated_at": evaluated_at,
        "input_hash": input_hash,
        "policy_hash": policy.policy_hash,
        "taxonomy_hash": evidence.taxonomy.taxonomy_hash,
        "cohort_hash": evidence.cohort.cohort_hash,
        "ordered_live_grades": evidence.taxonomy.ordered_live_grades,
        "default_label": evidence.taxonomy.default_label,
        "withdrawn_label": evidence.taxonomy.withdrawn_label,
        "destination_labels": destination_labels,
        "minimum_cohort_size": policy.minimum_cohort_size,
        "minimum_terminal_coverage_ratio": policy.minimum_terminal_coverage_ratio,
        "expected_count": expected_count,
        "live_terminal_count": live_count,
        "default_count": default_count,
        "withdrawn_count": withdrawn_count,
        "censored_count": censored_count,
        "missing_count": missing_count,
        "terminal_coverage_ratio": coverage,
        "missing_evidence_member_ids": missing_member_ids,
        "rows": rows,
        "blockers": blockers,
        "research_only": True,
        "must_not_execute": True,
        "must_not_use_for_decision": True,
    }
    return RatingMigrationAssessment(
        output_hash=canonical_hash(payload),
        status=status,
        evaluated_at=evaluated_at,
        input_hash=input_hash,
        policy_hash=policy.policy_hash,
        taxonomy_hash=evidence.taxonomy.taxonomy_hash,
        cohort_hash=evidence.cohort.cohort_hash,
        ordered_live_grades=evidence.taxonomy.ordered_live_grades,
        default_label=evidence.taxonomy.default_label,
        withdrawn_label=evidence.taxonomy.withdrawn_label,
        destination_labels=destination_labels,
        minimum_cohort_size=policy.minimum_cohort_size,
        minimum_terminal_coverage_ratio=policy.minimum_terminal_coverage_ratio,
        expected_count=expected_count,
        live_terminal_count=live_count,
        default_count=default_count,
        withdrawn_count=withdrawn_count,
        censored_count=censored_count,
        missing_count=missing_count,
        terminal_coverage_ratio=coverage,
        missing_evidence_member_ids=missing_member_ids,
        rows=rows,
        blockers=blockers,
        research_only=True,
        must_not_execute=True,
        must_not_use_for_decision=True,
    )


from apps.fixed_income.domain.rating_migration_evaluation import (  # noqa: E402
    evaluate_rating_migration,
)

__all__ = [
    "RatingBucketCount",
    "RatingCensoringConvention",
    "RatingCohort",
    "RatingDenominatorConvention",
    "RatingMemberTransition",
    "RatingMigrationAssessment",
    "RatingMigrationBlocker",
    "RatingMigrationBlockerCode",
    "RatingMigrationEvidence",
    "RatingMigrationPolicy",
    "RatingMigrationStatus",
    "RatingTaxonomy",
    "RatingTerminalKind",
    "RatingTerminalSelection",
    "RatingTransitionRow",
    "evaluate_rating_migration",
    "rating_migration_input_hash",
]
