"""SQLite component coverage for the R4 research-control read boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import pytest
from django.db import transaction

from apps.research.application.r4_promotion_monitoring import (
    EvaluateR4PromotionMonitoringCommand,
    R4MonitoringEvaluationEvidence,
)
from apps.research.application.r4_promotion_monitoring_persistence import (
    R4MonitoringPersistenceCorruption,
)
from apps.research.application.r4_research_control_preflight import (
    EvaluateR4ResearchControlPreflightCommand,
    R4ResearchControlBlockerCode,
    R4ResearchControlPreflightStatus,
)
from apps.research.domain.r4_promotion_decision import R4PromotionDecision
from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.domain.r4_promotion_monitoring import (
    R4MonitoringPolicy,
    evaluate_r4_promotion_monitoring,
)
from apps.research.infrastructure.r4_promotion_model_values import (
    _decision_bundle_model_values,
    _decision_receipt_model_values,
    _policy_model_values,
)
from apps.research.infrastructure.r4_promotion_models import (
    R4PromotionDecisionBundleModel,
    R4PromotionDecisionReceiptModel,
    R4PromotionPolicyModel,
    _activate_r4_promotion_unit_of_work,
    _claim_r4_promotion_insert,
)
from apps.research.infrastructure.r4_promotion_monitoring_models import (
    R4MonitoringAssessmentLedgerModel,
    R4MonitoringAuditSnapshotModel,
    R4MonitoringObservationLedgerModel,
)
from apps.research.infrastructure.r4_promotion_monitoring_repository import (
    _DjangoR4MonitoringStore,
)
from apps.research.infrastructure.r4_research_control_repository import (
    DjangoR4ResearchControlMonitoringRepository,
)
from apps.research.r4_research_control_composition import (
    _build_django_r4_research_control_test_runtime,
    build_django_r4_research_control_runtime,
)
from tests.unit.research.r4_promotion_factories import promotion_decision_bundle
from tests.unit.research.r4_promotion_monitoring_factories import (
    monitoring_calendar,
    monitoring_decision,
    monitoring_observation,
    monitoring_policy,
)

pytestmark = pytest.mark.django_db(transaction=True)


@dataclass
class _FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _persist_active_decision(decision: R4PromotionDecision) -> None:
    bundle = promotion_decision_bundle(decision)
    token = object()
    with transaction.atomic(), _activate_r4_promotion_unit_of_work(token):
        policy_values = _policy_model_values(decision.policy)
        with _claim_r4_promotion_insert(
            token=token,
            model_type=R4PromotionPolicyModel,
            expected_values=policy_values,
        ):
            policy_model = R4PromotionPolicyModel._default_manager.create(**policy_values)
        receipt_values = {
            **_decision_receipt_model_values(bundle.receipt),
            "policy_id": policy_model.pk,
        }
        with _claim_r4_promotion_insert(
            token=token,
            model_type=R4PromotionDecisionReceiptModel,
            expected_values=receipt_values,
        ):
            receipt_model = R4PromotionDecisionReceiptModel._default_manager.create(
                **receipt_values
            )
        bundle_values = {
            **_decision_bundle_model_values(bundle),
            "receipt_id": receipt_model.pk,
            "policy_id": policy_model.pk,
        }
        with _claim_r4_promotion_insert(
            token=token,
            model_type=R4PromotionDecisionBundleModel,
            expected_values=bundle_values,
        ):
            R4PromotionDecisionBundleModel._default_manager.create(**bundle_values)


def _command_and_evidence(
    *,
    period_count: int,
    decision: R4PromotionDecision,
    policy: R4MonitoringPolicy | None = None,
) -> tuple[EvaluateR4PromotionMonitoringCommand, R4MonitoringEvaluationEvidence]:
    calendar = monitoring_calendar(decision)
    selected_policy = policy or monitoring_policy(decision, calendar)
    observations = tuple(
        replace(
            monitoring_observation(
                period_index=index,
                decision=decision,
                calendar=calendar,
                policy=selected_policy,
            ),
            observation_id=(f"r4-monitoring-observation-{index}-{selected_policy.policy_id}"),
        )
        for index in range(period_count)
    )
    as_of = calendar.valid_from + timedelta(hours=period_count, minutes=30)
    command = EvaluateR4PromotionMonitoringCommand(
        active_decision=R4PromotionDecisionIdentity.from_decision(decision),
        policy_id=selected_policy.policy_id,
        policy_version=selected_policy.policy_version,
        expected_policy_hash=selected_policy.content_hash,
        as_of=as_of,
    )
    assessment = evaluate_r4_promotion_monitoring(
        requested_active_decision=command.active_decision,
        requested_policy_id=command.policy_id,
        requested_policy_version=command.policy_version,
        expected_policy_hash=command.expected_policy_hash,
        active_decision=decision,
        portfolio_result=decision.trial.portfolio_record,
        current_r3_attestation=decision.trial.current_r3_attestation,
        policy=selected_policy,
        period_calendar=calendar,
        observations=observations,
        evaluated_at=as_of,
    )
    return command, R4MonitoringEvaluationEvidence(
        active_decision=decision,
        portfolio_result=decision.trial.portfolio_record,
        current_r3_attestation=decision.trial.current_r3_attestation,
        policy=selected_policy,
        period_calendar=calendar,
        observations=observations,
        assessment=assessment,
    )


def _append(
    store: _DjangoR4MonitoringStore,
    command: EvaluateR4PromotionMonitoringCommand,
    evidence: R4MonitoringEvaluationEvidence,
):
    with store.atomic():
        return store.append_evidence(command=command, evidence=evidence)


def test_latest_complete_query_is_empty_then_selects_latest_period_exactly() -> None:
    decision = monitoring_decision()
    identity = R4PromotionDecisionIdentity.from_decision(decision)
    first_command, first_evidence = _command_and_evidence(
        period_count=2,
        decision=decision,
    )
    second_command, second_evidence = _command_and_evidence(
        period_count=3,
        decision=decision,
    )
    clock = _FixedClock(second_command.as_of + timedelta(minutes=10))
    repository = DjangoR4ResearchControlMonitoringRepository(clock=clock)
    assert (
        repository.get_latest_complete_for_active(
            active_decision=identity,
            as_of=first_command.as_of,
        )
        is None
    )

    _persist_active_decision(decision)
    store = _DjangoR4MonitoringStore(clock=clock)
    clock.value = first_command.as_of + timedelta(minutes=1)
    first = _append(store, first_command, first_evidence)
    clock.value = second_command.as_of + timedelta(minutes=1)
    second = _append(store, second_command, second_evidence)

    assert (
        repository.get_latest_complete_for_active(
            active_decision=identity,
            as_of=second.ledger_recorded_at,
        )
        == second
    )
    assert (
        repository.get_latest_complete_for_active(
            active_decision=identity,
            as_of=second.ledger_recorded_at - timedelta(microseconds=1),
        )
        == first
    )

    current_assessment = evaluate_r4_promotion_monitoring(
        requested_active_decision=second_evidence.assessment.active_decision,
        requested_policy_id=second_evidence.policy.policy_id,
        requested_policy_version=second_evidence.policy.policy_version,
        expected_policy_hash=second_evidence.policy.content_hash,
        active_decision=second_evidence.active_decision,
        portfolio_result=second_evidence.portfolio_result,
        current_r3_attestation=second_evidence.current_r3_attestation,
        policy=second_evidence.policy,
        period_calendar=second_evidence.period_calendar,
        observations=second_evidence.observations,
        evaluated_at=second.ledger_recorded_at,
    )
    current_evidence = replace(second_evidence, assessment=current_assessment)

    class _ActiveQuery:
        def get_active(self, scope_ref: object, *, as_of: datetime):
            del scope_ref
            assert as_of == second.ledger_recorded_at
            return promotion_decision_bundle(decision)

    class _OwnerGraphProvider:
        unit_of_work_key = "django:default"

        def execute_evidence(
            self,
            command: EvaluateR4PromotionMonitoringCommand,
        ) -> R4MonitoringEvaluationEvidence:
            assert command.as_of == second.ledger_recorded_at
            return current_evidence

    runtime = _build_django_r4_research_control_test_runtime(
        active_promotion_query=_ActiveQuery(),
        owner_graph_provider=_OwnerGraphProvider(),
    )
    preflight = runtime.preflight.execute(
        EvaluateR4ResearchControlPreflightCommand(
            scope_id=decision.scope.scope_id,
            as_of=second.ledger_recorded_at,
        )
    )
    assert preflight.status is R4ResearchControlPreflightStatus.ELIGIBLE_FOR_MANUAL_CONSUMER_REVIEW


def test_latest_complete_same_rank_fork_fails_closed() -> None:
    decision = monitoring_decision()
    identity = R4PromotionDecisionIdentity.from_decision(decision)
    first_command, first_evidence = _command_and_evidence(
        period_count=2,
        decision=decision,
    )
    fork_policy = replace(
        first_evidence.policy,
        policy_id="r4-post-promotion-monitoring-fork",
        policy_version="policy.v2",
    )
    fork_command, fork_evidence = _command_and_evidence(
        period_count=2,
        decision=decision,
        policy=fork_policy,
    )
    assert fork_command.as_of == first_command.as_of
    _persist_active_decision(decision)
    clock = _FixedClock(first_command.as_of + timedelta(minutes=1))
    store = _DjangoR4MonitoringStore(clock=clock)
    _append(store, first_command, first_evidence)
    _append(store, fork_command, fork_evidence)

    repository = DjangoR4ResearchControlMonitoringRepository(clock=clock)
    with pytest.raises(R4MonitoringPersistenceCorruption, match="multiple winners"):
        repository.get_latest_complete_for_active(
            active_decision=identity,
            as_of=clock.value,
        )


def test_public_runtime_is_empty_blocked_and_zero_write() -> None:
    decision = monitoring_decision()
    command, _ = _command_and_evidence(period_count=2, decision=decision)
    before = (
        R4MonitoringObservationLedgerModel._default_manager.count(),
        R4MonitoringAssessmentLedgerModel._default_manager.count(),
        R4MonitoringAuditSnapshotModel._default_manager.count(),
    )
    runtime = build_django_r4_research_control_runtime()

    result = runtime.preflight.execute(
        EvaluateR4ResearchControlPreflightCommand(
            scope_id=decision.scope.scope_id,
            as_of=command.as_of,
        )
    )

    assert result.blocker_codes == (R4ResearchControlBlockerCode.ACTIVE_PROMOTION_UNAVAILABLE,)
    assert (
        R4MonitoringObservationLedgerModel._default_manager.count(),
        R4MonitoringAssessmentLedgerModel._default_manager.count(),
        R4MonitoringAuditSnapshotModel._default_manager.count(),
    ) == before
