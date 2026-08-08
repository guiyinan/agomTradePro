"""Cohort-denominator and PIT coverage for R5 rating migration."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

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


def test_rating_taxonomy_and_cohort_reject_incomplete_owner_contracts() -> None:
    taxonomy = _taxonomy()
    for mutation, match in (
        ({"ordered_live_grades": ()}, "ordered live grades"),
        ({"ordered_live_grades": ("AAA", "AAA")}, "unique"),
        ({"ordered_live_grades": ("CENSORED",)}, "reserved"),
        ({"evidence": replace(taxonomy.evidence, subject_id="other")}, "must match"),
    ):
        with pytest.raises(ValueError, match=match):
            replace(taxonomy, **mutation)

    cohort = _cohort()
    for mutation, match in (
        ({"horizon_ends_at": cohort.formation_at}, "horizon"),
        ({"expected_member_ids": ()}, "expected members"),
        ({"expected_member_ids": ("bond-b", "bond-a")}, "canonical"),
        ({"expected_member_ids": ("bond-a", "bond-a")}, "canonical"),
        ({"evidence": replace(cohort.evidence, subject_id="other")}, "must match"),
    ):
        with pytest.raises(ValueError, match=match):
            replace(cohort, **mutation)


def test_rating_member_transition_rejects_ambiguous_terminal_states() -> None:
    policy = _policy()
    transition = _transition(
        "bond-a",
        "AAA",
        RatingTerminalKind.LIVE_GRADE,
        "AA",
        policy,
    )
    for mutation, match in (
        ({"terminal_kind": "live"}, "terminal kind"),
        (
            {"origin_available_at": transition.origin_observed_at - timedelta(seconds=1)},
            "origin availability",
        ),
        (
            {"selection_available_at": transition.selection_observed_at - timedelta(seconds=1)},
            "selection availability",
        ),
        ({"destination_label": None}, "destination label"),
        ({"outcome_observed_at": None}, "outcome clocks"),
        (
            {"outcome_available_at": transition.outcome_observed_at - timedelta(seconds=1)},
            "outcome availability",
        ),
        ({"censored_at": transition.outcome_observed_at}, "also be censored"),
        (
            {"origin_publication": replace(transition.origin_publication, subject_id="other")},
            "origin rating",
        ),
        (
            {
                "terminal_publication": replace(
                    transition.terminal_publication,
                    curve_role="wrong",
                )
            },
            "terminal selection clocks",
        ),
        ({"origin_record_hash": "0" * 64}, "origin record hash"),
        ({"terminal_record_hash": "0" * 64}, "terminal record hash"),
    ):
        with pytest.raises(ValueError, match=match):
            replace(transition, **mutation)

    censored = replace(
        transition,
        terminal_kind=RatingTerminalKind.CENSORED,
        destination_label=None,
        outcome_observed_at=None,
        outcome_available_at=None,
        censored_at=transition.outcome_observed_at,
    )
    with pytest.raises(ValueError, match="censor clock"):
        replace(censored, censored_at=None)
    with pytest.raises(ValueError, match="cannot carry terminal outcome"):
        replace(censored, destination_label="AA")

    missing = replace(censored, terminal_kind=RatingTerminalKind.MISSING, censored_at=None)
    with pytest.raises(ValueError, match="cannot carry synthesized"):
        replace(missing, censored_at=transition.outcome_observed_at)


def test_rating_policy_and_input_evidence_fail_closed() -> None:
    policy = _policy()
    for mutation, match in (
        ({"horizon_days": 0}, "horizon"),
        ({"outcome_availability_grace_seconds": -1}, "horizon"),
        ({"minimum_cohort_size": 0}, "cohort size"),
        ({"minimum_terminal_coverage_ratio": Decimal("0")}, "coverage"),
        ({"denominator_convention": "survivors"}, "full origin"),
        ({"censoring_convention": "drop"}, "denominator bucket"),
        ({"terminal_selection": "latest"}, "selection semantics"),
        ({"evidence": replace(policy.evidence, subject_id="other")}, "must match"),
    ):
        with pytest.raises(ValueError, match=match):
            replace(policy, **mutation)

    transition_a = _transition("bond-a", "AAA", RatingTerminalKind.LIVE_GRADE, "AA", policy)
    transition_b = _transition("bond-b", "BBB", RatingTerminalKind.DEFAULT, "DEFAULT", policy)
    evidence = _evidence((transition_a, transition_b))
    with pytest.raises(ValueError, match="canonical"):
        replace(evidence, transitions=(transition_b, transition_a))
    with pytest.raises(ValueError, match="attest"):
        replace(
            evidence,
            source=replace(evidence.source, upstream_hashes=()),
        )


def test_rating_assessment_rejects_tampered_counts_status_and_hash() -> None:
    policy = _policy()
    result = evaluate_rating_migration(
        _evidence(
            (
                _transition("bond-a", "AAA", RatingTerminalKind.LIVE_GRADE, "AA", policy),
                _transition("bond-b", "BBB", RatingTerminalKind.DEFAULT, "DEFAULT", policy),
            )
        ),
        policy=policy,
        evaluated_at=_EVALUATED_AT,
    )
    for mutation, match in (
        ({"expected_count": -1}, "cannot be negative"),
        ({"live_terminal_count": 0}, "buckets"),
        ({"terminal_coverage_ratio": Decimal("0.5")}, "recomputable"),
        ({"missing_evidence_member_ids": ("z", "a")}, "canonical"),
        ({"status": RatingMigrationStatus.BLOCKED}, "requires blockers"),
        ({"output_hash": "0" * 64}, "hash mismatch"),
    ):
        with pytest.raises(ValueError, match=match):
            replace(result, **mutation)


def test_rating_evaluator_surfaces_semantic_and_cutoff_blockers() -> None:
    policy = _policy()
    base = _transition(
        "bond-a",
        "AAA",
        RatingTerminalKind.LIVE_GRADE,
        "AA",
        policy,
    )
    semantic_mismatch = replace(
        base,
        taxonomy_id="other-taxonomy",
        origin_grade="UNKNOWN",
        terminal_publication=replace(
            base.terminal_publication,
            upstream_hashes=(),
        ),
    )
    evidence = _evidence((semantic_mismatch,))
    result = evaluate_rating_migration(
        evidence,
        policy=replace(policy, minimum_cohort_size=3),
        evaluated_at=_HORIZON,
        expected_input_hash="0" * 64,
    )
    codes = {blocker.code for blocker in result.blockers}
    assert {
        RatingMigrationBlockerCode.INPUT_HASH_MISMATCH,
        RatingMigrationBlockerCode.COHORT_INCOMPLETE,
        RatingMigrationBlockerCode.COHORT_TOO_SMALL,
        RatingMigrationBlockerCode.COHORT_MEMBER_MISSING,
        RatingMigrationBlockerCode.TERMINAL_SELECTION_MISMATCH,
        RatingMigrationBlockerCode.TAXONOMY_MISMATCH,
        RatingMigrationBlockerCode.TAXONOMY_GRADE_UNKNOWN,
    } <= codes
