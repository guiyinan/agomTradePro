"""Application orchestration for R7 monitoring uses only authoritative owner reads."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from apps.research.application.r7_post_promotion_monitoring import (
    EvaluateR7PostPromotionMonitoring,
    EvaluateR7PostPromotionMonitoringCommand,
    R7MonitoringActiveOwnerGraph,
    R7MonitoringEvaluationEvidence,
    R7PostPromotionMonitoringPolicy,
    R7PostPromotionMonitoringUnavailable,
)
from tests.unit.research.r7_research_result_factories import make_result
from tests.unit.research.test_r7_post_promotion_monitoring import (
    _active_period_and_fact,
    _lifecycle_owner_evidence,
    _promotion_stream,
)


class _Uow:
    unit_of_work_key = "research:default"

    @contextmanager
    def atomic(self) -> Iterator[None]:
        yield


class _Clock:
    unit_of_work_key = "research:default"

    def __init__(self, now: datetime) -> None:
        self.value = now

    def now(self) -> datetime:
        return self.value


class _Provider:
    unit_of_work_key = "research:default"

    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    def get_exact(self, **_: object) -> object:
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def _graph() -> tuple[
    R7PostPromotionMonitoringPolicy,
    R7MonitoringActiveOwnerGraph,
    object,
    object,
    datetime,
]:
    active, calendar, period, fact = _active_period_and_fact()
    stream = _promotion_stream()
    result = make_result()
    owner_graph = R7MonitoringActiveOwnerGraph(
        result=result,
        lifecycle_stream=stream,
        lifecycle_owner_evidence=_lifecycle_owner_evidence(stream),
    ).validated_copy()
    as_of = max(fact.owner_record.pit_as_of, active.lifecycle_recorded_at) + timedelta(seconds=1)
    policy = R7PostPromotionMonitoringPolicy.create(
        policy_id="r7-monitoring-policy:1",
        result_id=active.result_id,
        result_version=active.result_version,
        result_hash=active.result_hash,
        lifecycle_attestation_id=active.lifecycle_attestation_id,
        lifecycle_attestation_version=active.lifecycle_attestation_version,
        lifecycle_attestation_hash=active.lifecycle_attestation_hash,
        calendar_id=calendar.calendar_id,
        calendar_version=calendar.calendar_version,
        calendar_hash=calendar.content_hash,
        period_id=period.period_id,
        period_version=period.period_version,
        period_hash=period.content_hash,
        maximum_subjective_brier_score=Decimal("0.20"),
        maximum_model_brier_score=Decimal("0.20"),
        minimum_forecast_outcome_coverage=Decimal("1"),
        recorded_at=period.period_start - timedelta(minutes=1),
        valid_until=active.lifecycle_valid_until,
    )
    return policy, owner_graph, calendar, fact.owner_record, as_of


def _use_case(
    *,
    policy: object,
    owner_graph: object,
    calendar: object,
    realization: object,
    now: datetime,
) -> tuple[EvaluateR7PostPromotionMonitoring, tuple[_Provider, ...], _Clock, _Uow]:
    providers = tuple(_Provider(value) for value in (policy, owner_graph, calendar, realization))
    clock = _Clock(now)
    uow = _Uow()
    use_case = EvaluateR7PostPromotionMonitoring(
        policy_provider=providers[0],
        active_owner_graph_provider=providers[1],
        calendar_provider=providers[2],
        realization_provider=providers[3],
        clock=clock,
        unit_of_work=uow,
    )
    return use_case, providers, clock, uow


def _command(
    policy: R7PostPromotionMonitoringPolicy,
    as_of: datetime,
) -> EvaluateR7PostPromotionMonitoringCommand:
    return EvaluateR7PostPromotionMonitoringCommand(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        expected_policy_hash=policy.content_hash,
        as_of=as_of,
    )


def test_application_double_reads_and_replays_complete_owner_graph() -> None:
    policy, owner_graph, calendar, realization, as_of = _graph()
    use_case, providers, _, _ = _use_case(
        policy=policy,
        owner_graph=owner_graph,
        calendar=calendar,
        realization=realization,
        now=as_of + timedelta(seconds=1),
    )

    evidence = use_case.execute_evidence(_command(policy, as_of))

    assert type(evidence) is R7MonitoringEvaluationEvidence
    assert evidence.assessment.result_hash == owner_graph.result.content_hash
    assert evidence.assessment.realization_hash == evidence.realization.content_hash
    assert evidence.assessment.automatic_retirement is False
    assert [provider.calls for provider in providers] == [2, 2, 2, 2]


def test_application_blocks_second_read_substitution() -> None:
    policy, owner_graph, calendar, realization, as_of = _graph()

    class _ReplacingProvider(_Provider):
        def get_exact(self, **_: object) -> object:
            self.calls += 1
            if self.calls == 1:
                return self.value
            return replace(realization, evidence_ref="signal://substituted")

    policy_provider = _Provider(policy)
    owner_provider = _Provider(owner_graph)
    calendar_provider = _Provider(calendar)
    realization_provider = _ReplacingProvider(realization)
    clock = _Clock(as_of + timedelta(seconds=1))
    uow = _Uow()
    use_case = EvaluateR7PostPromotionMonitoring(
        policy_provider=policy_provider,
        active_owner_graph_provider=owner_provider,
        calendar_provider=calendar_provider,
        realization_provider=realization_provider,
        clock=clock,
        unit_of_work=uow,
    )

    with pytest.raises(R7PostPromotionMonitoringUnavailable):
        use_case.execute_evidence(_command(policy, as_of))


@pytest.mark.parametrize("owner_value", [None, RuntimeError("owner failed"), object()])
def test_application_normalizes_missing_throwing_or_malformed_owner(
    owner_value: object,
) -> None:
    policy, owner_graph, calendar, realization, as_of = _graph()
    use_case, _, _, _ = _use_case(
        policy=policy,
        owner_graph=owner_value,
        calendar=calendar,
        realization=realization,
        now=as_of + timedelta(seconds=1),
    )

    with pytest.raises(R7PostPromotionMonitoringUnavailable):
        use_case.execute_evidence(_command(policy, as_of))


def test_application_rejects_future_command_before_owner_reads() -> None:
    policy, owner_graph, calendar, realization, as_of = _graph()
    use_case, providers, _, _ = _use_case(
        policy=policy,
        owner_graph=owner_graph,
        calendar=calendar,
        realization=realization,
        now=as_of - timedelta(seconds=1),
    )

    with pytest.raises(R7PostPromotionMonitoringUnavailable):
        use_case.execute_evidence(_command(policy, as_of))

    assert [provider.calls for provider in providers] == [0, 0, 0, 0]


def test_application_rejects_dynamic_uow_drift() -> None:
    policy, owner_graph, calendar, realization, as_of = _graph()
    use_case, providers, _, _ = _use_case(
        policy=policy,
        owner_graph=owner_graph,
        calendar=calendar,
        realization=realization,
        now=as_of + timedelta(seconds=1),
    )
    providers[2].unit_of_work_key = "research:other"

    with pytest.raises(R7PostPromotionMonitoringUnavailable):
        use_case.execute_evidence(_command(policy, as_of))
