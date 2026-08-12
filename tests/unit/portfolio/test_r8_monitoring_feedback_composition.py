"""Public isolation for Portfolio-owned R8 raw feedback receipts."""

from inspect import signature

import pytest

from apps.portfolio.application.r8_monitoring_feedback_registry import (
    PortfolioR8MonitoringFeedbackRegistryUnavailable,
    RegisterPortfolioR8MonitoringFeedbackCommand,
)
from apps.portfolio.infrastructure.r8_portfolio_monitoring_feedback_adapter import (
    _build_period_observations,
    _to_monitoring_source_evidence,
)
from apps.portfolio.r8_monitoring_feedback_composition import (
    DjangoPortfolioR8MonitoringFeedbackRuntime,
    build_django_portfolio_r8_monitoring_feedback_runtime,
)
from tests.unit.portfolio.test_governed_optimization_monitoring import (
    _calendar,
    _facts,
    _receipt_and_result,
)
from tests.unit.portfolio.test_r8_monitoring_feedback_registry import _command, _feedback


def _walk_graph(root: object) -> tuple[object, ...]:
    pending = [root]
    visited: set[int] = set()
    values: list[object] = []
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        values.append(current)
        state = getattr(current, "__dict__", None)
        if isinstance(state, dict):
            pending.extend(state.values())
        for owner in type(current).__mro__:
            slots = owner.__dict__.get("__slots__", ())
            if isinstance(slots, str):
                slots = (slots,)
            for slot in slots:
                if slot in {"__dict__", "__weakref__"}:
                    continue
                try:
                    pending.append(object.__getattribute__(current, slot))
                except AttributeError:
                    continue
    return tuple(values)


def test_public_feedback_registry_is_using_only_readable_and_mutation_inert() -> None:
    """Production composition retains exact reads but no raw-fact append authority."""

    assert tuple(signature(build_django_portfolio_r8_monitoring_feedback_runtime).parameters) == (
        "using",
    )
    runtime = build_django_portfolio_r8_monitoring_feedback_runtime()
    assert isinstance(runtime, DjangoPortfolioR8MonitoringFeedbackRuntime)
    assert type(runtime.register).__slots__ == ()
    graph = _walk_graph(runtime)
    assert not any(
        any(hasattr(item, name) for name in ("_store", "_clock", "_token", "_uow"))
        for item in graph
    )

    with pytest.raises(
        PortfolioR8MonitoringFeedbackRegistryUnavailable,
        match="unavailable",
    ):
        runtime.register.execute(_command())

    command = _command()
    object.__setattr__(command, "feedback_id", "")
    object.__setattr__(command, "__post_init__", lambda: None)
    with pytest.raises(
        PortfolioR8MonitoringFeedbackRegistryUnavailable,
        match="malformed",
    ):
        runtime.register.execute(command)


def test_public_feedback_registry_rejects_command_subclasses() -> None:
    """Subclass validators cannot cross the public registration boundary."""

    class _CommandSubclass(RegisterPortfolioR8MonitoringFeedbackCommand):
        pass

    value = _command()
    command = _CommandSubclass(value.feedback_id, value.feedback_version)
    runtime = build_django_portfolio_r8_monitoring_feedback_runtime()
    with pytest.raises(
        PortfolioR8MonitoringFeedbackRegistryUnavailable,
        match="malformed",
    ):
        runtime.register.execute(command)


def test_portfolio_feedback_adapter_derives_eight_and_combines_exact_eleven() -> None:
    """The narrow adapter derives ratios from raw facts and joins Broker evidence."""

    portfolio = _to_monitoring_source_evidence(_feedback())
    assert len(portfolio.metric_payload) == 8
    receipt, result = _receipt_and_result()
    calendar = _calendar()
    _, broker, _ = _facts(calendar=calendar, receipt=receipt, result=result)
    period_id = calendar.periods[0].period_id
    observations = _build_period_observations(
        portfolio=(portfolio,),
        broker=(broker[0],),
        period_ids=(period_id,),
    )
    assert len(observations) == 1
    assert len(observations[0].metrics) == 11
    assert (
        _build_period_observations(
            portfolio=(portfolio,),
            broker=(),
            period_ids=(period_id,),
        )
        == ()
    )
