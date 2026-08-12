"""Tests for the compact cross-consumer Evidence summary contract."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.research.application.evidence_summary import EvidenceSummaryDTO
from apps.research.domain.evidence_contracts import (
    ArtifactRef,
    ClaimKind,
    DecisionPermission,
    EvidenceEnvelope,
    EvidenceOperatorSpec,
    GovernanceState,
    MethodKind,
    MetricDirection,
    TrackRecordSnapshot,
)

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)
LATER = NOW + timedelta(days=1)


def _artifact(identifier: str = "forecast-1") -> ArtifactRef:
    return ArtifactRef("research", "forecast", identifier, "v1", "a" * 64)


def _operator(*, requires_track_record: bool) -> EvidenceOperatorSpec:
    return EvidenceOperatorSpec.create(
        operator_id="forecast-operator",
        operator_version="v1",
        research_family="r7",
        output_artifact_type="forecast",
        claim_kind=ClaimKind.FORECAST,
        method_kind=MethodKind.STATISTICAL,
        required_input_roles=(),
        dependency_flags=frozenset(),
        maximum_permission=DecisionPermission.DISPLAY_ONLY,
        requires_track_record=requires_track_record,
        activated_at=NOW - timedelta(days=1),
        valid_until=LATER,
    )


def _track(*, eligible: int) -> TrackRecordSnapshot:
    return TrackRecordSnapshot(
        snapshot_id="track-1",
        snapshot_version="v1",
        artifact=_artifact(),
        target="probability",
        horizon="21d",
        sample_policy_id="oos",
        sample_policy_version="v1",
        evaluated_at=NOW,
        valid_until=LATER,
        eligible=eligible,
        resolved=eligible,
        unresolved=0,
        censored=0,
        invalidated=0,
        n_eff=Decimal(eligible),
        coverage=Decimal(1 if eligible else 0),
        market_regimes=(),
        primary_metric_code="brier" if eligible else None,
        primary_metric_unit="score" if eligible else None,
        metric_direction=MetricDirection.LOWER_IS_BETTER if eligible else None,
        primary_metric_value=Decimal("0.2") if eligible else None,
        benchmark_metric_value=Decimal("0.3") if eligible else None,
        skill_delta=Decimal("0.1") if eligible else None,
        confidence_interval_low=Decimal("0.01") if eligible else None,
        confidence_interval_high=Decimal("0.19") if eligible else None,
        drift_detected=False,
        promotion_ref=ArtifactRef("research", "promotion", "p1", "v1", "b" * 64),
        outcome_refs=(),
        content_hash="",
    )


def _envelope(
    operator: EvidenceOperatorSpec,
    track: TrackRecordSnapshot | None,
) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        output_artifact=_artifact(),
        operator_spec_ref=operator.artifact_ref,
        claim_kind=ClaimKind.FORECAST,
        method_kind=MethodKind.STATISTICAL,
        research_family="r7",
        governance_state=GovernanceState.RESEARCH_ONLY,
        permission=DecisionPermission.DISPLAY_ONLY,
        lineage=tuple(sorted((_artifact(), operator.artifact_ref))),
        dependency_flags=frozenset(),
        track_record_ref=track.artifact_ref if track is not None else None,
        blockers=(),
        evaluated_at=NOW,
        valid_until=LATER,
        content_hash="",
    )


@pytest.mark.parametrize(
    ("required", "eligible", "expected"),
    [
        (False, None, "not_required"),
        (True, None, "unavailable"),
        (True, 0, "empty"),
        (True, 3, "available"),
    ],
)
def test_summary_distinguishes_track_record_states(
    required: bool,
    eligible: int | None,
    expected: str,
) -> None:
    operator = _operator(requires_track_record=required)
    track = _track(eligible=eligible) if eligible is not None else None
    summary = EvidenceSummaryDTO.from_evidence(
        envelope=_envelope(operator, track),
        operator_spec=operator,
        track_record=track,
    )

    assert summary.track_record_availability == expected
    assert summary.n_eff == (str(eligible) if eligible is not None else None)
    assert summary.must_not_use_for_decision is True
    assert summary.must_not_execute is True


def test_summary_rejects_operator_and_track_record_substitution() -> None:
    operator = _operator(requires_track_record=True)
    track = _track(eligible=3)
    envelope = _envelope(operator, track)

    with pytest.raises(ValueError, match="operator specification"):
        EvidenceSummaryDTO.from_evidence(
            envelope=envelope,
            operator_spec=replace(operator, operator_version="v2", content_hash=""),
            track_record=track,
        )
    with pytest.raises(ValueError, match="Track Record"):
        EvidenceSummaryDTO.from_evidence(
            envelope=envelope,
            operator_spec=operator,
            track_record=replace(track, snapshot_version="v2", content_hash=""),
        )
