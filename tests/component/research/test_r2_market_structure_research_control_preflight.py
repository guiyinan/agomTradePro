"""SQLite boundaries for the read-only R2 research-control preflight."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.research.application.r2_market_structure_research_control_preflight import (
    EvaluateR2ResearchControlPreflightCommand,
    R2ResearchControlBlockerCode,
    R2ResearchControlPreflightStatus,
)
from apps.research.application.r2_market_structure_trial_monitoring_persistence import (
    RegisterR2ExplanatoryTrialAssessment,
    RegisterR2MonitoringAssessment,
)
from apps.research.infrastructure.r2_market_structure_research_control_repository import (
    DjangoR2ResearchControlReadRepository,
)
from apps.research.infrastructure.r2_market_structure_trial_monitoring_models import (
    R2ExplanatoryTrialAssessmentLedgerModel,
    R2MonitoringAssessmentLedgerModel,
    R2MonitoringObservationLedgerModel,
)
from apps.research.infrastructure.r2_market_structure_trial_monitoring_repository import (
    _build_r2_trial_monitoring_writer,
)
from apps.research.infrastructure.r2_market_structure_trial_policy_models import (
    R2MarketStructureTrialPolicyLedgerModel,
)
from apps.research.r2_market_structure_research_control_composition import (
    build_django_r2_research_control_runtime,
)
from tests.component.research.test_r2_market_structure_trial_monitoring_repository import (
    _Clock,
    _Evaluator,
)
from tests.unit.research.r2_market_structure_trial_monitoring_factories import NOW
from tests.unit.research.test_r2_market_structure_trial_monitoring_persistence import (
    _command,
    _monitoring_evidence,
    _trial_evidence,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_repository_selects_the_latest_complete_pair_for_exact_policy() -> None:
    clock = _Clock(NOW + timedelta(minutes=1))
    writer = _build_r2_trial_monitoring_writer(clock=clock)
    trial = _trial_evidence()
    monitoring = _monitoring_evidence()
    command = _command()
    RegisterR2ExplanatoryTrialAssessment(
        evaluator=_Evaluator(trial),
        writer=writer,
    ).execute(command)
    RegisterR2MonitoringAssessment(
        evaluator=_Evaluator(monitoring),
        writer=writer,
    ).execute(command)
    repository = DjangoR2ResearchControlReadRepository(
        clock=_Clock(NOW + timedelta(minutes=2)),
    )

    selected = repository.get_latest_complete(
        policy_ref=trial.policy.reference,
        as_of=NOW + timedelta(minutes=1),
    )

    assert selected is not None
    assert selected.trial.evidence == trial
    assert selected.monitoring.evidence == monitoring
    assert selected.monitoring.trial_reference == selected.trial.reference


def test_public_runtime_empty_database_is_blocked_and_zero_write() -> None:
    before = (
        R2MarketStructureTrialPolicyLedgerModel._default_manager.count(),
        R2ExplanatoryTrialAssessmentLedgerModel._default_manager.count(),
        R2MonitoringAssessmentLedgerModel._default_manager.count(),
        R2MonitoringObservationLedgerModel._default_manager.count(),
    )
    runtime = build_django_r2_research_control_runtime()

    result = runtime.preflight.execute(
        EvaluateR2ResearchControlPreflightCommand(
            policy_id="missing-r2-policy",
            policy_version="v1",
            expected_policy_hash="a" * 64,
            as_of=datetime(2020, 1, 1, tzinfo=UTC),
        )
    )

    assert result.status is R2ResearchControlPreflightStatus.BLOCKED
    assert result.blocker_codes == (
        R2ResearchControlBlockerCode.AUDIT_MONITORING_FACTS_UNAVAILABLE,
        R2ResearchControlBlockerCode.AUDIT_OUTCOME_UNAVAILABLE,
        R2ResearchControlBlockerCode.CALENDAR_PUBLICATION_UNAVAILABLE,
        R2ResearchControlBlockerCode.CYCLE_EVIDENCE_UNAVAILABLE,
        R2ResearchControlBlockerCode.LATEST_COMPLETE_TRIAL_MONITORING_UNAVAILABLE,
        R2ResearchControlBlockerCode.POLICY_UNAVAILABLE,
        R2ResearchControlBlockerCode.TAXONOMY_PUBLICATION_UNAVAILABLE,
    )
    assert not hasattr(runtime, "register")
    assert not hasattr(runtime, "publish_current")
    assert not hasattr(runtime, "decide")
    assert not hasattr(runtime, "execute")
    assert (
        R2MarketStructureTrialPolicyLedgerModel._default_manager.count(),
        R2ExplanatoryTrialAssessmentLedgerModel._default_manager.count(),
        R2MonitoringAssessmentLedgerModel._default_manager.count(),
        R2MonitoringObservationLedgerModel._default_manager.count(),
    ) == before
