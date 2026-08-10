"""Application contracts for R2 explanatory-trial monitoring persistence."""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

import pytest

from apps.research.application.r2_market_structure_trial_monitoring import (
    EvaluateR2MarketStructureExplanatoryTrial,
    EvaluateR2MarketStructureMonitoring,
    EvaluateR2MarketStructureTrialCommand,
    R2ExplanatoryTrialEvaluationEvidence,
    R2MonitoringEvaluationEvidence,
    R2TrialMonitoringUnavailable,
)
from apps.research.application.r2_market_structure_trial_monitoring_persistence import (
    R2TrialMonitoringPersistenceUnavailable,
    RegisterR2ExplanatoryTrialAssessment,
    RegisterR2MonitoringAssessment,
)
from apps.research.domain.r2_market_structure_trial_monitoring import (
    R2AuditExplanatoryOutcome,
    R2AuditMetric,
    R2EvidenceRef,
    R2MonitoringRawFact,
    R2PublicationRef,
)
from tests.unit.research.r2_market_structure_trial_monitoring_factories import (
    NOW,
    build_r2_scenario,
)
from tests.unit.research.test_r2_market_structure_trial_monitoring import (
    _AuditProvider,
    _Clock,
    _CycleProvider,
    _FactProvider,
    _PolicyProvider,
    _PublicationProvider,
    _UnitOfWork,
)


def _command() -> EvaluateR2MarketStructureTrialCommand:
    scenario = build_r2_scenario()
    return EvaluateR2MarketStructureTrialCommand(
        policy_id=scenario.policy.policy_id,
        policy_version=scenario.policy.policy_version,
        expected_policy_hash=scenario.policy.content_hash,
        as_of=NOW,
    )


def _trial_evidence() -> R2ExplanatoryTrialEvaluationEvidence:
    scenario = build_r2_scenario()
    from apps.research.domain.r2_market_structure_trial_monitoring import (
        evaluate_r2_explanatory_trial,
    )

    assessment = evaluate_r2_explanatory_trial(
        policy=scenario.policy,
        taxonomy_publication=scenario.taxonomy,
        calendar_publication=scenario.calendar,
        cycle_evidence=scenario.cycles,
        audit_outcome=scenario.audit,
        assessed_at=NOW,
    )
    return R2ExplanatoryTrialEvaluationEvidence(
        policy=scenario.policy,
        taxonomy_publication=scenario.taxonomy,
        calendar_publication=scenario.calendar,
        cycles=scenario.cycles,
        audit_outcome=scenario.audit,
        assessment=assessment,
    ).validated_copy()


def _monitoring_evidence() -> R2MonitoringEvaluationEvidence:
    scenario = build_r2_scenario()
    from apps.research.domain.r2_market_structure_trial_monitoring import (
        evaluate_r2_monitoring,
    )

    trial = _trial_evidence()
    assessment = evaluate_r2_monitoring(
        policy=scenario.policy,
        taxonomy_publication=scenario.taxonomy,
        calendar_publication=scenario.calendar,
        trial_assessment=trial.assessment,
        facts=scenario.monitoring_facts,
        assessed_at=NOW,
    )
    return R2MonitoringEvaluationEvidence(
        trial=trial,
        facts=scenario.monitoring_facts,
        assessment=assessment,
    ).validated_copy()


@dataclass
class _Evaluator:
    evidence: R2ExplanatoryTrialEvaluationEvidence | R2MonitoringEvaluationEvidence
    unit_of_work_key: str = "django:r2-test"
    calls: int = 0
    unavailable: bool = False

    def execute_evidence(
        self,
        command: EvaluateR2MarketStructureTrialCommand,
    ) -> R2ExplanatoryTrialEvaluationEvidence | R2MonitoringEvaluationEvidence:
        self.calls += 1
        if self.unavailable:
            raise R2TrialMonitoringUnavailable("owner unavailable")
        return self.evidence


@dataclass
class _Writer:
    unit_of_work_key: str = "django:r2-test"
    atomic_entries: int = 0
    trial_writes: int = 0
    monitoring_writes: int = 0

    @contextmanager
    def atomic(self) -> AbstractContextManager[None]:
        self.atomic_entries += 1
        yield

    def append_trial(self, *, command, evidence):
        self.trial_writes += 1
        return evidence

    def append_monitoring(self, *, command, evidence):
        self.monitoring_writes += 1
        return evidence


@dataclass
class _AuditSequenceProvider:
    outcomes: tuple[R2AuditExplanatoryOutcome, ...]
    calls: int = 0
    unit_of_work_key: str = "django:r2-test"

    def get_exact(
        self,
        *,
        policy_ref: R2EvidenceRef,
        audit_plan_ref: R2EvidenceRef,
        cycle_evidence_refs: tuple[R2EvidenceRef, ...],
        expected_outcome_id: str,
        expected_outcome_version: str,
        as_of: datetime,
    ) -> R2AuditExplanatoryOutcome | None:
        del (
            policy_ref,
            audit_plan_ref,
            cycle_evidence_refs,
            expected_outcome_id,
            expected_outcome_version,
            as_of,
        )
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        return outcome


@dataclass
class _FactSequenceProvider:
    fact_sets: tuple[tuple[R2MonitoringRawFact, ...], ...]
    calls: int = 0
    unit_of_work_key: str = "django:r2-test"

    def list_exact(
        self,
        *,
        policy_ref: R2EvidenceRef,
        taxonomy_publication_ref: R2PublicationRef,
        calendar_publication_ref: R2PublicationRef,
        expected_fact_identities: tuple[tuple[str, str], ...],
        as_of: datetime,
    ) -> tuple[R2MonitoringRawFact, ...]:
        del (
            policy_ref,
            taxonomy_publication_ref,
            calendar_publication_ref,
            expected_fact_identities,
            as_of,
        )
        facts = self.fact_sets[min(self.calls, len(self.fact_sets) - 1)]
        self.calls += 1
        return facts


def _concrete_trial_evaluator(
    audit_provider: _AuditProvider | _AuditSequenceProvider,
) -> EvaluateR2MarketStructureExplanatoryTrial:
    scenario = build_r2_scenario()
    return EvaluateR2MarketStructureExplanatoryTrial(
        policy_provider=_PolicyProvider(scenario.policy),
        publication_provider=_PublicationProvider(
            scenario.taxonomy,
            scenario.calendar,
        ),
        cycle_provider=_CycleProvider(scenario.cycles),
        audit_provider=audit_provider,
        clock=_Clock(),
        unit_of_work=_UnitOfWork(),
    )


def test_trial_registration_is_id_only_atomic_and_owner_derived() -> None:
    evaluator = _Evaluator(_trial_evidence())
    writer = _Writer()
    use_case = RegisterR2ExplanatoryTrialAssessment(
        evaluator=evaluator,
        writer=writer,
    )

    result = use_case.execute(_command())

    assert result == evaluator.evidence
    assert evaluator.calls == 2
    assert writer.atomic_entries == 1
    assert writer.trial_writes == 1
    assert writer.monitoring_writes == 0


def test_monitoring_registration_is_id_only_atomic_and_owner_derived() -> None:
    evaluator = _Evaluator(_monitoring_evidence())
    writer = _Writer()
    use_case = RegisterR2MonitoringAssessment(evaluator=evaluator, writer=writer)

    result = use_case.execute(_command())

    assert result == evaluator.evidence
    assert evaluator.calls == 2
    assert writer.atomic_entries == 1
    assert writer.monitoring_writes == 1


def test_registration_rejects_uow_mismatch_and_owner_unavailability_without_write() -> None:
    writer = _Writer()
    with pytest.raises(R2TrialMonitoringPersistenceUnavailable, match="unit of work"):
        RegisterR2ExplanatoryTrialAssessment(
            evaluator=_Evaluator(_trial_evidence(), unit_of_work_key="django:other"),
            writer=writer,
        )

    evaluator = _Evaluator(_trial_evidence(), unavailable=True)
    use_case = RegisterR2ExplanatoryTrialAssessment(evaluator=evaluator, writer=writer)
    with pytest.raises(R2TrialMonitoringPersistenceUnavailable, match="owner graph"):
        use_case.execute(_command())
    assert writer.trial_writes == 0


def test_real_concrete_evaluators_compose_with_persistence_uow_protocol() -> None:
    scenario = build_r2_scenario()
    trial_evaluator = _concrete_trial_evaluator(_AuditProvider(scenario.audit))
    monitoring_evaluator = EvaluateR2MarketStructureMonitoring(
        policy_provider=_PolicyProvider(scenario.policy),
        publication_provider=_PublicationProvider(
            scenario.taxonomy,
            scenario.calendar,
        ),
        cycle_provider=_CycleProvider(scenario.cycles),
        audit_provider=_AuditProvider(scenario.audit),
        monitoring_fact_provider=_FactProvider(scenario.monitoring_facts),
        clock=_Clock(),
        unit_of_work=_UnitOfWork(),
    )
    trial_writer = _Writer()
    monitoring_writer = _Writer()

    trial = RegisterR2ExplanatoryTrialAssessment(
        evaluator=trial_evaluator,
        writer=trial_writer,
    ).execute(_command())
    monitoring = RegisterR2MonitoringAssessment(
        evaluator=monitoring_evaluator,
        writer=monitoring_writer,
    ).execute(_command())

    assert trial == _trial_evidence()
    assert monitoring == _monitoring_evidence()
    assert trial_writer.trial_writes == 1
    assert monitoring_writer.monitoring_writes == 1


def test_both_concrete_evaluators_expose_a_live_exact_uow_baseline() -> None:
    scenario = build_r2_scenario()
    trial_policy = _PolicyProvider(scenario.policy)
    trial_evaluator = EvaluateR2MarketStructureExplanatoryTrial(
        policy_provider=trial_policy,
        publication_provider=_PublicationProvider(
            scenario.taxonomy,
            scenario.calendar,
        ),
        cycle_provider=_CycleProvider(scenario.cycles),
        audit_provider=_AuditProvider(scenario.audit),
        clock=_Clock(),
        unit_of_work=_UnitOfWork(),
    )
    monitoring_policy = _PolicyProvider(scenario.policy)
    monitoring_evaluator = EvaluateR2MarketStructureMonitoring(
        policy_provider=monitoring_policy,
        publication_provider=_PublicationProvider(
            scenario.taxonomy,
            scenario.calendar,
        ),
        cycle_provider=_CycleProvider(scenario.cycles),
        audit_provider=_AuditProvider(scenario.audit),
        monitoring_fact_provider=_FactProvider(scenario.monitoring_facts),
        clock=_Clock(),
        unit_of_work=_UnitOfWork(),
    )

    assert trial_evaluator.unit_of_work_key == "django:r2-test"
    assert monitoring_evaluator.unit_of_work_key == "django:r2-test"
    trial_policy.unit_of_work_key = "django:changed"
    monitoring_policy.unit_of_work_key = "django:changed"
    with pytest.raises(ValueError, match="share one unit of work"):
        _ = trial_evaluator.unit_of_work_key
    with pytest.raises(ValueError, match="share one unit of work"):
        _ = monitoring_evaluator.unit_of_work_key


def test_third_owner_read_drift_blocks_before_trial_append() -> None:
    scenario = build_r2_scenario()
    changed_metric = replace(
        scenario.audit.metrics[1],
        value=Decimal("0.79"),
    )
    assert isinstance(changed_metric, R2AuditMetric)
    changed_audit = replace(
        scenario.audit,
        metrics=(
            scenario.audit.metrics[0],
            changed_metric,
            *scenario.audit.metrics[2:],
        ),
    )
    provider = _AuditSequenceProvider(
        (scenario.audit, scenario.audit, changed_audit, changed_audit)
    )
    evaluator = _concrete_trial_evaluator(provider)
    writer = _Writer()

    with pytest.raises(
        R2TrialMonitoringPersistenceUnavailable,
        match="changed during registration",
    ):
        RegisterR2ExplanatoryTrialAssessment(
            evaluator=evaluator,
            writer=writer,
        ).execute(_command())

    assert provider.calls == 4
    assert writer.trial_writes == 0


def test_third_monitoring_fact_read_drift_blocks_before_append() -> None:
    scenario = build_r2_scenario()
    changed_metric = replace(
        scenario.monitoring_facts[-1].metrics[1],
        value=Decimal("0.77"),
    )
    changed_fact = replace(
        scenario.monitoring_facts[-1],
        metrics=(
            scenario.monitoring_facts[-1].metrics[0],
            changed_metric,
            scenario.monitoring_facts[-1].metrics[2],
        ),
    )
    changed_facts = (*scenario.monitoring_facts[:-1], changed_fact)
    fact_provider = _FactSequenceProvider(
        (
            scenario.monitoring_facts,
            scenario.monitoring_facts,
            changed_facts,
            changed_facts,
        )
    )
    evaluator = EvaluateR2MarketStructureMonitoring(
        policy_provider=_PolicyProvider(scenario.policy),
        publication_provider=_PublicationProvider(
            scenario.taxonomy,
            scenario.calendar,
        ),
        cycle_provider=_CycleProvider(scenario.cycles),
        audit_provider=_AuditProvider(scenario.audit),
        monitoring_fact_provider=fact_provider,
        clock=_Clock(),
        unit_of_work=_UnitOfWork(),
    )
    writer = _Writer()

    with pytest.raises(
        R2TrialMonitoringPersistenceUnavailable,
        match="changed during registration",
    ):
        RegisterR2MonitoringAssessment(
            evaluator=evaluator,
            writer=writer,
        ).execute(_command())

    assert fact_provider.calls == 4
    assert writer.monitoring_writes == 0
