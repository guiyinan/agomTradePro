"""Focused repository selection coverage for the R5 research-control gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.research.application import (
    r5_relative_value_promotion_decision as promotion_decision_application,
)
from apps.research.application.r5_relative_value_monitoring_persistence import (
    RegisterR5MonitoringAssessment,
)
from apps.research.application.r5_research_control_adapters import (
    R5LatestCompleteMonitoringExactAdapter,
)
from apps.research.application.r5_research_control_preflight import (
    EvaluateR5ResearchControlPreflightCommand,
    R5ResearchControlBlockerCode,
    R5ResearchControlPreflightStatus,
)
from apps.research.domain import r5_relative_value_promotion_decision as promotion_decision_domain
from apps.research.domain.r5_relative_value_promotion_policy import (
    R5RelativeValuePromotionPolicy,
)
from apps.research.domain.r5_relative_value_promotion_trial import (
    R5RelativeValuePromotionTrial,
)
from apps.research.infrastructure.r5_relative_value_monitoring_models import (
    R5MonitoringAssessmentLedgerModel,
    R5MonitoringObservationLedgerModel,
)
from apps.research.infrastructure.r5_relative_value_monitoring_repository import (
    DjangoR5MonitoringRepository,
    _build_r5_monitoring_writer,
)
from apps.research.infrastructure.r5_relative_value_promotion_models import (
    R5PromotionArtifactModel,
    R5PromotionDecisionAuthorizationModel,
    R5PromotionDecisionBundleModel,
    R5PromotionLifecycleAuthorizationModel,
    R5PromotionLifecycleEventModel,
)
from apps.research.r5_research_control_composition import (
    build_django_r5_research_control_runtime,
)
from tests.component.research import (
    test_r5_relative_value_promotion_repository as promotion_repository_tests,
)
from tests.component.research.test_r5_relative_value_monitoring_repository import (
    _Clock,
    _Evaluator,
    _evidence,
    _reevaluated_evidence,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_repository_selects_latest_complete_for_exact_active_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def extended_valid_until(
        *,
        policy: R5RelativeValuePromotionPolicy,
        trial: R5RelativeValuePromotionTrial,
        decided_at: datetime,
    ) -> datetime:
        del policy, decided_at
        return trial.valid_until

    monkeypatch.setattr(
        promotion_repository_tests,
        "r5_relative_value_promotion_decision_valid_until",
        extended_valid_until,
    )
    monkeypatch.setattr(
        promotion_decision_application,
        "r5_relative_value_promotion_decision_valid_until",
        extended_valid_until,
    )
    monkeypatch.setattr(
        promotion_decision_domain,
        "r5_relative_value_promotion_decision_valid_until",
        extended_valid_until,
    )
    first_evidence, first_command = _evidence(monkeypatch)
    assert first_evidence.active_lifecycle is not None
    clock = _Clock(first_command.as_of + timedelta(minutes=1))
    first = RegisterR5MonitoringAssessment(
        evaluator=_Evaluator(first_evidence),
        writer=_build_r5_monitoring_writer(clock=clock),
    ).execute(first_command)
    second_evidence, second_command = _reevaluated_evidence(
        first_evidence,
        first_command,
        evaluated_at=first_command.as_of + timedelta(minutes=1),
    )
    clock.current = second_command.as_of + timedelta(minutes=1)
    second = RegisterR5MonitoringAssessment(
        evaluator=_Evaluator(second_evidence),
        writer=_build_r5_monitoring_writer(clock=clock),
    ).execute(second_command)
    repository = DjangoR5MonitoringRepository(clock=clock)

    selected = repository.get_latest_complete_for_active(
        active_lifecycle=first_evidence.active_lifecycle,
        as_of=clock.current,
    )
    projection = R5LatestCompleteMonitoringExactAdapter(repository).get_latest_complete(
        active_lifecycle=first_evidence.active_lifecycle,
        as_of=clock.current,
    )

    assert selected == second
    assert selected != first
    assert projection is not None
    assert projection.assessment_id == second.assessment_ref.assessment_id
    assert projection.assessment_hash == second.assessment_ref.assessment_hash
    assert projection.latest_period_id == second.assessment.latest_period_id


def test_public_runtime_is_empty_database_blocked_and_zero_write() -> None:
    before = (
        R5MonitoringAssessmentLedgerModel._default_manager.count(),
        R5MonitoringObservationLedgerModel._default_manager.count(),
        R5PromotionArtifactModel._default_manager.count(),
        R5PromotionDecisionAuthorizationModel._default_manager.count(),
        R5PromotionDecisionBundleModel._default_manager.count(),
        R5PromotionLifecycleAuthorizationModel._default_manager.count(),
        R5PromotionLifecycleEventModel._default_manager.count(),
    )
    runtime = build_django_r5_research_control_runtime()

    result = runtime.preflight.execute(
        EvaluateR5ResearchControlPreflightCommand(
            scope_id="empty-r5-scope",
            as_of=datetime(2020, 1, 1, tzinfo=UTC),
        )
    )

    assert result.status is R5ResearchControlPreflightStatus.BLOCKED
    assert result.blocker_codes == (R5ResearchControlBlockerCode.ACTIVE_LIFECYCLE_UNAVAILABLE,)
    assert (
        R5MonitoringAssessmentLedgerModel._default_manager.count(),
        R5MonitoringObservationLedgerModel._default_manager.count(),
        R5PromotionArtifactModel._default_manager.count(),
        R5PromotionDecisionAuthorizationModel._default_manager.count(),
        R5PromotionDecisionBundleModel._default_manager.count(),
        R5PromotionLifecycleAuthorizationModel._default_manager.count(),
        R5PromotionLifecycleEventModel._default_manager.count(),
    ) == before
