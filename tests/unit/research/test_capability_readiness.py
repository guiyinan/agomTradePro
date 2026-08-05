"""Tests for R1-R8 readiness gates before implementation is allowed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.research.application.capability_readiness import (
    EvaluateCapabilityReadinessUseCase,
)
from apps.research.domain.capability_readiness import (
    R1_REQUIREMENTS,
    R2_REQUIREMENTS,
    R3_REQUIREMENTS,
    R4_REQUIREMENTS,
    R5_REQUIREMENTS,
    R6_REQUIREMENTS,
    R7_REQUIREMENTS,
    R8_REQUIREMENTS,
    ReadinessDecision,
    ReadinessEvidence,
    ReadinessRequirement,
    ReadinessState,
    ResearchCapability,
    evaluate_capability_readiness,
    requirement_owner,
    requirements_for,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


def _verified(requirement: ReadinessRequirement) -> ReadinessEvidence:
    return ReadinessEvidence(
        requirement=requirement,
        owner=requirement_owner(requirement),
        state=ReadinessState.VERIFIED,
        observed_at=NOW,
        valid_until=NOW + timedelta(days=1),
        evidence_ref=f"evidence:{requirement.value}:v1",
    )


def test_r3_is_ready_only_when_every_requirement_is_verified() -> None:
    report = evaluate_capability_readiness(
        capability=ResearchCapability.MACRO_FACTOR_NOWCAST,
        evaluated_at=NOW,
        evidence=tuple(_verified(requirement) for requirement in R3_REQUIREMENTS),
    )

    assert report.decision is ReadinessDecision.READY
    assert report.can_start is True
    assert report.blockers == ()


@pytest.mark.parametrize(
    ("capability", "requirements"),
    [
        (ResearchCapability.INDUSTRY_EARNINGS_FORECAST, R1_REQUIREMENTS),
        (ResearchCapability.MARKET_STRUCTURE_INVESTOR_FLOW, R2_REQUIREMENTS),
    ],
)
def test_r1_r2_are_ready_only_with_complete_owner_evidence(
    capability: ResearchCapability,
    requirements: tuple[ReadinessRequirement, ...],
) -> None:
    ready = evaluate_capability_readiness(
        capability=capability,
        evaluated_at=NOW,
        evidence=tuple(_verified(requirement) for requirement in requirements),
    )
    blocked = evaluate_capability_readiness(
        capability=capability,
        evaluated_at=NOW,
        evidence=tuple(_verified(requirement) for requirement in requirements[:-1]),
    )

    assert ready.can_start is True
    assert blocked.can_start is False
    assert [item.requirement for item in blocked.blockers] == [requirements[-1]]


def test_r1_r2_requirement_sets_keep_owner_boundaries_explicit() -> None:
    assert tuple(requirement_owner(item) for item in R1_REQUIREMENTS) == (
        "risk_center",
        "data_center",
        "data_center",
        "data_center",
        "equity",
        "research",
    )
    assert {requirement_owner(item) for item in R2_REQUIREMENTS} == {"data_center"}


def test_missing_r3_evidence_is_materialized_as_stable_blockers() -> None:
    report = evaluate_capability_readiness(
        capability=ResearchCapability.MACRO_FACTOR_NOWCAST,
        evaluated_at=NOW,
        evidence=(),
    )

    assert report.decision is ReadinessDecision.BLOCKED
    assert report.can_start is False
    assert tuple(item.requirement for item in report.evidence) == R3_REQUIREMENTS
    assert len(report.blockers) == len(R3_REQUIREMENTS)
    assert report.blockers[0].reason_code.endswith(".missing")


def test_unverified_owner_evidence_preserves_specific_blocking_detail() -> None:
    evidence = ReadinessEvidence(
        requirement=ReadinessRequirement.TARGET_MACRO_VINTAGES_PIT,
        owner="data_center",
        state=ReadinessState.UNVERIFIED,
        observed_at=NOW,
        blocking_reason="macro target series has no production PIT population evidence",
    )

    report = evaluate_capability_readiness(
        capability=ResearchCapability.MACRO_FACTOR_NOWCAST,
        evaluated_at=NOW,
        evidence=(evidence,),
    )

    blocker = next(
        item
        for item in report.blockers
        if item.requirement is ReadinessRequirement.TARGET_MACRO_VINTAGES_PIT
    )
    assert blocker.owner == "data_center"
    assert blocker.detail == evidence.blocking_reason
    assert blocker.reason_code.endswith(".unverified")


def test_r4_cannot_start_without_an_r3_promotion_reference() -> None:
    evidence = tuple(
        _verified(requirement)
        for requirement in R4_REQUIREMENTS
        if requirement is not ReadinessRequirement.R3_PROMOTED_FACTOR_VERSION
    )

    report = evaluate_capability_readiness(
        capability=ResearchCapability.MACRO_FACTOR_RISK_PARITY,
        evaluated_at=NOW,
        evidence=evidence,
    )

    assert report.can_start is False
    assert [item.requirement for item in report.blockers] == [
        ReadinessRequirement.R3_PROMOTED_FACTOR_VERSION
    ]


def test_r4_is_ready_only_with_promoted_r3_and_portfolio_inputs() -> None:
    report = evaluate_capability_readiness(
        capability=ResearchCapability.MACRO_FACTOR_RISK_PARITY,
        evaluated_at=NOW,
        evidence=tuple(_verified(requirement) for requirement in R4_REQUIREMENTS),
    )

    assert report.can_start is True


@pytest.mark.parametrize(
    ("capability", "requirements"),
    [
        (ResearchCapability.FIXED_INCOME_RELATIVE_VALUE, R5_REQUIREMENTS),
        (ResearchCapability.ADVANCED_STATE_MODEL, R6_REQUIREMENTS),
        (ResearchCapability.SCENARIO_PROBABILITY_CALIBRATION, R7_REQUIREMENTS),
        (ResearchCapability.MULTI_ASSET_OPTIMIZATION, R8_REQUIREMENTS),
    ],
)
def test_r5_r8_are_ready_only_with_complete_owner_evidence(
    capability: ResearchCapability,
    requirements: tuple[ReadinessRequirement, ...],
) -> None:
    ready = evaluate_capability_readiness(
        capability=capability,
        evaluated_at=NOW,
        evidence=tuple(_verified(requirement) for requirement in requirements),
    )
    blocked = evaluate_capability_readiness(
        capability=capability,
        evaluated_at=NOW,
        evidence=tuple(_verified(requirement) for requirement in requirements[:-1]),
    )

    assert ready.can_start is True
    assert blocked.can_start is False
    assert [item.requirement for item in blocked.blockers] == [requirements[-1]]


def test_r7_requires_scenario_ledger_binding_and_outcome_history() -> None:
    required_dependencies = {
        ReadinessRequirement.SCENARIO_VERSION_LEDGER_BINDING,
        ReadinessRequirement.COMPLETE_SCENARIO_OUTCOME_HISTORY,
    }
    evidence = tuple(
        _verified(requirement)
        for requirement in R7_REQUIREMENTS
        if requirement not in required_dependencies
    )

    report = evaluate_capability_readiness(
        capability=ResearchCapability.SCENARIO_PROBABILITY_CALIBRATION,
        evaluated_at=NOW,
        evidence=evidence,
    )

    assert {item.requirement for item in report.blockers} == required_dependencies


def test_r8_requires_all_upstream_promoted_versions() -> None:
    promoted_versions = {
        ReadinessRequirement.R3_PROMOTED_FACTOR_VERSION,
        ReadinessRequirement.R4_PROMOTED_MACRO_RISK_VERSION,
        ReadinessRequirement.R5_PROMOTED_FIXED_INCOME_VERSION,
    }
    evidence = tuple(
        _verified(requirement)
        for requirement in R8_REQUIREMENTS
        if requirement not in promoted_versions
    )

    report = evaluate_capability_readiness(
        capability=ResearchCapability.MULTI_ASSET_OPTIMIZATION,
        evaluated_at=NOW,
        evidence=evidence,
    )

    assert {item.requirement for item in report.blockers} == promoted_versions


@pytest.mark.parametrize(
    ("evidence", "message"),
    [
        (
            ReadinessEvidence(
                requirement=ReadinessRequirement.EXPERIMENT_REGISTRY,
                owner="research",
                state=ReadinessState.VERIFIED,
                observed_at=NOW + timedelta(seconds=1),
                valid_until=NOW + timedelta(days=1),
                evidence_ref="research-registry:v1",
            ),
            "future",
        ),
        (
            ReadinessEvidence(
                requirement=ReadinessRequirement.EXPERIMENT_REGISTRY,
                owner="research",
                state=ReadinessState.VERIFIED,
                observed_at=NOW,
                valid_until=NOW + timedelta(days=1),
                evidence_ref="research-registry:v1",
            ),
            "duplicate",
        ),
    ],
)
def test_gate_rejects_future_or_duplicate_evidence(
    evidence: ReadinessEvidence,
    message: str,
) -> None:
    supplied = (evidence,) if message == "future" else (evidence, evidence)

    with pytest.raises(ValueError, match=message):
        evaluate_capability_readiness(
            capability=ResearchCapability.MACRO_FACTOR_NOWCAST,
            evaluated_at=NOW,
            evidence=supplied,
        )


def test_evidence_cannot_be_attested_by_the_wrong_owner() -> None:
    with pytest.raises(ValueError, match="must be owned by data_center"):
        ReadinessEvidence(
            requirement=ReadinessRequirement.PROXY_ASSET_PRICES_PIT,
            owner="factor",
            state=ReadinessState.VERIFIED,
            observed_at=NOW,
            valid_until=NOW + timedelta(days=1),
            evidence_ref="price-manifest:v1",
        )


def test_expired_verified_evidence_is_normalized_to_stale() -> None:
    requirement = ReadinessRequirement.EXPERIMENT_REGISTRY
    evidence = ReadinessEvidence(
        requirement=requirement,
        owner=requirement_owner(requirement),
        state=ReadinessState.VERIFIED,
        observed_at=NOW - timedelta(days=2),
        valid_until=NOW - timedelta(days=1),
        evidence_ref="research-registry:v1",
    )

    report = evaluate_capability_readiness(
        capability=ResearchCapability.MACRO_FACTOR_NOWCAST,
        evaluated_at=NOW,
        evidence=(evidence,),
    )

    stale = next(item for item in report.evidence if item.requirement is requirement)
    assert stale.state is ReadinessState.STALE
    assert [item.requirement for item in report.blockers].count(requirement) == 1
    assert next(
        item for item in report.blockers if item.requirement is requirement
    ).reason_code.endswith(".stale")


def test_verified_evidence_requires_an_explicit_validity_window() -> None:
    with pytest.raises(ValueError, match="requires valid_until"):
        ReadinessEvidence(
            requirement=ReadinessRequirement.EXPERIMENT_REGISTRY,
            owner="research",
            state=ReadinessState.VERIFIED,
            observed_at=NOW,
            evidence_ref="research-registry:v1",
        )


def test_every_requirement_is_owned_and_referenced_by_a_capability() -> None:
    referenced: set[ReadinessRequirement] = set()
    for capability in ResearchCapability:
        requirements = requirements_for(capability)
        assert requirements
        assert len(requirements) == len(set(requirements))
        referenced.update(requirements)

    assert referenced == set(ReadinessRequirement)
    assert all(requirement_owner(item) for item in ReadinessRequirement)


def test_cross_capability_evidence_is_rejected() -> None:
    evidence = _verified(ReadinessRequirement.R3_PROMOTED_FACTOR_VERSION)

    with pytest.raises(ValueError, match="unexpected readiness evidence"):
        evaluate_capability_readiness(
            capability=ResearchCapability.MACRO_FACTOR_NOWCAST,
            evaluated_at=NOW,
            evidence=(evidence,),
        )


def test_evidence_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="observed_at must be timezone-aware"):
        ReadinessEvidence(
            requirement=ReadinessRequirement.EXPERIMENT_REGISTRY,
            owner="research",
            state=ReadinessState.MISSING,
            observed_at=datetime(2026, 8, 5, 12),
            blocking_reason="missing",
        )


def test_non_verified_evidence_requires_a_blocking_reason() -> None:
    with pytest.raises(ValueError, match="requires a blocking reason"):
        ReadinessEvidence(
            requirement=ReadinessRequirement.EXPERIMENT_REGISTRY,
            owner="research",
            state=ReadinessState.UNVERIFIED,
            observed_at=NOW,
        )


class _RecordingEvidenceProvider:
    def __init__(self) -> None:
        self.requirements: tuple[ReadinessRequirement, ...] = ()

    def collect(
        self,
        *,
        capability: ResearchCapability,
        requirements: tuple[ReadinessRequirement, ...],
        evaluated_at: datetime,
    ) -> tuple[ReadinessEvidence, ...]:
        assert capability is ResearchCapability.MACRO_FACTOR_NOWCAST
        assert evaluated_at == NOW
        self.requirements = requirements
        return tuple(_verified(requirement) for requirement in requirements)


def test_application_use_case_requests_the_governed_requirement_set() -> None:
    provider = _RecordingEvidenceProvider()

    report = EvaluateCapabilityReadinessUseCase(provider).execute(
        capability=ResearchCapability.MACRO_FACTOR_NOWCAST,
        evaluated_at=NOW,
    )

    assert provider.requirements == R3_REQUIREMENTS
    assert report.can_start is True
