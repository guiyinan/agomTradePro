"""Cohort-denominator and PIT coverage for R5 rating migration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.fixed_income.domain.evidence import EvidenceRole, ExactEvidence, canonical_hash
from apps.fixed_income.domain.rating_migration import (
    RatingCensoringConvention,
    RatingCohort,
    RatingDenominatorConvention,
    RatingMemberTransition,
    RatingMigrationBlockerCode,
    RatingMigrationEvidence,
    RatingMigrationPolicy,
    RatingMigrationStatus,
    RatingTaxonomy,
    RatingTerminalKind,
    RatingTerminalSelection,
    evaluate_rating_migration,
)

_FORMATION = datetime(2025, 1, 1, tzinfo=UTC)
_HORIZON = datetime(2026, 1, 1, tzinfo=UTC)
_EVALUATED_AT = datetime(2026, 1, 3, tzinfo=UTC)
_VALID_UNTIL = datetime(2027, 1, 1, tzinfo=UTC)


def _digest(value: str) -> str:
    return canonical_hash({"value": value})


def _exact(
    *,
    role: EvidenceRole,
    evidence_id: str,
    version: str,
    subject_id: str,
    observed_at: datetime,
    available_at: datetime,
    content_hash: str,
    curve_role: str,
    upstream_hashes: tuple[str, ...] = (),
) -> ExactEvidence:
    return ExactEvidence(
        role=role,
        owner="research" if role is EvidenceRole.POLICY else "data_center",
        evidence_id=evidence_id,
        version=version,
        subject_id=subject_id,
        content_hash=content_hash,
        observed_at=observed_at,
        available_at=available_at,
        valid_until=_VALID_UNTIL,
        currency=None,
        curve_role=curve_role,
        upstream_hashes=tuple(sorted(upstream_hashes)),
    )


def _policy() -> RatingMigrationPolicy:
    evidence = _exact(
        role=EvidenceRole.POLICY,
        evidence_id="rating-policy",
        version="v1",
        subject_id="rating-policy",
        observed_at=datetime(2024, 12, 1, tzinfo=UTC),
        available_at=datetime(2024, 12, 2, tzinfo=UTC),
        content_hash=_digest("rating-policy"),
        curve_role="rating_migration_policy",
    )
    return RatingMigrationPolicy(
        policy_id="rating-policy",
        policy_version="v1",
        formation_cutoff=_FORMATION,
        horizon_days=365,
        outcome_availability_grace_seconds=86400,
        minimum_cohort_size=2,
        minimum_terminal_coverage_ratio=Decimal("1"),
        denominator_convention=RatingDenominatorConvention.ORIGIN_COHORT_ALL,
        censoring_convention=RatingCensoringConvention.RETAIN_AS_BUCKET,
        terminal_selection=(RatingTerminalSelection.EARLIEST_EVENT_DEFAULT_PRECEDENCE),
        evidence=evidence,
    )


def _taxonomy() -> RatingTaxonomy:
    return RatingTaxonomy(
        agency_id="agency",
        taxonomy_id="rating-taxonomy",
        taxonomy_version="v1",
        ordered_live_grades=("AAA", "AA", "BBB"),
        default_label="DEFAULT",
        withdrawn_label="WITHDRAWN",
        evidence=_exact(
            role=EvidenceRole.PUBLICATION,
            evidence_id="rating-taxonomy-publication",
            version="v1",
            subject_id="rating-taxonomy",
            observed_at=datetime(2024, 12, 1, tzinfo=UTC),
            available_at=datetime(2024, 12, 2, tzinfo=UTC),
            content_hash=_digest("taxonomy"),
            curve_role="rating_taxonomy",
        ),
    )


def _cohort() -> RatingCohort:
    return RatingCohort(
        cohort_id="rating-cohort",
        cohort_version="v1",
        formation_at=_FORMATION,
        horizon_ends_at=_HORIZON,
        expected_member_ids=("bond-a", "bond-b"),
        evidence=_exact(
            role=EvidenceRole.EXACT_PIT_INPUT,
            evidence_id="rating-cohort",
            version="v1",
            subject_id="rating-cohort",
            observed_at=datetime(2024, 12, 31, tzinfo=UTC),
            available_at=_FORMATION,
            content_hash=_digest("cohort"),
            curve_role="rating_cohort",
        ),
    )


def _transition(
    member_id: str,
    origin: str,
    terminal: RatingTerminalKind,
    destination: str,
    policy: RatingMigrationPolicy,
) -> RatingMemberTransition:
    origin_hash = _digest(f"origin-{member_id}")
    terminal_hash = _digest(f"terminal-{member_id}")
    outcome_observed = datetime(2025, 6, 1, tzinfo=UTC)
    outcome_available = outcome_observed + timedelta(days=1)
    selection_available = _HORIZON + timedelta(hours=12)
    origin_publication = _exact(
        role=EvidenceRole.PUBLICATION,
        evidence_id=f"origin-{member_id}",
        version="v1",
        subject_id=member_id,
        observed_at=datetime(2024, 12, 30, tzinfo=UTC),
        available_at=datetime(2024, 12, 31, tzinfo=UTC),
        content_hash=origin_hash,
        curve_role="rating_origin",
    )
    terminal_publication = _exact(
        role=EvidenceRole.PUBLICATION,
        evidence_id=f"terminal-{member_id}",
        version="v1",
        subject_id=member_id,
        observed_at=_HORIZON,
        available_at=selection_available,
        content_hash=terminal_hash,
        curve_role=("rating_terminal_selection:" f"{policy.terminal_selection.value}"),
        upstream_hashes=(policy.policy_hash,),
    )
    return RatingMemberTransition(
        member_id=member_id,
        taxonomy_id="rating-taxonomy",
        taxonomy_version="v1",
        origin_grade=origin,
        terminal_kind=terminal,
        destination_label=destination,
        origin_observed_at=origin_publication.observed_at,
        origin_available_at=origin_publication.available_at,
        outcome_observed_at=outcome_observed,
        outcome_available_at=outcome_available,
        censored_at=None,
        selection_observed_at=_HORIZON,
        selection_available_at=selection_available,
        origin_record_hash=origin_hash,
        terminal_record_hash=terminal_hash,
        origin_publication=origin_publication,
        terminal_publication=terminal_publication,
    )


def _evidence(
    transitions: tuple[RatingMemberTransition, ...],
) -> RatingMigrationEvidence:
    taxonomy = _taxonomy()
    cohort = _cohort()
    upstreams = tuple(
        sorted(
            (
                taxonomy.taxonomy_hash,
                cohort.cohort_hash,
                *(transition.seal_hash for transition in transitions),
            )
        )
    )
    return RatingMigrationEvidence(
        evidence_id="rating-input",
        evidence_version="v1",
        taxonomy=taxonomy,
        cohort=cohort,
        transitions=transitions,
        source=_exact(
            role=EvidenceRole.EXACT_PIT_INPUT,
            evidence_id="rating-input",
            version="v1",
            subject_id="rating-cohort",
            observed_at=_HORIZON,
            available_at=_HORIZON + timedelta(days=1),
            content_hash=_digest("rating-input"),
            curve_role="rating_migration",
            upstream_hashes=upstreams,
        ),
    )


def test_rating_matrix_retains_full_origin_denominator() -> None:
    policy = _policy()
    evidence = _evidence(
        (
            _transition("bond-a", "AAA", RatingTerminalKind.LIVE_GRADE, "AA", policy),
            _transition("bond-b", "BBB", RatingTerminalKind.DEFAULT, "DEFAULT", policy),
        )
    )

    result = evaluate_rating_migration(
        evidence,
        policy=policy,
        evaluated_at=_EVALUATED_AT,
    )

    assert result.status is RatingMigrationStatus.AVAILABLE
    assert result.expected_count == result.live_terminal_count + result.default_count
    assert (result.withdrawn_count, result.censored_count, result.missing_count) == (0, 0, 0)
    assert result.terminal_coverage_ratio == Decimal("1")
    assert sum(row.origin_count for row in result.rows) == 2
    assert result.output_hash == result.calculated_output_hash


def test_missing_member_stays_explicit_and_count_identity_never_relaxes() -> None:
    policy = _policy()
    evidence = _evidence(
        (_transition("bond-a", "AAA", RatingTerminalKind.LIVE_GRADE, "AA", policy),)
    )

    result = evaluate_rating_migration(
        evidence,
        policy=policy,
        evaluated_at=_EVALUATED_AT,
    )

    assert result.status is RatingMigrationStatus.BLOCKED
    assert RatingMigrationBlockerCode.COHORT_MEMBER_MISSING in {
        blocker.code for blocker in result.blockers
    }
    assert result.missing_count == 1
    assert (
        sum(
            (
                result.live_terminal_count,
                result.default_count,
                result.withdrawn_count,
                result.censored_count,
                result.missing_count,
            )
        )
        == result.expected_count
    )
