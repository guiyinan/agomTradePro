"""Application-boundary tests for R5 post-promotion monitoring."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import fields
from datetime import datetime, timedelta

import pytest

from apps.research.application.r5_relative_value_monitoring import (
    EvaluateR5PostPromotionMonitoring,
    EvaluateR5PostPromotionMonitoringCommand,
    R5PostPromotionMonitoringUnavailable,
)
from apps.research.domain.r5_relative_value_monitoring import (
    R5MonitoringAssessmentStatus,
)
from tests.unit.research.test_r5_relative_value_monitoring import (
    BASE,
    _active,
    _calendar,
    _facts,
    _fixed_income,
    _policy,
)


class _Provider:
    def __init__(self, value: object, key: object = "research:r5-monitoring") -> None:
        self.value = value
        self.key = key
        self.calls = 0

    @property
    def unit_of_work_key(self) -> object:
        return self.key

    def get_exact(self, **kwargs: object) -> object:
        del kwargs
        self.calls += 1
        return self.value

    def list_exact(self, **kwargs: object) -> object:
        del kwargs
        self.calls += 1
        return self.value


class _UnitOfWork:
    def __init__(self, key: object = "research:r5-monitoring") -> None:
        self.key = key
        self.atomic_calls = 0

    @property
    def unit_of_work_key(self) -> object:
        return self.key

    def atomic(self):  # type: ignore[no-untyped-def]
        self.atomic_calls += 1
        return nullcontext()


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def _application() -> tuple[
    EvaluateR5PostPromotionMonitoring,
    EvaluateR5PostPromotionMonitoringCommand,
    tuple[_Provider, ...],
    _UnitOfWork,
]:
    calendar = _calendar()
    policy = _policy(calendar)
    providers = (
        _Provider(policy),
        _Provider(_active()),
        _Provider(calendar),
        _Provider(_fixed_income()),
        _Provider(_facts(policy)),
    )
    unit_of_work = _UnitOfWork()
    use_case = EvaluateR5PostPromotionMonitoring(
        policy_provider=providers[0],
        active_lifecycle_provider=providers[1],
        calendar_provider=providers[2],
        fixed_income_provider=providers[3],
        portfolio_fact_provider=providers[4],
        unit_of_work=unit_of_work,
        clock=_Clock(BASE + timedelta(days=3, hours=2)),
    )
    command = EvaluateR5PostPromotionMonitoringCommand(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        expected_policy_hash=policy.content_hash,
        as_of=BASE + timedelta(days=3, hours=1),
    )
    return use_case, command, providers, unit_of_work


def test_command_is_identity_only_and_owner_graph_is_read_twice() -> None:
    use_case, command, providers, unit_of_work = _application()

    assert tuple(item.name for item in fields(command)) == (
        "policy_id",
        "policy_version",
        "expected_policy_hash",
        "as_of",
    )
    assessment = use_case.execute(command)

    assert assessment.status is R5MonitoringAssessmentStatus.HEALTHY
    assert tuple(item.calls for item in providers) == (2, 2, 2, 2, 2)
    assert unit_of_work.atomic_calls == 1
    assert not hasattr(use_case, "writer")
    assert not hasattr(use_case, "repository")


def test_malformed_command_and_future_cutoff_are_stably_unavailable() -> None:
    use_case, command, providers, _ = _application()
    object.__setattr__(command, "expected_policy_hash", None)
    with pytest.raises(R5PostPromotionMonitoringUnavailable, match="command"):
        use_case.execute(command)
    assert tuple(item.calls for item in providers) == (0, 0, 0, 0, 0)

    future_use_case, future_command, _, _ = _application()
    future_use_case._clock = _Clock(future_command.as_of - timedelta(seconds=1))
    with pytest.raises(R5PostPromotionMonitoringUnavailable, match="future"):
        future_use_case.execute(future_command)


def test_provider_exception_owner_drift_and_uow_drift_are_normalized() -> None:
    use_case, command, providers, _ = _application()

    class _FailingProvider(_Provider):
        def get_exact(self, **kwargs: object) -> object:
            del kwargs
            raise AttributeError("owner unavailable")

    use_case._calendar_provider = _FailingProvider(providers[2].value)
    with pytest.raises(R5PostPromotionMonitoringUnavailable, match="owner graph"):
        use_case.execute(command)

    drift_use_case, drift_command, drift_providers, _ = _application()

    class _DriftingFacts(_Provider):
        def list_exact(self, **kwargs: object) -> object:
            value = super().list_exact(**kwargs)
            assert isinstance(value, tuple)
            return value if self.calls == 1 else value[:-1]

    drift_use_case._portfolio_fact_provider = _DriftingFacts(drift_providers[4].value)
    with pytest.raises(R5PostPromotionMonitoringUnavailable, match="changed"):
        drift_use_case.execute(drift_command)

    uow_use_case, uow_command, uow_providers, _ = _application()
    uow_providers[0].key = "research:r5-monitoring:drift"
    with pytest.raises(R5PostPromotionMonitoringUnavailable, match="UoW"):
        uow_use_case.execute(uow_command)


def test_uow_key_requires_an_exact_builtin_string() -> None:
    class _WideString(str):
        pass

    calendar = _calendar()
    policy = _policy(calendar)
    invalid = _WideString("research:r5-monitoring")
    with pytest.raises(R5PostPromotionMonitoringUnavailable, match="UoW"):
        EvaluateR5PostPromotionMonitoring(
            policy_provider=_Provider(policy, invalid),
            active_lifecycle_provider=_Provider(_active(), invalid),
            calendar_provider=_Provider(calendar, invalid),
            fixed_income_provider=_Provider(_fixed_income(), invalid),
            portfolio_fact_provider=_Provider(_facts(policy), invalid),
            unit_of_work=_UnitOfWork(invalid),
            clock=_Clock(BASE + timedelta(days=4)),
        )
