"""Contracts for exact source clocks, decision purpose, and coverage evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
    qualify_portfolio_risk_source,
)

AS_OF = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)


def _coverage(status: CoverageStatus = CoverageStatus.PARTIAL) -> PortfolioRiskCoverage:
    """Create explicit partial reported-weight coverage for source tests."""

    return PortfolioRiskCoverage(
        status=status,
        precision_basis="reported_nav_weight",
        reported_weight_fraction=Decimal("0.75"),
        expected_item_count=4,
        observed_item_count=3,
    )


def _evidence(**changes: object) -> PortfolioRiskSourceEvidence:
    """Build one well-formed source snapshot with distinct source and system clocks."""

    evidence = PortfolioRiskSourceEvidence(
        source_id="provider:record-1",
        source_record_id="record-1",
        original_payload_sha256="a" * 64,
        observation_precision=SourceObservationPrecision.TIMESTAMP,
        observed_at=AS_OF - timedelta(hours=2),
        observed_on=None,
        available_at=AS_OF - timedelta(hours=1),
        known_at=AS_OF - timedelta(minutes=30),
        decision_cutoff=AS_OF,
        decision_date_cutoff=None,
        valid_until=AS_OF + timedelta(hours=1),
        source_purpose="published_market_fact",
        allowed_purposes=("simulation_plan",),
        restrictions=(),
        must_not_use_for_decision=False,
        coverage=_coverage(),
        effective_on=date(2026, 11, 2),
    )
    return replace(evidence, **changes)


def _qualify(
    evidence: PortfolioRiskSourceEvidence,
    *,
    allowed: tuple[SourceObservationPrecision, ...] = (SourceObservationPrecision.TIMESTAMP,),
) -> tuple[str, ...]:
    """Return stable blockers for the one explicit preview purpose and cutoff."""

    result = qualify_portfolio_risk_source(
        evidence=evidence,
        requested_purpose="simulation_plan",
        allowed_observation_precisions=allowed,
        as_of=AS_OF,
    )
    return result.reason_codes


def test_partial_coverage_is_preserved_without_rejecting_valid_source_clocks() -> None:
    result = qualify_portfolio_risk_source(
        evidence=_evidence(),
        requested_purpose="simulation_plan",
        allowed_observation_precisions=(SourceObservationPrecision.TIMESTAMP,),
        as_of=AS_OF,
    )

    assert result.eligible is True
    assert result.reason_codes == ()
    assert result.eligible is True  # The caller must still bound the uncovered 25%.


def test_missing_original_hash_and_source_clocks_block_without_local_time_fallback() -> None:
    evidence = _evidence(
        original_payload_sha256=None,
        observation_precision=SourceObservationPrecision.UNKNOWN,
        observed_at=None,
        observed_on=None,
        available_at=None,
        known_at=None,
        valid_until=None,
        coverage=PortfolioRiskCoverage(
            status=CoverageStatus.UNKNOWN,
            precision_basis="coverage_not_reported",
        ),
    )

    reasons = _qualify(evidence)

    assert "RISK_SOURCE_ORIGINAL_HASH_UNKNOWN" in reasons
    assert "RISK_SOURCE_OBSERVATION_CLOCK_UNKNOWN" in reasons
    assert "RISK_SOURCE_AVAILABLE_AT_UNKNOWN" in reasons
    assert "RISK_SOURCE_KNOWN_AT_UNKNOWN" in reasons
    assert "RISK_SOURCE_VALID_UNTIL_UNKNOWN" in reasons
    assert "RISK_SOURCE_OBSERVATION_PRECISION_NOT_ALLOWED" in reasons


@pytest.mark.parametrize(
    ("field_name", "reason"),
    (
        ("observed_at", "RISK_SOURCE_OBSERVED_AT_AFTER_CUTOFF"),
        ("available_at", "RISK_SOURCE_AVAILABLE_AT_AFTER_CUTOFF"),
        ("known_at", "RISK_SOURCE_KNOWN_AT_AFTER_CUTOFF"),
    ),
)
def test_future_source_clocks_block(
    field_name: str,
    reason: str,
) -> None:
    evidence = _evidence(**{field_name: AS_OF + timedelta(seconds=1)})

    assert reason in _qualify(evidence)


def test_expired_and_cutoff_mismatched_sources_block() -> None:
    expired = _evidence(valid_until=AS_OF)
    mismatched = _evidence(decision_cutoff=AS_OF - timedelta(seconds=1))

    assert "RISK_SOURCE_EXPIRED_AT_CUTOFF" in _qualify(expired)
    assert "RISK_SOURCE_CUTOFF_MISMATCH" in _qualify(mismatched)


def test_source_permission_and_global_prohibition_block() -> None:
    wrong_purpose = _evidence(allowed_purposes=("historical_research",))
    prohibited = _evidence(must_not_use_for_decision=True)

    assert "RISK_SOURCE_PURPOSE_NOT_ALLOWED" in _qualify(wrong_purpose)
    assert "RISK_SOURCE_PROHIBITED_FOR_DECISION" in _qualify(prohibited)


def test_unconfigured_source_restrictions_block_and_explicit_benign_scope_can_be_accepted() -> None:
    restricted = _evidence(restrictions=("top_10_only",))
    default_result = qualify_portfolio_risk_source(
        evidence=restricted,
        requested_purpose="simulation_plan",
        allowed_observation_precisions=(SourceObservationPrecision.TIMESTAMP,),
        as_of=AS_OF,
    )
    explicit_result = qualify_portfolio_risk_source(
        evidence=restricted,
        requested_purpose="simulation_plan",
        allowed_observation_precisions=(SourceObservationPrecision.TIMESTAMP,),
        as_of=AS_OF,
        allowed_restrictions=("top_10_only",),
    )

    assert "RISK_SOURCE_RESTRICTION_NOT_ALLOWED" in default_result.reason_codes
    assert explicit_result.eligible is True


@pytest.mark.parametrize(
    "restriction", ("must_not_use_for_decision", "research_only", "observation_only")
)
def test_unconditional_source_restrictions_cannot_be_policy_allowed(restriction: str) -> None:
    result = qualify_portfolio_risk_source(
        evidence=_evidence(restrictions=(restriction,)),
        requested_purpose="simulation_plan",
        allowed_observation_precisions=(SourceObservationPrecision.TIMESTAMP,),
        as_of=AS_OF,
        allowed_restrictions=("top_10_only",),
    )

    assert result.eligible is False
    assert "RISK_SOURCE_PROHIBITED_RESTRICTION" in result.reason_codes


def test_research_only_source_purpose_is_blocked_even_if_decision_purpose_is_listed() -> None:
    result = qualify_portfolio_risk_source(
        evidence=_evidence(source_purpose="research_only"),
        requested_purpose="simulation_plan",
        allowed_observation_precisions=(SourceObservationPrecision.TIMESTAMP,),
        as_of=AS_OF,
    )

    assert result.eligible is False
    assert "RISK_SOURCE_PROHIBITED_PURPOSE" in result.reason_codes


def test_date_precision_requires_the_original_date_and_explicit_policy_allowance() -> None:
    evidence = _evidence(
        observation_precision=SourceObservationPrecision.DATE,
        observed_at=None,
        observed_on=date(2026, 11, 2),
        decision_date_cutoff=date(2026, 11, 2),
    )

    result = qualify_portfolio_risk_source(
        evidence=evidence,
        requested_purpose="simulation_plan",
        allowed_observation_precisions=(SourceObservationPrecision.DATE,),
        as_of=AS_OF,
    )

    assert result.eligible is True
    assert result.reason_codes == ()
    assert evidence.observed_at is None


def test_future_date_only_observation_blocks_without_synthetic_midnight() -> None:
    evidence = _evidence(
        observation_precision=SourceObservationPrecision.DATE,
        observed_at=None,
        observed_on=date(2026, 11, 4),
        decision_date_cutoff=date(2026, 11, 3),
    )

    result = qualify_portfolio_risk_source(
        evidence=evidence,
        requested_purpose="simulation_plan",
        allowed_observation_precisions=(SourceObservationPrecision.DATE,),
        as_of=AS_OF,
    )

    assert result.eligible is False
    assert "RISK_SOURCE_OBSERVATION_DATE_AFTER_CUTOFF" in result.reason_codes


def test_date_precision_rejects_missing_date_cutoff() -> None:
    with pytest.raises(ValueError, match="decision_date_cutoff"):
        _evidence(
            observation_precision=SourceObservationPrecision.DATE,
            observed_at=None,
            observed_on=date(2026, 11, 2),
            decision_date_cutoff=None,
        )


def test_complete_coverage_requires_exact_supporting_evidence() -> None:
    with pytest.raises(ValueError, match="complete coverage"):
        PortfolioRiskCoverage(
            status=CoverageStatus.COMPLETE,
            precision_basis="reported_nav_weight",
            reported_weight_fraction=Decimal("0.98"),
        )
