"""PIT and full-seal coverage for R5 historical spread percentiles."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.fixed_income.domain.evidence import (
    EvidenceRole,
    ExactEvidence,
    canonical_hash,
)
from apps.fixed_income.domain.spread_history import (
    CalendarPeriod,
    ExpectedObservationCalendar,
    RevisionSelection,
    SpreadAssessmentStatus,
    SpreadBlockerCode,
    SpreadObservation,
    SpreadObservationState,
    SpreadPercentileAssessment,
    SpreadPercentileEvidence,
    SpreadPercentilePolicy,
    SpreadTieConvention,
    TargetSampleConvention,
    evaluate_spread_percentile,
)

_EVALUATED_AT = datetime(2026, 6, 10, tzinfo=UTC)
_VALID_UNTIL = datetime(2026, 7, 1, tzinfo=UTC)
_SCOPE = "CGB-2Y-10Y"
_CURVE_ROLE = "government:policy_bank"


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
    currency: str | None = "CNY",
    upstream_hashes: tuple[str, ...] = (),
) -> ExactEvidence:
    owner = "research" if role is EvidenceRole.POLICY else "data_center"
    return ExactEvidence(
        role=role,
        owner=owner,
        evidence_id=evidence_id,
        version=version,
        subject_id=subject_id,
        content_hash=content_hash,
        observed_at=observed_at,
        available_at=available_at,
        valid_until=_VALID_UNTIL,
        currency=currency,
        curve_role=curve_role,
        upstream_hashes=tuple(sorted(upstream_hashes)),
    )


def _observation(
    period_id: str,
    value: str,
    *,
    revision: int = 0,
    available_at: datetime | None = None,
    state: SpreadObservationState = SpreadObservationState.OBSERVED,
) -> SpreadObservation:
    observed_at = datetime.fromisoformat(f"{period_id}T00:00:00+00:00")
    actual_available = available_at or observed_at + timedelta(days=1)
    observation_id = f"spread-{period_id}-r{revision}"
    record_hash = _digest(observation_id)
    publication = _exact(
        role=EvidenceRole.PUBLICATION,
        evidence_id=observation_id,
        version=f"r{revision}",
        subject_id=_SCOPE,
        observed_at=observed_at,
        available_at=actual_available,
        content_hash=record_hash,
        curve_role=_CURVE_ROLE,
    )
    return SpreadObservation(
        observation_id=observation_id,
        observation_version=f"r{revision}",
        revision_number=revision,
        period_id=period_id,
        scope_id=_SCOPE,
        spread_definition_id="spread-definition",
        spread_definition_version="v1",
        currency="CNY",
        numerator_curve_role="government",
        denominator_curve_role="policy_bank",
        state=state,
        value_bp=None if state is SpreadObservationState.MISSING else Decimal(value),
        observed_at=observed_at,
        available_at=actual_available,
        record_hash=record_hash,
        publication=publication,
    )


def _calendar() -> ExpectedObservationCalendar:
    periods = (
        CalendarPeriod(
            period_id="2026-01-31",
            starts_at=datetime(2026, 1, 1, tzinfo=UTC),
            ends_at=datetime(2026, 1, 31, tzinfo=UTC),
            expected_release_at=datetime(2026, 2, 1, tzinfo=UTC),
        ),
        CalendarPeriod(
            period_id="2026-02-28",
            starts_at=datetime(2026, 2, 1, tzinfo=UTC),
            ends_at=datetime(2026, 2, 28, tzinfo=UTC),
            expected_release_at=datetime(2026, 3, 1, tzinfo=UTC),
        ),
    )
    manifest_hash = canonical_hash({"scope_id": _SCOPE, "periods": periods})
    return ExpectedObservationCalendar(
        scope_id=_SCOPE,
        evidence=_exact(
            role=EvidenceRole.CALENDAR,
            evidence_id="spread-calendar",
            version="v1",
            subject_id=_SCOPE,
            observed_at=datetime(2025, 12, 1, tzinfo=UTC),
            available_at=datetime(2025, 12, 2, tzinfo=UTC),
            content_hash=manifest_hash,
            curve_role="spread_observation_calendar",
            currency=None,
        ),
        periods=periods,
    )


def _policy() -> SpreadPercentilePolicy:
    return SpreadPercentilePolicy(
        policy_id="spread-policy",
        policy_version="v1",
        lookback_starts_at=datetime(2026, 1, 1, tzinfo=UTC),
        lookback_ends_at=datetime(2026, 3, 1, tzinfo=UTC),
        minimum_observation_count=2,
        minimum_coverage_ratio=Decimal("1"),
        tie_convention=SpreadTieConvention.MID_RANK,
        target_sample_convention=TargetSampleConvention.EXCLUDED,
        revision_selection=RevisionSelection.LATEST_AVAILABLE_AT_CUTOFF,
        revision_policy_version="v1",
        maximum_release_lag_seconds=86400 * 3,
        allow_estimated=False,
        allow_estimated_target=False,
        evidence=_exact(
            role=EvidenceRole.POLICY,
            evidence_id="spread-policy",
            version="v1",
            subject_id="spread-policy",
            observed_at=datetime(2025, 12, 1, tzinfo=UTC),
            available_at=datetime(2025, 12, 2, tzinfo=UTC),
            content_hash=_digest("spread-policy"),
            curve_role="spread_percentile_policy",
            currency=None,
        ),
    )


def _evidence(
    references: tuple[SpreadObservation, ...],
) -> SpreadPercentileEvidence:
    target = _observation("2026-06-01", "20")
    raw_manifest = canonical_hash(
        {
            "evidence_id": "spread-input",
            "evidence_version": "v1",
            "scope_id": _SCOPE,
            "spread_definition_id": "spread-definition",
            "spread_definition_version": "v1",
            "currency": "CNY",
            "numerator_curve_role": "government",
            "denominator_curve_role": "policy_bank",
            "target_hash": target.seal_hash,
            "reference_hashes": tuple(item.seal_hash for item in references),
        }
    )
    return SpreadPercentileEvidence(
        evidence_id="spread-input",
        evidence_version="v1",
        scope_id=_SCOPE,
        spread_definition_id="spread-definition",
        spread_definition_version="v1",
        currency="CNY",
        numerator_curve_role="government",
        denominator_curve_role="policy_bank",
        target=target,
        reference_observations=references,
        source=_exact(
            role=EvidenceRole.EXACT_PIT_INPUT,
            evidence_id="spread-input",
            version="v1",
            subject_id=_SCOPE,
            observed_at=datetime(2026, 6, 1, tzinfo=UTC),
            available_at=datetime(2026, 6, 2, tzinfo=UTC),
            content_hash=raw_manifest,
            curve_role="spread_percentile:government:policy_bank",
            upstream_hashes=tuple(
                sorted((target.seal_hash, *(item.seal_hash for item in references)))
            ),
        ),
    )


def _codes(result: SpreadPercentileAssessment) -> set[SpreadBlockerCode]:
    return {blocker.code for blocker in result.blockers}


def test_midrank_percentile_uses_exact_reference_calendar_denominator() -> None:
    references = (
        _observation("2026-01-31", "10"),
        _observation("2026-02-28", "20"),
    )
    result = evaluate_spread_percentile(
        _evidence(references),
        policy=_policy(),
        calendar=_calendar(),
        evaluated_at=_EVALUATED_AT,
    )

    assert result.status is SpreadAssessmentStatus.AVAILABLE
    assert (result.less_count, result.equal_count, result.greater_count) == (1, 1, 0)
    assert result.percentile == Decimal("0.75")
    assert result.coverage_numerator == result.expected_period_count == 2
    assert result.output_hash == result.calculated_output_hash


def test_future_revision_blocks_but_cannot_hide_known_revision() -> None:
    known = _observation("2026-01-31", "10")
    future = _observation(
        "2026-01-31",
        "99",
        revision=1,
        available_at=datetime(2026, 6, 20, tzinfo=UTC),
    )
    references = (
        known,
        future,
        _observation("2026-02-28", "20"),
    )
    result = evaluate_spread_percentile(
        _evidence(references),
        policy=_policy(),
        calendar=_calendar(),
        evaluated_at=_EVALUATED_AT,
    )

    assert result.status is SpreadAssessmentStatus.BLOCKED
    assert SpreadBlockerCode.EVIDENCE_FROM_FUTURE in _codes(result)
    assert result.selected_observations[0].revision_number == 0


def test_result_statistics_and_hash_are_fully_recomputed() -> None:
    result = evaluate_spread_percentile(
        _evidence(
            (
                _observation("2026-01-31", "10"),
                _observation("2026-02-28", "20"),
            )
        ),
        policy=_policy(),
        calendar=_calendar(),
        evaluated_at=_EVALUATED_AT,
    )

    with pytest.raises(ValueError, match="counts are not recomputable"):
        replace(
            result,
            less_count=0,
            equal_count=2,
            output_hash=canonical_hash(
                {
                    "tampered": "self-consistent hash cannot bypass identities",
                }
            ),
        )


def test_canonical_evidence_rejects_uppercase_hashes_and_mutable_payloads() -> None:
    with pytest.raises(ValueError, match="lowercase"):
        replace(_calendar().evidence, content_hash="A" * 64)
    with pytest.raises(TypeError, match="unsupported"):
        canonical_hash(["mutable", "list"])
    with pytest.raises(TypeError, match="string keys"):
        canonical_hash({1: "non-string"})
