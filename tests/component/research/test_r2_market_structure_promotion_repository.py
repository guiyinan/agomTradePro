"""Component coverage for the persisted R2 promotion loop."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.data_center.domain.market_structure import ImmutableMarketStructureEvidence
from apps.research.application.r2_market_structure_promotion import (
    ApplyR2MarketStructureLifecycleCommand,
    EvaluateR2MarketStructurePromotionCommand,
    R2MarketStructurePromotionEvidenceError,
)
from apps.research.domain.r2_market_structure_promotion import (
    R2MarketStructureDecisionAuthorization,
    R2MarketStructureLifecycleAction,
    R2MarketStructureLifecycleAuthorization,
    R2MarketStructurePromotionPolicy,
    R2MarketStructurePromotionRef,
)
from apps.research.infrastructure.r2_market_structure_promotion_models import (
    R2MarketStructurePromotionDecisionModel,
    R2MarketStructurePromotionLifecycleEventModel,
    R2MarketStructurePromotionPolicyModel,
)
from apps.research.infrastructure.r2_market_structure_promotion_repository import (
    DjangoR2MarketStructurePromotionRepository,
)
from apps.research.r2_market_structure_promotion_composition import (
    build_django_r2_market_structure_promotion_runtime,
)
from tests.unit.research.r2_market_structure_promotion_factories import (
    make_r2_decision,
    make_r2_evidence,
    make_r2_lifecycle_authorization,
    make_r2_policy,
)

pytestmark = pytest.mark.django_db(transaction=True)


class _Clock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


@dataclass
class _PolicySource:
    policy: R2MarketStructurePromotionPolicy
    enabled: bool = True
    unit_of_work_key: str = "django:default"

    def get_exact(
        self,
        policy_ref: R2MarketStructurePromotionRef,
        *,
        as_of: datetime,
    ) -> R2MarketStructurePromotionPolicy | None:
        if not self.enabled:
            return None
        return (
            self.policy
            if self.policy.reference == policy_ref and self.policy.is_active_at(as_of)
            else None
        )


@dataclass
class _EvidenceProvider:
    evidence: ImmutableMarketStructureEvidence
    enabled: bool = True
    unit_of_work_key: str = "django:default"

    def get_exact(
        self,
        evidence_ref: R2MarketStructurePromotionRef,
        *,
        as_of: datetime,
    ) -> ImmutableMarketStructureEvidence | None:
        del as_of
        expected = R2MarketStructurePromotionRef(
            self.evidence.evidence_key,
            str(self.evidence.evidence_version),
        )
        return self.evidence if self.enabled and evidence_ref == expected else None


@dataclass
class _DecisionAuthorizationSource:
    authorization: R2MarketStructureDecisionAuthorization
    unit_of_work_key: str = "django:default"

    def get_exact(
        self,
        authorization_ref: R2MarketStructurePromotionRef,
        *,
        policy_ref: R2MarketStructurePromotionRef,
        evidence_ref: R2MarketStructurePromotionRef,
        as_of: datetime,
    ) -> R2MarketStructureDecisionAuthorization | None:
        item = self.authorization
        return (
            item
            if item.reference == authorization_ref
            and item.policy_ref == policy_ref
            and item.evidence_ref == evidence_ref
            and item.issued_at <= as_of < item.valid_until
            else None
        )


@dataclass
class _LifecycleAuthorizationSource:
    authorization: R2MarketStructureLifecycleAuthorization | None = None
    unit_of_work_key: str = "django:default"

    def get_exact(
        self,
        authorization_ref: R2MarketStructurePromotionRef,
        *,
        scope_id: str,
        action: R2MarketStructureLifecycleAction,
        decision_ref: R2MarketStructurePromotionRef,
        rollback_target_ref: R2MarketStructurePromotionRef | None,
    ) -> R2MarketStructureLifecycleAuthorization | None:
        item = self.authorization
        return (
            item
            if item is not None
            and item.reference == authorization_ref
            and item.scope_id == scope_id
            and item.action is action
            and item.decision_ref == decision_ref
            and item.rollback_target_ref == rollback_target_ref
            else None
        )


def test_id_only_runtime_persists_and_revalidates_active_descriptive_evidence() -> None:
    evidence = make_r2_evidence()
    policy = make_r2_policy(evidence)
    decision, decision_authorization = make_r2_decision(evidence, policy)
    policy_source = _PolicySource(policy)
    evidence_provider = _EvidenceProvider(evidence)
    decision_source = _DecisionAuthorizationSource(decision_authorization)
    lifecycle_source = _LifecycleAuthorizationSource()
    clock = _Clock(policy.active_from)
    runtime = build_django_r2_market_structure_promotion_runtime(
        policy_source=policy_source,
        evidence_provider=evidence_provider,
        decision_authorization_source=decision_source,
        lifecycle_authorization_source=lifecycle_source,
        clock=clock,
    )

    assert not hasattr(DjangoR2MarketStructurePromotionRepository, "append_policy")
    assert not hasattr(DjangoR2MarketStructurePromotionRepository, "append_decision")
    assert not hasattr(DjangoR2MarketStructurePromotionRepository, "append_lifecycle_event")
    assert runtime.register_policy.execute(policy.reference) == policy
    clock.current = decision.decided_at + timedelta(minutes=1)
    command = EvaluateR2MarketStructurePromotionCommand(
        policy_ref=policy.reference,
        evidence_ref=decision.evidence.reference,
        authorization_ref=decision_authorization.reference,
        as_of=decision.decided_at,
    )
    assert runtime.evaluate.execute(command) == decision
    lifecycle = make_r2_lifecycle_authorization(decision)
    lifecycle_source.authorization = lifecycle
    clock.current = lifecycle.occurred_at + timedelta(minutes=1)
    lifecycle_command = ApplyR2MarketStructureLifecycleCommand(
        scope_id=policy.scope.scope_id,
        action=R2MarketStructureLifecycleAction.PROMOTE,
        decision_ref=decision.reference,
        authorization_ref=lifecycle.reference,
    )
    event = runtime.apply_lifecycle.execute(lifecycle_command)
    assert runtime.apply_lifecycle.execute(lifecycle_command) == event
    with pytest.raises(R2MarketStructurePromotionEvidenceError) as idempotency_error:
        runtime.apply_lifecycle.execute(
            ApplyR2MarketStructureLifecycleCommand(
                scope_id=policy.scope.scope_id,
                action=R2MarketStructureLifecycleAction.RETIRE,
                decision_ref=decision.reference,
                authorization_ref=lifecycle.reference,
            )
        )
    assert (
        idempotency_error.value.reason_code == "r2_market_structure.lifecycle_idempotency_conflict"
    )
    active_as_of = event.recorded_at + timedelta(minutes=1)
    clock.current = active_as_of
    assert runtime.get_active.get_active(policy.scope.scope_id, as_of=active_as_of) == decision

    assert R2MarketStructurePromotionPolicyModel._default_manager.count() == 1
    assert R2MarketStructurePromotionDecisionModel._default_manager.count() == 1
    assert R2MarketStructurePromotionLifecycleEventModel._default_manager.count() == 1
    assert R2MarketStructurePromotionDecisionModel._default_manager.get().must_not_execute is True
    assert (
        R2MarketStructurePromotionPolicyModel._base_manager
        is R2MarketStructurePromotionPolicyModel._default_manager
    )
    assert (
        R2MarketStructurePromotionDecisionModel._base_manager
        is R2MarketStructurePromotionDecisionModel._default_manager
    )
    assert (
        R2MarketStructurePromotionLifecycleEventModel._base_manager
        is R2MarketStructurePromotionLifecycleEventModel._default_manager
    )

    policy_model = R2MarketStructurePromotionPolicyModel._default_manager.get()
    with pytest.raises(ValidationError):
        policy_model.save()
    with pytest.raises(ValidationError):
        R2MarketStructurePromotionPolicyModel._default_manager.filter(pk=policy_model.pk).update(
            scope_id="tampered"
        )

    evidence_provider.enabled = False
    assert runtime.get_active.get_active(policy.scope.scope_id, as_of=active_as_of) is None


def test_future_cutoff_and_raw_stream_tamper_fail_closed() -> None:
    evidence = make_r2_evidence()
    policy = make_r2_policy(evidence)
    decision, decision_authorization = make_r2_decision(evidence, policy)
    lifecycle = make_r2_lifecycle_authorization(decision)
    lifecycle_source = _LifecycleAuthorizationSource(lifecycle)
    clock = _Clock(policy.active_from)
    runtime = build_django_r2_market_structure_promotion_runtime(
        policy_source=_PolicySource(policy),
        evidence_provider=_EvidenceProvider(evidence),
        decision_authorization_source=_DecisionAuthorizationSource(decision_authorization),
        lifecycle_authorization_source=lifecycle_source,
        clock=clock,
    )
    runtime.register_policy.execute(policy.reference)
    future = decision.decided_at
    clock.current = future - timedelta(microseconds=1)
    with pytest.raises(R2MarketStructurePromotionEvidenceError) as error:
        runtime.evaluate.execute(
            EvaluateR2MarketStructurePromotionCommand(
                policy_ref=policy.reference,
                evidence_ref=decision.evidence.reference,
                authorization_ref=decision_authorization.reference,
                as_of=future,
            )
        )
    assert error.value.reason_code == "r2_market_structure.future_cutoff"

    clock.current = decision.decided_at + timedelta(minutes=1)
    runtime.evaluate.execute(
        EvaluateR2MarketStructurePromotionCommand(
            policy_ref=policy.reference,
            evidence_ref=decision.evidence.reference,
            authorization_ref=decision_authorization.reference,
            as_of=decision.decided_at,
        )
    )
    clock.current = lifecycle.occurred_at - timedelta(microseconds=1)
    with pytest.raises(R2MarketStructurePromotionEvidenceError) as lifecycle_error:
        runtime.apply_lifecycle.execute(
            ApplyR2MarketStructureLifecycleCommand(
                scope_id=policy.scope.scope_id,
                action=R2MarketStructureLifecycleAction.PROMOTE,
                decision_ref=decision.reference,
                authorization_ref=lifecycle.reference,
            )
        )
    assert lifecycle_error.value.reason_code == "r2_market_structure.future_cutoff"
    clock.current = lifecycle.occurred_at + timedelta(minutes=1)
    event = runtime.apply_lifecycle.execute(
        ApplyR2MarketStructureLifecycleCommand(
            scope_id=policy.scope.scope_id,
            action=R2MarketStructureLifecycleAction.PROMOTE,
            decision_ref=decision.reference,
            authorization_ref=lifecycle.reference,
        )
    )
    model = R2MarketStructurePromotionLifecycleEventModel._default_manager.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_r2_ms_promotion_lifecycle " "SET stream_id = %s WHERE id = %s",
            ["raw-hidden-stream", model.pk],
        )
    active_as_of = event.recorded_at + timedelta(minutes=1)
    clock.current = active_as_of
    assert runtime.get_active.get_active(policy.scope.scope_id, as_of=active_as_of) is None
