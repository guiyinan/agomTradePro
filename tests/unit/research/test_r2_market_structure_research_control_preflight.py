"""Read-only research-control boundary for the R2 evidence graph."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from inspect import signature

import pytest

from apps.research.application.r2_market_structure_research_control_preflight import (
    EvaluateR2ResearchControlPreflight,
    EvaluateR2ResearchControlPreflightCommand,
    R2LatestCompleteTrialMonitoringEvidence,
    R2ResearchControlBlockerCode,
    R2ResearchControlPreflightStatus,
    R2ResearchControlUnavailable,
)
from apps.research.application.r2_market_structure_trial_monitoring_persistence import (
    R2MonitoringAssessmentRef,
    R2PersistedMonitoringAssessment,
    R2PersistedTrialAssessment,
    R2TrialAssessmentRef,
    R2TrialMonitoringPersistenceCorruption,
)
from apps.research.domain.r2_market_structure_trial_monitoring import (
    R2CanonicalPublicationEvidence,
    R2CyclePITEvidence,
    R2EvidenceRef,
    R2PublicationKind,
)
from apps.research.infrastructure.r2_market_structure_research_control_repository import (
    _select_latest_complete,
)
from apps.research.r2_market_structure_research_control_composition import (
    build_django_r2_research_control_runtime,
)
from tests.unit.research.r2_market_structure_trial_monitoring_factories import (
    NOW,
    build_r2_scenario,
)
from tests.unit.research.test_r2_market_structure_trial_monitoring_persistence import (
    _monitoring_evidence,
    _trial_evidence,
)


class _UnitOfWork:
    unit_of_work_key = "django:r2-control-test"

    def __init__(self) -> None:
        self.atomic_entries = 0

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.atomic_entries += 1
        yield

    def server_now(self) -> datetime:
        return NOW + timedelta(minutes=2)


class _Provider:
    unit_of_work_key = "django:r2-control-test"

    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    def get_exact(self, **_kwargs: object) -> object:
        self.calls += 1
        return self.value

    def get_latest_complete(self, **_kwargs: object) -> object:
        self.calls += 1
        return self.value

    def list_exact(self, **_kwargs: object) -> object:
        self.calls += 1
        return self.value


class _SequenceProvider(_Provider):
    def __init__(self, values: tuple[object, ...]) -> None:
        super().__init__(values[0])
        self.values = values

    def get_exact(self, **_kwargs: object) -> object:
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


class _DriftingProvider(_Provider):
    def __init__(self, value: object) -> None:
        super().__init__(value)
        self.key_reads = 0

    @property
    def unit_of_work_key(self) -> str:
        self.key_reads += 1
        if self.key_reads <= 2:
            return "django:r2-control-test"
        return "django:replacement"


class _PublicationProvider:
    unit_of_work_key = "django:r2-control-test"

    def __init__(
        self,
        taxonomy: R2CanonicalPublicationEvidence,
        calendar: R2CanonicalPublicationEvidence,
    ) -> None:
        self.values = {
            R2PublicationKind.TAXONOMY: taxonomy,
            R2PublicationKind.EXPECTED_PERIOD_CALENDAR: calendar,
        }
        self.calls = 0

    def get_exact(
        self,
        *,
        kind: R2PublicationKind,
        **_kwargs: object,
    ) -> R2CanonicalPublicationEvidence:
        self.calls += 1
        return self.values[kind]


class _CycleProvider:
    unit_of_work_key = "django:r2-control-test"

    def __init__(self, cycles: tuple[R2CyclePITEvidence, ...]) -> None:
        self.values = {item.reference: item for item in cycles}
        self.calls = 0

    def get_exact(
        self,
        *,
        evidence_ref: R2EvidenceRef,
        **_kwargs: object,
    ) -> R2CyclePITEvidence:
        self.calls += 1
        return self.values[evidence_ref]


def _latest() -> R2LatestCompleteTrialMonitoringEvidence:
    trial = _trial_evidence()
    monitoring = _monitoring_evidence()
    trial_reference = R2TrialAssessmentRef("r2-trial", "v1", "a" * 64)
    return R2LatestCompleteTrialMonitoringEvidence.create(
        trial=R2PersistedTrialAssessment(
            reference=trial_reference,
            evidence=trial,
            ledger_recorded_at=NOW + timedelta(seconds=30),
        ),
        monitoring=R2PersistedMonitoringAssessment(
            reference=R2MonitoringAssessmentRef("r2-monitoring", "v1", "b" * 64),
            trial_reference=trial_reference,
            evidence=monitoring,
            ledger_recorded_at=NOW + timedelta(seconds=45),
        ),
    )


def _command() -> EvaluateR2ResearchControlPreflightCommand:
    policy = build_r2_scenario().policy
    return EvaluateR2ResearchControlPreflightCommand(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        expected_policy_hash=policy.content_hash,
        as_of=NOW + timedelta(minutes=1),
    )


def test_complete_owner_graph_is_double_read_and_remains_research_only() -> None:
    scenario = build_r2_scenario()
    policy = _Provider(scenario.policy)
    publication = _PublicationProvider(scenario.taxonomy, scenario.calendar)
    cycles = _CycleProvider(scenario.cycles)
    latest = _Provider(_latest())
    audit = _Provider(scenario.audit)
    facts = _Provider(scenario.monitoring_facts)
    uow = _UnitOfWork()

    result = EvaluateR2ResearchControlPreflight(
        policy_provider=policy,
        publication_provider=publication,
        cycle_provider=cycles,
        latest_complete_provider=latest,
        audit_provider=audit,
        monitoring_fact_provider=facts,
        unit_of_work=uow,
    ).execute(_command())

    assert result.status is R2ResearchControlPreflightStatus.EVIDENCE_GRAPH_COMPLETE
    assert result.blocker_codes == ()
    assert result.research_only is True
    assert result.must_not_use_as_predictive_signal is True
    assert result.must_not_publish_current is True
    assert result.must_not_use_for_decision is True
    assert result.must_not_execute is True
    assert (policy.calls, publication.calls, cycles.calls) == (2, 4, 4)
    assert (latest.calls, audit.calls, facts.calls) == (2, 2, 2)
    assert uow.atomic_entries == 1


def test_public_runtime_is_using_only_read_only_and_missing_owners_block() -> None:
    assert tuple(signature(build_django_r2_research_control_runtime).parameters) == ("using",)
    runtime = build_django_r2_research_control_runtime()
    assert tuple(runtime.__dataclass_fields__) == ("preflight",)
    assert not hasattr(runtime, "register")
    assert not hasattr(runtime, "publish_current")
    assert not hasattr(runtime, "decide")
    assert not hasattr(runtime, "execute")


def test_missing_publication_and_audit_owners_are_stably_blocked() -> None:
    scenario = build_r2_scenario()
    result = EvaluateR2ResearchControlPreflight(
        policy_provider=_Provider(scenario.policy),
        publication_provider=_Provider(None),
        cycle_provider=_CycleProvider(scenario.cycles),
        latest_complete_provider=_Provider(_latest()),
        audit_provider=_Provider(None),
        monitoring_fact_provider=_Provider(()),
        unit_of_work=_UnitOfWork(),
    ).execute(_command())

    assert result.status is R2ResearchControlPreflightStatus.BLOCKED
    assert result.blocker_codes == (
        R2ResearchControlBlockerCode.AUDIT_MONITORING_FACTS_UNAVAILABLE,
        R2ResearchControlBlockerCode.AUDIT_OUTCOME_UNAVAILABLE,
        R2ResearchControlBlockerCode.CALENDAR_PUBLICATION_UNAVAILABLE,
        R2ResearchControlBlockerCode.TAXONOMY_PUBLICATION_UNAVAILABLE,
    )


def test_command_is_id_only_and_live_validated_before_owner_reads() -> None:
    assert tuple(EvaluateR2ResearchControlPreflightCommand.__dataclass_fields__) == (
        "policy_id",
        "policy_version",
        "expected_policy_hash",
        "as_of",
    )
    scenario = build_r2_scenario()
    policy = _Provider(scenario.policy)
    latest = _Provider(_latest())
    service = EvaluateR2ResearchControlPreflight(
        policy_provider=policy,
        publication_provider=_PublicationProvider(
            scenario.taxonomy,
            scenario.calendar,
        ),
        cycle_provider=_CycleProvider(scenario.cycles),
        latest_complete_provider=latest,
        audit_provider=_Provider(scenario.audit),
        monitoring_fact_provider=_Provider(scenario.monitoring_facts),
        unit_of_work=_UnitOfWork(),
    )
    malformed = _command()
    object.__setattr__(malformed, "expected_policy_hash", "")

    with pytest.raises(R2ResearchControlUnavailable, match="command"):
        service.execute(malformed)

    class _NoOpValidatorCommand(EvaluateR2ResearchControlPreflightCommand):
        def __post_init__(self) -> None:
            pass

    valid = _command()
    subclass = _NoOpValidatorCommand(
        policy_id=valid.policy_id,
        policy_version=valid.policy_version,
        expected_policy_hash="",
        as_of=valid.as_of,
    )
    with pytest.raises(R2ResearchControlUnavailable, match="command"):
        service.execute(subclass)

    assert (policy.calls, latest.calls) == (0, 0)


def test_dynamic_unit_of_work_replacement_after_clock_is_stably_blocked() -> None:
    scenario = build_r2_scenario()
    policy = _DriftingProvider(scenario.policy)
    uow = _UnitOfWork()

    result = EvaluateR2ResearchControlPreflight(
        policy_provider=policy,
        publication_provider=_PublicationProvider(
            scenario.taxonomy,
            scenario.calendar,
        ),
        cycle_provider=_CycleProvider(scenario.cycles),
        latest_complete_provider=_Provider(_latest()),
        audit_provider=_Provider(scenario.audit),
        monitoring_fact_provider=_Provider(scenario.monitoring_facts),
        unit_of_work=uow,
    ).execute(_command())

    assert result.status is R2ResearchControlPreflightStatus.BLOCKED
    assert result.blocker_codes == (R2ResearchControlBlockerCode.UNIT_OF_WORK_CHANGED,)
    assert policy.calls == 0
    assert uow.atomic_entries == 1


def test_future_cutoff_is_rejected_before_owner_reads() -> None:
    scenario = build_r2_scenario()
    policy = _Provider(scenario.policy)
    latest = _Provider(_latest())
    command = replace(_command(), as_of=NOW + timedelta(minutes=3))
    service = EvaluateR2ResearchControlPreflight(
        policy_provider=policy,
        publication_provider=_PublicationProvider(
            scenario.taxonomy,
            scenario.calendar,
        ),
        cycle_provider=_CycleProvider(scenario.cycles),
        latest_complete_provider=latest,
        audit_provider=_Provider(scenario.audit),
        monitoring_fact_provider=_Provider(scenario.monitoring_facts),
        unit_of_work=_UnitOfWork(),
    )

    with pytest.raises(R2ResearchControlUnavailable, match="future"):
        service.execute(command)

    assert (policy.calls, latest.calls) == (0, 0)


def test_owner_replacement_is_blocked_after_both_complete_reads() -> None:
    scenario = build_r2_scenario()
    changed_audit = replace(
        scenario.audit,
        valid_until=scenario.audit.valid_until + timedelta(days=1),
    )
    result = EvaluateR2ResearchControlPreflight(
        policy_provider=_Provider(scenario.policy),
        publication_provider=_PublicationProvider(
            scenario.taxonomy,
            scenario.calendar,
        ),
        cycle_provider=_CycleProvider(scenario.cycles),
        latest_complete_provider=_Provider(_latest()),
        audit_provider=_SequenceProvider((scenario.audit, changed_audit)),
        monitoring_fact_provider=_Provider(scenario.monitoring_facts),
        unit_of_work=_UnitOfWork(),
    ).execute(_command())

    assert result.blocker_codes == (
        R2ResearchControlBlockerCode.OWNER_GRAPH_CHANGED_DURING_PREFLIGHT,
    )


def test_latest_complete_same_rank_fork_fails_closed() -> None:
    first = _latest()
    second = R2LatestCompleteTrialMonitoringEvidence.create(
        trial=first.trial,
        monitoring=replace(
            first.monitoring,
            reference=R2MonitoringAssessmentRef(
                "r2-monitoring-fork",
                "v1",
                "c" * 64,
            ),
        ),
    )

    with pytest.raises(R2TrialMonitoringPersistenceCorruption, match="same-rank fork"):
        _select_latest_complete((first, second))
