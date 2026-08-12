"""Tests for canonical evidence-envelope domain contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.research.domain.evidence_contracts import (
    ArtifactRef,
    ClaimKind,
    DecisionPermission,
    DependencyFlag,
    EvidenceBlockerCode,
    EvidenceInputBinding,
    EvidenceOperatorSpec,
    GovernanceGrant,
    GovernanceState,
    MethodKind,
    MetricDirection,
    TrackRecordSnapshot,
    build_legacy_unverified_envelope,
    resolve_evidence_envelope,
)
from shared.domain.reliability import ReliabilityContract, ReliabilityStatus

NOW = datetime(2026, 8, 12, 8, tzinfo=UTC)
LATER = NOW + timedelta(days=30)


def _digest(character: str) -> str:
    return character * 64


def _artifact(identifier: str, *, digest: str = "a") -> ArtifactRef:
    return ArtifactRef(
        owner="research",
        artifact_type="scenario_forecast",
        artifact_id=identifier,
        artifact_version="v1",
        content_hash=_digest(digest),
    )


def _spec(*, requires_track_record: bool = True) -> EvidenceOperatorSpec:
    return EvidenceOperatorSpec.create(
        operator_id="r7-scenario-forecast",
        operator_version="v1",
        research_family="scenario",
        output_artifact_type="scenario_forecast",
        claim_kind=ClaimKind.FORECAST,
        method_kind=MethodKind.STATISTICAL,
        required_input_roles=("features", "regime"),
        dependency_flags=frozenset({DependencyFlag.ESTIMATED_INPUT}),
        maximum_permission=DecisionPermission.EXECUTION_ELIGIBLE,
        requires_track_record=requires_track_record,
        activated_at=NOW - timedelta(days=1),
        valid_until=LATER,
    )


def _fresh() -> ReliabilityContract:
    return ReliabilityContract.fresh(
        observed_at=NOW - timedelta(minutes=5),
        fetched_at=NOW - timedelta(minutes=1),
        source="canonical-publication",
    )


def _input(role: str, identifier: str) -> EvidenceInputBinding:
    return EvidenceInputBinding(
        role=role,
        artifact=_artifact(identifier),
        reliability=_fresh(),
        permission=DecisionPermission.EXECUTION_ELIGIBLE,
        valid_until=LATER,
        dependency_flags=frozenset({DependencyFlag.FORECAST_INPUT}),
    )


def _grant(output: ArtifactRef) -> GovernanceGrant:
    return GovernanceGrant(
        output_artifact=output,
        promotion_ref=ArtifactRef(
            owner="research",
            artifact_type="promotion_decision",
            artifact_id="promotion-1",
            artifact_version="v1",
            content_hash=_digest("b"),
        ),
        governance_state=GovernanceState.PROMOTED,
        permission_cap=DecisionPermission.EXECUTION_ELIGIBLE,
        promotion_valid_until=LATER,
        monitoring_ref=ArtifactRef(
            owner="research",
            artifact_type="monitoring_assessment",
            artifact_id="monitoring-1",
            artifact_version="v1",
            content_hash=_digest("c"),
        ),
        monitoring_permission_cap=DecisionPermission.EXECUTION_ELIGIBLE,
        monitoring_valid_until=LATER,
    )


def _track_record(output: ArtifactRef, *, eligible: int = 10) -> TrackRecordSnapshot:
    resolved = eligible
    return TrackRecordSnapshot(
        snapshot_id="track-1",
        snapshot_version="v1",
        artifact=output,
        target="scenario-probability",
        horizon="21d",
        sample_policy_id="r7-oos-policy",
        sample_policy_version="v1",
        evaluated_at=NOW - timedelta(minutes=1),
        valid_until=LATER,
        eligible=eligible,
        resolved=resolved,
        unresolved=0,
        censored=0,
        invalidated=0,
        n_eff=Decimal(resolved),
        coverage=Decimal(0) if eligible == 0 else Decimal(1),
        market_regimes=("growth", "inflation"),
        primary_metric_code=None if eligible == 0 else "brier",
        primary_metric_unit=None if eligible == 0 else "score",
        metric_direction=None if eligible == 0 else MetricDirection.LOWER_IS_BETTER,
        primary_metric_value=None if eligible == 0 else Decimal("0.17"),
        benchmark_metric_value=None if eligible == 0 else Decimal("0.22"),
        skill_delta=None if eligible == 0 else Decimal("0.05"),
        confidence_interval_low=None if eligible == 0 else Decimal("0.01"),
        confidence_interval_high=None if eligible == 0 else Decimal("0.09"),
        drift_detected=False,
        promotion_ref=_grant(output).promotion_ref,
        outcome_refs=(),
        content_hash="",
    )


def _resolve(output: ArtifactRef, **overrides: object):  # type: ignore[no-untyped-def]
    values = {
        "output_artifact": output,
        "operator_spec": _spec(),
        "inputs": (_input("features", "features-1"), _input("regime", "regime-1")),
        "governance_state": GovernanceState.PROMOTED,
        "governance_grant": _grant(output),
        "track_record": _track_record(output),
        "evaluated_at": NOW,
    }
    values.update(overrides)
    return resolve_evidence_envelope(**values)  # type: ignore[arg-type]


def test_resolve_envelope_uses_operator_classification_and_propagates_flags() -> None:
    output = _artifact("forecast-1", digest="e")

    envelope = _resolve(output)

    assert envelope.claim_kind is ClaimKind.FORECAST
    assert envelope.method_kind is MethodKind.STATISTICAL
    assert envelope.permission is DecisionPermission.EXECUTION_ELIGIBLE
    assert envelope.dependency_flags == frozenset(
        {DependencyFlag.ESTIMATED_INPUT, DependencyFlag.FORECAST_INPUT}
    )
    assert envelope.blockers == ()
    assert envelope.must_not_use_for_decision is False
    assert envelope.must_not_execute is False


def test_input_permission_and_governance_cap_take_strictest_intersection() -> None:
    output = _artifact("forecast-1", digest="e")
    advisory = replace(_input("features", "features-1"), permission=DecisionPermission.ADVISORY)
    grant = replace(_grant(output), monitoring_permission_cap=DecisionPermission.DECISION_ELIGIBLE)

    envelope = _resolve(
        output,
        inputs=(advisory, _input("regime", "regime-1")),
        governance_grant=grant,
    )

    assert envelope.permission is DecisionPermission.ADVISORY
    assert envelope.must_not_use_for_decision is True


@pytest.mark.parametrize(
    ("replacement", "expected"),
    [
        (
            {"inputs": (_input("features", "features-1"),)},
            EvidenceBlockerCode.REQUIRED_INPUT_MISSING,
        ),
        (
            {"governance_grant": None},
            EvidenceBlockerCode.PROMOTION_MISSING,
        ),
        (
            {"track_record": None},
            EvidenceBlockerCode.TRACK_RECORD_MISSING,
        ),
    ],
)
def test_missing_required_evidence_fails_closed(
    replacement: dict[str, object], expected: EvidenceBlockerCode
) -> None:
    output = _artifact("forecast-1", digest="e")

    envelope = _resolve(output, **replacement)

    assert expected in envelope.blockers
    assert envelope.permission is DecisionPermission.DISPLAY_ONLY


def test_stale_or_non_pit_input_fails_closed() -> None:
    output = _artifact("forecast-1", digest="e")
    blocked = ReliabilityContract.blocked(
        status=ReliabilityStatus.STALE,
        source="canonical-publication",
        reason_code="canonical_publication_stale",
        reason="source observation is stale",
        observed_at=NOW - timedelta(days=2),
        fetched_at=NOW - timedelta(days=2),
    )
    unsafe = replace(_input("features", "features-1"), reliability=blocked, pit_verified=False)

    envelope = _resolve(output, inputs=(unsafe, _input("regime", "regime-1")))

    assert EvidenceBlockerCode.INPUT_UNRELIABLE in envelope.blockers
    assert EvidenceBlockerCode.INPUT_PIT_UNVERIFIED in envelope.blockers
    assert envelope.permission is DecisionPermission.DISPLAY_ONLY


def test_promotion_does_not_inherit_when_output_is_research_only() -> None:
    output = _artifact("forecast-1", digest="e")

    envelope = _resolve(
        output,
        governance_state=GovernanceState.RESEARCH_ONLY,
        governance_grant=None,
    )

    assert EvidenceBlockerCode.OUTPUT_NOT_PROMOTED in envelope.blockers
    assert envelope.permission is DecisionPermission.DISPLAY_ONLY


def test_track_record_isolated_by_exact_output_version_and_hash() -> None:
    output = _artifact("forecast-1", digest="e")
    other_version = ArtifactRef(
        owner=output.owner,
        artifact_type=output.artifact_type,
        artifact_id=output.artifact_id,
        artifact_version="v2",
        content_hash=_digest("f"),
    )

    envelope = _resolve(output, track_record=_track_record(other_version))

    assert EvidenceBlockerCode.TRACK_RECORD_MISMATCH in envelope.blockers
    assert envelope.permission is DecisionPermission.DISPLAY_ONLY


def test_empty_track_record_has_complete_denominator_but_cannot_unlock_decision() -> None:
    output = _artifact("forecast-1", digest="e")

    envelope = _resolve(output, track_record=_track_record(output, eligible=0))

    assert EvidenceBlockerCode.TRACK_RECORD_EMPTY in envelope.blockers
    assert envelope.permission is DecisionPermission.DISPLAY_ONLY


def test_track_record_rejects_incomplete_denominator_and_future_metrics_for_zero_sample() -> None:
    output = _artifact("forecast-1", digest="e")
    record = _track_record(output)

    with pytest.raises(ValueError, match="conserve"):
        replace(record, eligible=11)
    with pytest.raises(ValueError, match="eligible=0"):
        replace(record, eligible=0, resolved=0, n_eff=Decimal(0), coverage=Decimal(0))


def test_valid_until_is_earliest_evidence_expiry() -> None:
    output = _artifact("forecast-1", digest="e")
    early = NOW + timedelta(hours=1)
    input_binding = replace(_input("features", "features-1"), valid_until=early)

    envelope = _resolve(output, inputs=(input_binding, _input("regime", "regime-1")))

    assert envelope.valid_until == early


def test_content_hash_is_deterministic_and_sensitive_to_lineage() -> None:
    output = _artifact("forecast-1", digest="e")

    first = _resolve(output)
    second = _resolve(output)
    changed = _resolve(
        output,
        inputs=(_input("features", "features-2"), _input("regime", "regime-1")),
    )

    assert first.content_hash == second.content_hash
    assert first.content_hash != changed.content_hash


def test_legacy_adapter_is_non_persistent_display_only_compatibility() -> None:
    output = _artifact("legacy-forecast", digest="e")

    envelope = build_legacy_unverified_envelope(
        output_artifact=output,
        claim_kind=ClaimKind.FORECAST,
        method_kind=MethodKind.STATISTICAL,
        evaluated_at=NOW,
        valid_until=LATER,
    )

    assert envelope.governance_state is GovernanceState.RESEARCH_ONLY
    assert envelope.permission is DecisionPermission.DISPLAY_ONLY
    assert envelope.blockers == (EvidenceBlockerCode.LEGACY_UNVERIFIED,)
    assert envelope.must_not_execute is True


def test_operator_spec_rejects_unsorted_or_duplicate_required_roles() -> None:
    spec = _spec()

    with pytest.raises(ValueError, match="ordered and unique"):
        replace(spec, required_input_roles=("regime", "features"))


def test_domain_seals_reject_post_construction_semantic_tampering() -> None:
    output = _artifact("forecast-1", digest="e")
    spec = _spec()
    record = _track_record(output)
    envelope = _resolve(output)

    with pytest.raises(ValueError, match="operator specification content_hash"):
        replace(spec, maximum_permission=DecisionPermission.DISPLAY_ONLY)
    with pytest.raises(ValueError, match="track-record content_hash"):
        replace(record, primary_metric_value=Decimal("0.99"))
    with pytest.raises(ValueError, match="evidence-envelope content_hash"):
        replace(envelope, permission=DecisionPermission.DISPLAY_ONLY)


def test_operator_factory_rejects_naive_time_before_hashing() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        EvidenceOperatorSpec.create(
            operator_id="r7-scenario-forecast",
            operator_version="v1",
            research_family="scenario",
            output_artifact_type="scenario_forecast",
            claim_kind=ClaimKind.FORECAST,
            method_kind=MethodKind.STATISTICAL,
            required_input_roles=("features",),
            dependency_flags=frozenset(),
            maximum_permission=DecisionPermission.DISPLAY_ONLY,
            requires_track_record=True,
            activated_at=datetime(2026, 8, 12, 8),
            valid_until=LATER,
        )
