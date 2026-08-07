"""Deterministic fixtures for R2 market-structure promotion tests."""

from __future__ import annotations

from datetime import timedelta

from apps.data_center.domain.market_structure import (
    ImmutableMarketStructureEvidence,
    MarketStructureGovernanceArtifactKind,
    aggregate_market_structure,
    build_market_structure_evidence,
)
from apps.research.domain.r2_market_structure_promotion import (
    R2MarketStructureDecisionAuthorization,
    R2MarketStructureEvidenceSeal,
    R2MarketStructureLifecycleAction,
    R2MarketStructureLifecycleAuthorization,
    R2MarketStructurePromotionDecision,
    R2MarketStructurePromotionPolicy,
    R2MarketStructurePromotionScope,
    create_r2_market_structure_lifecycle_authorization,
    create_r2_market_structure_promotion_decision,
)
from tests.unit.data_center.test_market_structure import (
    AS_OF,
    _actor,
    _calendar,
    _complete_observations,
    _coverage_for,
    _publication_attestation,
    _request,
    _series,
)

HASH = "d" * 64


def make_r2_evidence() -> ImmutableMarketStructureEvidence:
    first = _series("A")
    second = _series("B")
    observations = _complete_observations(first, second)
    request = _request()
    snapshot = aggregate_market_structure(
        request=request,
        period_calendar=_calendar(),
        definitions=(first, second),
        observations=observations,
        coverage=_coverage_for(observations),
    )
    actors = (_actor("A"), _actor("B"))
    return build_market_structure_evidence(
        request=request,
        snapshot=snapshot,
        period_calendar=_calendar(),
        actor_definitions=actors,
        series_definitions=(first, second),
        source_evidence=tuple(item.evidence for item in observations),
        governance_publications=(
            _publication_attestation(
                kind=MarketStructureGovernanceArtifactKind.PERIOD_CALENDAR,
                natural_key="calendar:TEST_MONTHLY_CALENDAR:v1",
                artifact_hash=_calendar().calendar_hash,
                observed_at=AS_OF,
                member_id="calendar-member",
            ),
            *(
                _publication_attestation(
                    kind=MarketStructureGovernanceArtifactKind.ACTOR,
                    natural_key=f"actor:TEST_TAXONOMY:v1:{actor.actor_code}",
                    artifact_hash=actor.definition_hash,
                    observed_at=actor.available_at,
                    member_id=f"actor-{actor.actor_code}",
                )
                for actor in actors
            ),
            *(
                _publication_attestation(
                    kind=MarketStructureGovernanceArtifactKind.SERIES,
                    natural_key=f"series:{series.series_code}:v1",
                    artifact_hash=series.definition_hash,
                    observed_at=series.available_at,
                    member_id=f"series-{series.actor_code}",
                )
                for series in (first, second)
            ),
        ),
    )


def make_r2_policy(
    evidence: ImmutableMarketStructureEvidence,
) -> R2MarketStructurePromotionPolicy:
    scope = R2MarketStructurePromotionScope.create(
        group_code=evidence.group_code,
        group_revision=evidence.group_revision,
        method_version=evidence.method_version,
        policy_code=evidence.policy_code,
        policy_version=evidence.policy_version,
    )
    return R2MarketStructurePromotionPolicy.create(
        policy_version="r2-promotion-policy.v1",
        scope=scope,
        owner_approval_ref="research-owner://r2-policy/test",
        owner_approval_hash=HASH,
        registered_at=AS_OF + timedelta(hours=1),
        active_from=AS_OF + timedelta(hours=1),
        valid_until=AS_OF + timedelta(days=30),
    )


def make_r2_decision(
    evidence: ImmutableMarketStructureEvidence,
    policy: R2MarketStructurePromotionPolicy,
) -> tuple[R2MarketStructurePromotionDecision, R2MarketStructureDecisionAuthorization]:
    seal = R2MarketStructureEvidenceSeal.from_evidence(evidence)
    decided_at = AS_OF + timedelta(hours=2)
    authorization = R2MarketStructureDecisionAuthorization.create(
        authorization_version="r2-decision-auth.v1",
        policy=policy,
        evidence=seal,
        issued_at=decided_at - timedelta(minutes=5),
        decided_at=decided_at,
        decision_recorded_at=decided_at + timedelta(minutes=5),
        valid_until=AS_OF + timedelta(days=20),
        owner_receipt_hash=HASH,
    )
    return (
        create_r2_market_structure_promotion_decision(
            policy=policy,
            evidence=seal,
            authorization=authorization,
        ),
        authorization,
    )


def make_r2_lifecycle_authorization(
    decision: R2MarketStructurePromotionDecision,
    *,
    action: R2MarketStructureLifecycleAction = R2MarketStructureLifecycleAction.PROMOTE,
    rollback_target: R2MarketStructurePromotionDecision | None = None,
    offset_hours: int = 3,
) -> R2MarketStructureLifecycleAuthorization:
    occurred_at = AS_OF + timedelta(hours=offset_hours)
    return create_r2_market_structure_lifecycle_authorization(
        authorization_version=f"r2-lifecycle-{action.value}.v1",
        scope=decision.policy.scope,
        action=action,
        decision=decision,
        rollback_target=rollback_target,
        issued_at=occurred_at - timedelta(minutes=5),
        occurred_at=occurred_at,
        event_recorded_at=occurred_at + timedelta(minutes=5),
        valid_until=AS_OF + timedelta(days=10),
        reason_codes=(f"owner_{action.value}_approved",),
        owner_receipt_hash=HASH,
    )


__all__ = [
    "HASH",
    "make_r2_decision",
    "make_r2_evidence",
    "make_r2_lifecycle_authorization",
    "make_r2_policy",
]
