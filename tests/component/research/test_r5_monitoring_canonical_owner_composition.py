"""Component acceptance for canonical R5 monitoring owner composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from inspect import signature

import pytest
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.deletion import Collector

from apps.fixed_income.application.relative_value_projection import (
    GetExactR5RelativeValueOwnerRecordCommand,
)
from apps.fixed_income.relative_value_composition import (
    build_django_r5_relative_value_owner_record_query,
)
from apps.portfolio.application.r5_monitoring_raw_fact_registry import (
    PortfolioR5MonitoringRawFactUnavailable,
    RegisterPortfolioR5MonitoringRawFactCommand,
)
from apps.portfolio.domain.r5_monitoring_raw_fact_registry import (
    PortfolioR5MonitoringRawFactDefinition,
    PortfolioR5MonitoringRawFactSourceReceipt,
)
from apps.portfolio.infrastructure.r5_monitoring_raw_fact_models import (
    PortfolioR5MonitoringRawFactReceiptModel,
)
from apps.portfolio.r5_monitoring_raw_fact_composition import (
    _build_django_portfolio_r5_monitoring_raw_fact_registration_runtime,
    build_django_portfolio_r5_monitoring_raw_fact_runtime,
)
from apps.research.application import (
    r5_relative_value_promotion_decision as promotion_decision_application,
)
from apps.research.application.r5_monitoring_owner_registry import (
    RegisterR5MonitoringCalendarCommand,
    RegisterR5MonitoringPolicyCommand,
)
from apps.research.application.r5_relative_value_monitoring import (
    EvaluateR5PostPromotionMonitoringCommand,
)
from apps.research.application.r5_relative_value_monitoring_persistence import (
    R5MonitoringPersistenceUnavailable,
)
from apps.research.application.r5_research_control_preflight import (
    EvaluateR5ResearchControlPreflightCommand,
    R5ResearchControlPreflightStatus,
)
from apps.research.domain import r5_relative_value_promotion_decision as promotion_decision_domain
from apps.research.domain.r5_monitoring_owner_registry import (
    R5MonitoringCalendarDefinition,
    R5MonitoringOwnerRecordKind,
    R5MonitoringOwnerSourceReceipt,
    R5MonitoringPolicyDefinition,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringActiveLifecycle,
)
from apps.research.domain.r5_relative_value_promotion_policy import (
    R5RelativeValuePromotionPolicy,
)
from apps.research.domain.r5_relative_value_promotion_trial import (
    R5RelativeValuePromotionTrial,
)
from apps.research.infrastructure.r5_monitoring_owner_models import (
    R5MonitoringCalendarRegistryModel,
    R5MonitoringPolicyRegistryModel,
)
from apps.research.infrastructure.r5_relative_value_monitoring_models import (
    R5MonitoringAssessmentLedgerModel,
    R5MonitoringObservationLedgerModel,
)
from apps.research.r5_monitoring_owner_composition import (
    _build_django_r5_monitoring_owner_registration_runtime,
    build_django_r5_monitoring_owner_registry_runtime,
)
from apps.research.r5_relative_value_monitoring_composition import (
    _build_django_canonical_r5_monitoring_test_runtime,
    build_django_canonical_r5_monitoring_runtime,
)
from tests.component.fixed_income.test_relative_value_persistence_repository import (
    _persist_command as _fixed_income_persist_command,
)
from tests.component.fixed_income.test_relative_value_persistence_repository import (
    _runtime as _fixed_income_runtime,
)
from tests.component.research import (
    test_r5_relative_value_promotion_repository as promotion_repository_tests,
)
from tests.component.research.test_r5_relative_value_monitoring_repository import (
    _evidence,
)
from tests.unit.fixed_income.test_relative_value_use_case import (
    _EVALUATED_AT,
    _fixture_graph,
)

pytestmark = pytest.mark.django_db(transaction=True)


@dataclass
class _ExactProvider:
    value: object
    unit_of_work_key: str = "django:default"

    def get_exact(self, **kwargs: object) -> object:
        del kwargs
        return self.value


@dataclass(frozen=True)
class _Clock:
    value: datetime
    unit_of_work_key: str = "django:default"

    def now(self) -> datetime:
        return self.value


@dataclass(frozen=True)
class _ActiveProvider:
    value: R5MonitoringActiveLifecycle
    unit_of_work_key: str = "django:default"

    def get_active(
        self,
        *,
        scope_id: str,
        as_of: datetime,
    ) -> R5MonitoringActiveLifecycle | None:
        if (
            self.value.scope_id != scope_id
            or not self.value.recorded_at <= as_of < self.value.valid_until
        ):
            return None
        return self.value.validated_copy()


@dataclass(frozen=True)
class _OwnerInputs:
    policy_definition: R5MonitoringPolicyDefinition
    calendar_definition: R5MonitoringCalendarDefinition
    policy_source: R5MonitoringOwnerSourceReceipt
    calendar_source: R5MonitoringOwnerSourceReceipt
    raw_definitions: tuple[PortfolioR5MonitoringRawFactDefinition, ...]
    raw_sources: tuple[PortfolioR5MonitoringRawFactSourceReceipt, ...]
    command: EvaluateR5PostPromotionMonitoringCommand


def _inputs(monkeypatch: pytest.MonkeyPatch) -> tuple[object, _OwnerInputs]:
    def extended_valid_until(
        *,
        policy: R5RelativeValuePromotionPolicy,
        trial: R5RelativeValuePromotionTrial,
        decided_at: datetime,
    ) -> datetime:
        del policy, decided_at
        return trial.valid_until

    for module in (
        promotion_repository_tests,
        promotion_decision_application,
        promotion_decision_domain,
    ):
        monkeypatch.setattr(
            module,
            "r5_relative_value_promotion_decision_valid_until",
            extended_valid_until,
        )
    fixed_income_graph = _fixture_graph(monkeypatch)
    fixed_income_runtime = _fixed_income_runtime(fixed_income_graph)
    fixed_income_runtime.runtime.persist.execute(
        _fixed_income_persist_command(
            fixed_income_graph,
            assessment_id="r5-assessment-a",
        )
    )
    fixed_income_runtime.clock.value = _EVALUATED_AT + timedelta(minutes=2)
    fixed_income_runtime.runtime.persist.execute(
        _fixed_income_persist_command(
            fixed_income_graph,
            assessment_id="r5-assessment-b",
        )
    )
    evidence, command = _evidence(monkeypatch)
    assert evidence.policy is not None
    assert evidence.calendar is not None
    policy_definition = R5MonitoringPolicyDefinition.from_policy(evidence.policy)
    calendar_definition = R5MonitoringCalendarDefinition.from_calendar(evidence.calendar)
    raw_definitions = tuple(
        PortfolioR5MonitoringRawFactDefinition.from_fact(item) for item in evidence.portfolio_facts
    )
    return evidence, _OwnerInputs(
        policy_definition=policy_definition,
        calendar_definition=calendar_definition,
        policy_source=R5MonitoringOwnerSourceReceipt.create(
            record_kind=R5MonitoringOwnerRecordKind.POLICY,
            source_owner="research",
            source_receipt_id="r5-policy-source",
            source_receipt_version="v1",
            owner_id=evidence.policy.policy_id,
            owner_version=evidence.policy.policy_version,
            definition_hash=policy_definition.content_hash,
            available_at=evidence.policy.recorded_at,
            valid_until=evidence.policy.valid_until,
        ),
        calendar_source=R5MonitoringOwnerSourceReceipt.create(
            record_kind=R5MonitoringOwnerRecordKind.CALENDAR,
            source_owner="research",
            source_receipt_id="r5-calendar-source",
            source_receipt_version="v1",
            owner_id=evidence.calendar.owner.owner_id,
            owner_version=evidence.calendar.owner.owner_version,
            definition_hash=calendar_definition.content_hash,
            available_at=evidence.calendar.recorded_at,
            valid_until=evidence.calendar.valid_until,
        ),
        raw_definitions=raw_definitions,
        raw_sources=tuple(
            PortfolioR5MonitoringRawFactSourceReceipt.create(
                source_owner="portfolio",
                source_receipt_id=f"r5-raw-source-{index}",
                source_receipt_version="v1",
                fact_id=definition.fact.fact_id,
                fact_version=definition.fact.fact_version,
                definition_hash=definition.content_hash,
                available_at=definition.fact.recorded_at,
                valid_until=definition.fact.valid_until,
            )
            for index, definition in enumerate(raw_definitions)
        ),
        command=command,
    )


def _owner_runtime(inputs: _OwnerInputs) -> object:
    return _build_django_r5_monitoring_owner_registration_runtime(
        policy_definition_provider=_ExactProvider(inputs.policy_definition),
        calendar_definition_provider=_ExactProvider(inputs.calendar_definition),
        policy_source_provider=_ExactProvider(inputs.policy_source),
        calendar_source_provider=_ExactProvider(inputs.calendar_source),
        clock=_Clock(inputs.command.as_of),
    )


def _raw_runtime(inputs: _OwnerInputs) -> object:
    definitions = {item.fact.fact_id: item for item in inputs.raw_definitions}
    sources = {item.fact_id: item for item in inputs.raw_sources}

    class _Definitions:
        unit_of_work_key = "django:default"

        def get_exact(self, *, fact_id: str, **kwargs: object) -> object:
            del kwargs
            return definitions.get(fact_id)

    class _Sources:
        unit_of_work_key = "django:default"

        def get_exact(self, *, fact_id: str, **kwargs: object) -> object:
            del kwargs
            return sources.get(fact_id)

    return _build_django_portfolio_r5_monitoring_raw_fact_registration_runtime(
        definition_provider=_Definitions(),
        source_provider=_Sources(),
        clock=_Clock(inputs.command.as_of),
    )


def _register_all(inputs: _OwnerInputs) -> tuple[object, object, tuple[object, ...]]:
    owner_runtime = _owner_runtime(inputs)
    raw_runtime = _raw_runtime(inputs)
    policy = owner_runtime.register_policy.execute(
        RegisterR5MonitoringPolicyCommand(
            inputs.policy_definition.policy.policy_id,
            inputs.policy_definition.policy.policy_version,
        )
    )
    calendar = owner_runtime.register_calendar.execute(
        RegisterR5MonitoringCalendarCommand(
            inputs.calendar_definition.calendar.owner.owner_id,
            inputs.calendar_definition.calendar.owner.owner_version,
        )
    )
    facts = tuple(
        raw_runtime.register.execute(
            RegisterPortfolioR5MonitoringRawFactCommand(
                item.fact.fact_id,
                item.fact.fact_version,
            )
        )
        for item in inputs.raw_definitions
    )
    return policy, calendar, facts


def test_private_owner_runtimes_roundtrip_exact_pit_idempotency_and_fork(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, inputs = _inputs(monkeypatch)
    owner_runtime = _owner_runtime(inputs)
    raw_runtime = _raw_runtime(inputs)
    policy_command = RegisterR5MonitoringPolicyCommand(
        inputs.policy_definition.policy.policy_id,
        inputs.policy_definition.policy.policy_version,
    )
    calendar_command = RegisterR5MonitoringCalendarCommand(
        inputs.calendar_definition.calendar.owner.owner_id,
        inputs.calendar_definition.calendar.owner.owner_version,
    )
    policy = owner_runtime.register_policy.execute(policy_command)
    calendar = owner_runtime.register_calendar.execute(calendar_command)
    facts = tuple(
        raw_runtime.register.execute(
            RegisterPortfolioR5MonitoringRawFactCommand(
                item.fact.fact_id,
                item.fact.fact_version,
            )
        )
        for item in inputs.raw_definitions
    )
    assert owner_runtime.register_policy.execute(policy_command) == policy
    assert owner_runtime.register_calendar.execute(calendar_command) == calendar
    assert R5MonitoringPolicyRegistryModel._default_manager.count() == 1
    assert R5MonitoringCalendarRegistryModel._default_manager.count() == 1
    assert PortfolioR5MonitoringRawFactReceiptModel._default_manager.count() == len(facts)

    before = inputs.command.as_of - timedelta(microseconds=1)
    assert (
        owner_runtime.policy_provider.get_exact(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_policy_hash=policy.content_hash,
            as_of=before,
        )
        is None
    )
    assert (
        owner_runtime.policy_provider.get_exact(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_policy_hash=policy.content_hash,
            as_of=inputs.command.as_of,
        )
        == policy
    )
    assert (
        raw_runtime.repository.list_exact(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_policy_hash=policy.content_hash,
            target_hash=policy.target.content_hash,
            calendar_id=calendar.owner.owner_id,
            calendar_version=calendar.owner.owner_version,
            expected_calendar_hash=calendar.content_hash,
            period_ids=tuple(item.period_id for item in calendar.entries),
            as_of=before,
        )
        == ()
    )
    assert (
        raw_runtime.repository.list_exact(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_policy_hash=policy.content_hash,
            target_hash=policy.target.content_hash,
            calendar_id=calendar.owner.owner_id,
            calendar_version=calendar.owner.owner_version,
            expected_calendar_hash=calendar.content_hash,
            period_ids=tuple(item.period_id for item in calendar.entries),
            as_of=inputs.command.as_of,
        )
        == facts
    )

    forked_source = PortfolioR5MonitoringRawFactSourceReceipt.create(
        source_owner="portfolio",
        source_receipt_id="r5-raw-source-fork",
        source_receipt_version="v1",
        fact_id=inputs.raw_definitions[0].fact.fact_id,
        fact_version=inputs.raw_definitions[0].fact.fact_version,
        definition_hash=inputs.raw_definitions[0].content_hash,
        available_at=inputs.raw_definitions[0].fact.recorded_at,
        valid_until=inputs.raw_definitions[0].fact.valid_until,
    )
    forked_runtime = _build_django_portfolio_r5_monitoring_raw_fact_registration_runtime(
        definition_provider=_ExactProvider(inputs.raw_definitions[0]),
        source_provider=_ExactProvider(forked_source),
        clock=_Clock(inputs.command.as_of),
    )
    with pytest.raises(PortfolioR5MonitoringRawFactUnavailable, match="unavailable"):
        forked_runtime.register.execute(
            RegisterPortfolioR5MonitoringRawFactCommand(
                inputs.raw_definitions[0].fact.fact_id,
                inputs.raw_definitions[0].fact.fact_version,
            )
        )
    assert PortfolioR5MonitoringRawFactReceiptModel._default_manager.count() == len(facts)


def test_outer_rollback_and_all_orm_mutation_paths_are_guarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, inputs = _inputs(monkeypatch)
    with pytest.raises(RuntimeError, match="outer rollback"):
        with transaction.atomic():
            _register_all(inputs)
            raise RuntimeError("outer rollback")
    assert R5MonitoringPolicyRegistryModel._default_manager.count() == 0
    assert R5MonitoringCalendarRegistryModel._default_manager.count() == 0
    assert PortfolioR5MonitoringRawFactReceiptModel._default_manager.count() == 0

    _register_all(inputs)
    model_instances: tuple[tuple[type[models.Model], models.Model], ...] = (
        (
            R5MonitoringPolicyRegistryModel,
            R5MonitoringPolicyRegistryModel._default_manager.get(),
        ),
        (
            R5MonitoringCalendarRegistryModel,
            R5MonitoringCalendarRegistryModel._default_manager.get(),
        ),
        (
            PortfolioR5MonitoringRawFactReceiptModel,
            PortfolioR5MonitoringRawFactReceiptModel._default_manager.first(),
        ),
    )
    for model, instance in model_instances:
        assert instance is not None
        assert tuple(model._meta.related_objects) == ()
        queryset = model._default_manager.all()
        forbidden: tuple[Callable[[], object], ...] = (
            lambda model=model: model._default_manager.create(),
            lambda model=model: model._base_manager.create(),
            lambda instance=instance: instance.save(),
            lambda instance=instance: instance.save_base(),
            lambda instance=instance: instance.save_base(raw=True),
            lambda instance=instance: instance.delete(),
            lambda queryset=queryset: queryset.update(ledger_header_hash="f" * 64),
            lambda queryset=queryset: queryset.delete(),
            lambda model=model: model._default_manager.bulk_create([]),
            lambda model=model, instance=instance: model._default_manager.bulk_update(
                [instance], ["ledger_header_hash"]
            ),
            lambda model=model: model._default_manager.get_or_create(ledger_header_hash="f" * 64),
            lambda model=model: model._default_manager.update_or_create(
                ledger_header_hash="f" * 64
            ),
            lambda queryset=queryset: queryset._update([]),
            lambda queryset=queryset: queryset._raw_delete("default"),
            lambda queryset=queryset, instance=instance: queryset._insert([instance], []),
            lambda queryset=queryset, instance=instance: queryset._batched_insert(
                [instance], [], None
            ),
        )
        for operation in forbidden:
            with pytest.raises(ValidationError):
                operation()
        collector = Collector(using="default")
        collector.collect([instance])
        with pytest.raises(ValidationError):
            collector.delete()


def test_private_phase_a_b_and_preflight_succeed_from_registered_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, inputs = _inputs(monkeypatch)
    assert evidence.active_lifecycle is not None
    _register_all(inputs)
    ledger_clock = _Clock(inputs.command.as_of + timedelta(minutes=1))
    fixed_income_query = build_django_r5_relative_value_owner_record_query()
    fixed_income = inputs.policy_definition.policy.target.fixed_income
    record = fixed_income_query.execute(
        GetExactR5RelativeValueOwnerRecordCommand(
            result_id=fixed_income.result_id,
            result_version=fixed_income.result_version,
            expected_record_hash=fixed_income.result_hash,
            as_of=inputs.command.as_of,
        )
    )
    assert record is not None, fixed_income
    assert record.owner_record_key == fixed_income.owner_seal_id
    assert record.content_hash == fixed_income.owner_seal_hash
    runtime = _build_django_canonical_r5_monitoring_test_runtime(
        active_lifecycle_provider=_ActiveProvider(evidence.active_lifecycle),
        fixed_income_query=fixed_income_query,
        clock=ledger_clock,
    )

    persisted = runtime.register.execute(inputs.command)
    result = runtime.preflight.execute(
        EvaluateR5ResearchControlPreflightCommand(
            scope_id=evidence.active_lifecycle.scope_id,
            as_of=persisted.ledger_recorded_at,
        )
    )

    assert persisted.policy == inputs.policy_definition.policy
    assert persisted.portfolio_facts == tuple(item.fact for item in inputs.raw_definitions)
    assert result.status is R5ResearchControlPreflightStatus.ELIGIBLE_FOR_MANUAL_CONSUMER_REVIEW
    assert result.must_not_publish_current
    assert result.must_not_use_for_decision
    assert result.must_not_execute


def test_public_compositions_are_using_only_inert_and_zero_monitoring_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, inputs = _inputs(monkeypatch)
    assert tuple(signature(build_django_canonical_r5_monitoring_runtime).parameters) == ("using",)
    assert tuple(signature(build_django_r5_monitoring_owner_registry_runtime).parameters) == (
        "using",
    )
    assert tuple(signature(build_django_portfolio_r5_monitoring_raw_fact_runtime).parameters) == (
        "using",
    )
    runtime = build_django_canonical_r5_monitoring_runtime()

    with pytest.raises(R5MonitoringPersistenceUnavailable, match="providers are unavailable"):
        runtime.register.execute(inputs.command)
    assert R5MonitoringAssessmentLedgerModel._default_manager.count() == 0
    assert R5MonitoringObservationLedgerModel._default_manager.count() == 0
    assert R5MonitoringPolicyRegistryModel._default_manager.count() == 0
    assert R5MonitoringCalendarRegistryModel._default_manager.count() == 0
    assert PortfolioR5MonitoringRawFactReceiptModel._default_manager.count() == 0
    assert not hasattr(runtime, "writer")
    assert not hasattr(runtime.register, "_store")
