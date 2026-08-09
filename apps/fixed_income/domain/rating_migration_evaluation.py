"""Rating-migration evaluation orchestration split from its contracts."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from apps.fixed_income.domain.evidence import require_aware, require_sha256
from apps.fixed_income.domain.rating_migration import (
    RatingMigrationAssessment,
    RatingMigrationBlocker,
    RatingMigrationBlockerCode,
    RatingMigrationEvidence,
    RatingMigrationPolicy,
    RatingMigrationStatus,
    RatingTerminalKind,
    _blocker,
    _make_result,
    rating_migration_input_hash,
)


def evaluate_rating_migration(
    evidence: RatingMigrationEvidence,
    *,
    policy: RatingMigrationPolicy,
    evaluated_at: datetime,
    expected_input_hash: str | None = None,
) -> RatingMigrationAssessment:
    """Build a PIT matrix without survivor-only or late-outcome backfill."""

    require_aware(evaluated_at, "evaluated_at")
    input_hash = rating_migration_input_hash(
        evidence,
        policy,
        evaluated_at=evaluated_at,
    )
    blockers: list[RatingMigrationBlocker] = []
    if expected_input_hash is not None:
        require_sha256(expected_input_hash, "expected_input_hash")
        if expected_input_hash != input_hash:
            blockers.append(
                _blocker(RatingMigrationBlockerCode.INPUT_HASH_MISMATCH, "input hash mismatch")
            )
    cohort = evidence.cohort
    taxonomy = evidence.taxonomy
    expected_horizon = cohort.formation_at + timedelta(days=policy.horizon_days)
    terminal_cutoff = cohort.horizon_ends_at + timedelta(
        seconds=policy.outcome_availability_grace_seconds
    )
    if cohort.formation_at > policy.formation_cutoff or cohort.horizon_ends_at != expected_horizon:
        blockers.append(
            _blocker(
                RatingMigrationBlockerCode.COHORT_HORIZON_MISMATCH,
                "cohort formation or horizon mismatches policy",
            )
        )
    if evaluated_at < terminal_cutoff:
        blockers.append(
            _blocker(
                RatingMigrationBlockerCode.COHORT_INCOMPLETE,
                "cohort horizon and release grace are incomplete",
            )
        )
    if len(cohort.expected_member_ids) < policy.minimum_cohort_size:
        blockers.append(
            _blocker(
                RatingMigrationBlockerCode.COHORT_TOO_SMALL,
                "cohort is below minimum size",
            )
        )
    for exact in (policy.evidence, taxonomy.evidence, cohort.evidence):
        if exact.observed_at > cohort.formation_at or exact.available_at > cohort.formation_at:
            blockers.append(
                _blocker(
                    RatingMigrationBlockerCode.POLICY_NOT_PREREGISTERED,
                    "policy/taxonomy/cohort was not knowable at formation",
                )
            )
        elif exact.valid_until <= cohort.formation_at:
            blockers.append(
                _blocker(
                    RatingMigrationBlockerCode.EVIDENCE_STALE,
                    "policy/taxonomy/cohort was inactive at formation",
                )
            )
    source_reason = evidence.source.usability_reason(evaluated_at)
    if source_reason == "evidence_from_future":
        blockers.append(
            _blocker(
                RatingMigrationBlockerCode.EVIDENCE_FROM_FUTURE,
                "rating PIT source is from the future",
            )
        )
    elif source_reason == "evidence_stale":
        blockers.append(
            _blocker(
                RatingMigrationBlockerCode.EVIDENCE_STALE,
                "rating PIT source is stale",
            )
        )
    member_counts = Counter(transition.member_id for transition in evidence.transitions)
    expected_ids = set(cohort.expected_member_ids)
    if any(count > 1 for count in member_counts.values()):
        blockers.append(
            _blocker(
                RatingMigrationBlockerCode.COHORT_MEMBER_DUPLICATE,
                "duplicate member transition evidence",
            )
        )
    if expected_ids - set(member_counts):
        blockers.append(
            _blocker(
                RatingMigrationBlockerCode.COHORT_MEMBER_MISSING,
                "expected member evidence is missing",
            )
        )
    if set(member_counts) - expected_ids:
        blockers.append(
            _blocker(
                RatingMigrationBlockerCode.COHORT_MEMBER_UNEXPECTED,
                "unexpected member evidence is present",
            )
        )
    known_origins = {*taxonomy.ordered_live_grades, taxonomy.default_label}
    for transition in evidence.transitions:
        expected_selection_role = f"rating_terminal_selection:{policy.terminal_selection.value}"
        if (
            transition.terminal_publication.curve_role != expected_selection_role
            or policy.policy_hash not in transition.terminal_publication.upstream_hashes
        ):
            blockers.append(
                _blocker(
                    RatingMigrationBlockerCode.TERMINAL_SELECTION_MISMATCH,
                    "terminal selection does not bind exact policy/convention",
                )
            )
        if (
            transition.taxonomy_id != taxonomy.taxonomy_id
            or transition.taxonomy_version != taxonomy.taxonomy_version
        ):
            blockers.append(
                _blocker(
                    RatingMigrationBlockerCode.TAXONOMY_MISMATCH,
                    "transition taxonomy id/version mismatch",
                )
            )
        if transition.origin_grade not in known_origins or (
            transition.terminal_kind is RatingTerminalKind.LIVE_GRADE
            and transition.destination_label not in taxonomy.ordered_live_grades
        ):
            blockers.append(
                _blocker(
                    RatingMigrationBlockerCode.TAXONOMY_GRADE_UNKNOWN,
                    "origin or destination grade is unknown",
                )
            )
        if (
            transition.terminal_kind is RatingTerminalKind.DEFAULT
            and transition.destination_label != taxonomy.default_label
        ) or (
            transition.terminal_kind is RatingTerminalKind.WITHDRAWN
            and transition.destination_label != taxonomy.withdrawn_label
        ):
            blockers.append(
                _blocker(
                    RatingMigrationBlockerCode.TAXONOMY_MISMATCH,
                    "terminal label does not match taxonomy semantics",
                )
            )
        if (
            transition.origin_observed_at > cohort.formation_at
            or transition.origin_available_at > cohort.formation_at
            or transition.origin_publication.valid_until <= cohort.formation_at
        ):
            blockers.append(
                _blocker(
                    RatingMigrationBlockerCode.ORIGIN_AFTER_FORMATION,
                    "origin rating was not knowable at formation",
                )
            )
        if transition.outcome_observed_at is not None and not (
            cohort.formation_at <= transition.outcome_observed_at <= cohort.horizon_ends_at
        ):
            blockers.append(
                _blocker(
                    RatingMigrationBlockerCode.OUTCOME_AFTER_HORIZON,
                    "terminal event falls outside cohort horizon",
                )
            )
        if transition.outcome_available_at is not None:
            if transition.outcome_available_at > evaluated_at:
                blockers.append(
                    _blocker(
                        RatingMigrationBlockerCode.OUTCOME_FROM_FUTURE,
                        "terminal event was unavailable at evaluation cutoff",
                    )
                )
            if transition.outcome_available_at > terminal_cutoff:
                blockers.append(
                    _blocker(
                        RatingMigrationBlockerCode.OUTCOME_AVAILABLE_LATE,
                        "late outcome cannot backfill the horizon bucket",
                    )
                )
        if transition.outcome_observed_at is not None and (
            transition.selection_observed_at < transition.outcome_observed_at
            or transition.selection_available_at
            < (transition.outcome_available_at or transition.outcome_observed_at)
        ):
            blockers.append(
                _blocker(
                    RatingMigrationBlockerCode.TERMINAL_SELECTION_MISMATCH,
                    "terminal selection predates selected outcome",
                )
            )
        if (
            transition.selection_observed_at < cohort.formation_at
            or transition.selection_observed_at > cohort.horizon_ends_at
            or transition.selection_available_at > terminal_cutoff
            or transition.selection_available_at > evaluated_at
        ):
            blockers.append(
                _blocker(
                    RatingMigrationBlockerCode.TERMINAL_SELECTION_MISMATCH,
                    "terminal selection seal falls outside exact horizon/grace",
                )
            )
        if transition.terminal_kind is RatingTerminalKind.CENSORED and (
            transition.censored_at is None
            or not cohort.formation_at <= transition.censored_at <= cohort.horizon_ends_at
        ):
            blockers.append(
                _blocker(
                    RatingMigrationBlockerCode.CENSORING_INVALID,
                    "censor clock falls outside cohort horizon",
                )
            )
        if (
            transition.terminal_kind is RatingTerminalKind.CENSORED
            and transition.censored_at is not None
            and (
                transition.selection_observed_at < transition.censored_at
                or transition.selection_available_at < transition.censored_at
            )
        ):
            blockers.append(
                _blocker(
                    RatingMigrationBlockerCode.TERMINAL_SELECTION_MISMATCH,
                    "terminal selection predates censoring evidence",
                )
            )
        if (
            transition.terminal_kind is RatingTerminalKind.MISSING
            and transition.selection_observed_at < cohort.horizon_ends_at
        ):
            blockers.append(
                _blocker(
                    RatingMigrationBlockerCode.TERMINAL_SELECTION_MISMATCH,
                    "MISSING terminal selection predates cohort horizon",
                )
            )
        if transition.origin_grade == taxonomy.default_label and not (
            transition.terminal_kind is RatingTerminalKind.DEFAULT
            and transition.destination_label == taxonomy.default_label
        ):
            blockers.append(
                _blocker(
                    RatingMigrationBlockerCode.DEFAULT_NOT_ABSORBING,
                    "DEFAULT origin must remain DEFAULT",
                )
            )
    provisional = _make_result(
        status=RatingMigrationStatus.BLOCKED,
        evaluated_at=evaluated_at,
        input_hash=input_hash,
        policy=policy,
        evidence=evidence,
        blockers=(
            _blocker(
                RatingMigrationBlockerCode.COVERAGE_INSUFFICIENT,
                "provisional coverage check",
            ),
        ),
    )
    if provisional.terminal_coverage_ratio < policy.minimum_terminal_coverage_ratio:
        blockers.append(
            _blocker(
                RatingMigrationBlockerCode.COVERAGE_INSUFFICIENT,
                "terminal coverage is below policy minimum",
            )
        )
    unique_blockers = tuple(sorted(set(blockers), key=lambda item: (item.code.value, item.detail)))
    return _make_result(
        status=(
            RatingMigrationStatus.BLOCKED if unique_blockers else RatingMigrationStatus.AVAILABLE
        ),
        evaluated_at=evaluated_at,
        input_hash=input_hash,
        policy=policy,
        evidence=evidence,
        blockers=unique_blockers,
    )


__all__ = ["evaluate_rating_migration"]
