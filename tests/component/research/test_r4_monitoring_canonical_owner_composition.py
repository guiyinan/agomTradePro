"""Component acceptance for canonical R4 monitoring owner composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.deletion import Collector

from apps.portfolio.application.r4_monitoring_raw_fact_receipt import (
    RegisterPortfolioR4MonitoringRawFactCommand,
)
from apps.portfolio.domain.r4_monitoring_raw_fact_receipt import (
    PortfolioR4MonitoringRawFactSourceReceipt,
    PortfolioR4MonitoringRawMetric,
    R4MonitoringRawFactDefinition,
)
from apps.portfolio.infrastructure.r4_monitoring_raw_fact_models import (
    PortfolioR4MonitoringRawFactReceiptModel,
)
from apps.portfolio.r4_monitoring_raw_fact_composition import (
    _build_django_portfolio_r4_monitoring_raw_fact_registration_runtime,
    _DjangoPortfolioR4MonitoringRawFactRegistrationRuntime,
)
from apps.research.application.r4_promotion_monitoring import (
    EvaluateR4PromotionMonitoringCommand,
)
from apps.research.application.r4_promotion_monitoring_owner_registry import (
    R4MonitoringOwnerRegistryUnavailable,
    RegisterR4MonitoringCalendarCommand,
    RegisterR4MonitoringPolicyCommand,
)
from apps.research.application.r4_promotion_monitoring_persistence import (
    R4MonitoringPersistenceUnavailable,
)
from apps.research.domain.r4_promotion_lifecycle import R4PromotionDecisionIdentity
from apps.research.domain.r4_promotion_monitoring import (
    R4MonitoringObservation,
    R4MonitoringPeriodCalendar,
    R4MonitoringPolicy,
)
from apps.research.domain.r4_promotion_monitoring_owner_registry import (
    R4MonitoringCalendarDefinition,
    R4MonitoringOwnerRecordKind,
    R4MonitoringOwnerSourceReceipt,
    R4MonitoringPolicyDefinition,
)
from apps.research.infrastructure.r4_promotion_monitoring_models import (
    R4MonitoringAssessmentLedgerModel,
    R4MonitoringObservationLedgerModel,
)
from apps.research.infrastructure.r4_promotion_monitoring_owner_models import (
    R4MonitoringCalendarLedgerModel,
    R4MonitoringPolicyLedgerModel,
)
from apps.research.r4_promotion_monitoring_composition import (
    build_django_canonical_r4_monitoring_runtime,
)
from apps.research.r4_promotion_monitoring_owner_composition import (
    _build_django_r4_monitoring_owner_registration_runtime,
    _DjangoR4MonitoringOwnerRegistrationRuntime,
)
from tests.unit.research.r4_promotion_monitoring_factories import (
    monitoring_calendar,
    monitoring_decision,
    monitoring_observation,
    monitoring_policy,
)

pytestmark = pytest.mark.django_db(transaction=True)


@dataclass
class _ExactProvider:
    value: object
    unit_of_work_key: str = "django:default"

    def get_exact(self, **kwargs: object) -> object:
        return self.value


@dataclass(frozen=True)
class _Clock:
    value: datetime
    unit_of_work_key: str = "django:default"

    def now(self) -> datetime:
        return self.value


@dataclass(frozen=True)
class _OwnerInputs:
    policy: R4MonitoringPolicy
    calendar: R4MonitoringPeriodCalendar
    observation: R4MonitoringObservation
    policy_definition: R4MonitoringPolicyDefinition
    calendar_definition: R4MonitoringCalendarDefinition
    raw_definition: R4MonitoringRawFactDefinition
    policy_source: R4MonitoringOwnerSourceReceipt
    calendar_source: R4MonitoringOwnerSourceReceipt
    raw_source: PortfolioR4MonitoringRawFactSourceReceipt


def _raw_definition(observation: R4MonitoringObservation) -> R4MonitoringRawFactDefinition:
    return R4MonitoringRawFactDefinition(
        observation_id=observation.observation_id,
        observation_version=observation.observation_version,
        period_id=observation.period_id,
        calendar_id=observation.period_calendar_id,
        calendar_version=observation.period_calendar_version,
        calendar_hash=observation.period_calendar_hash,
        period_start=observation.period_start,
        period_end=observation.period_end,
        active_decision_id=observation.active_decision.decision_id,
        active_decision_version=observation.active_decision.decision_version,
        active_decision_hash=observation.active_decision.content_hash,
        policy_id=observation.policy_id,
        policy_version=observation.policy_version,
        policy_hash=observation.policy_hash,
        portfolio_record_id=observation.portfolio_record_id,
        portfolio_record_hash=observation.portfolio_record_hash,
        portfolio_record_content_hash=observation.portfolio_record_content_hash,
        r3_attestation_content_hash=observation.r3_attestation_content_hash,
        observed_at=observation.observed_at,
        available_at=observation.available_at,
        valid_until=observation.valid_until,
        pit_manifest_id=observation.pit_manifest_id,
        pit_manifest_hash=observation.pit_manifest_hash,
        evidence_ref=observation.evidence_ref,
        label_protocol_version=observation.label_protocol_version,
        observed_label_set_hash=observation.observed_label_set_hash,
        observed_data_schema_hash=observation.observed_data_schema_hash,
        metrics=tuple(
            PortfolioR4MonitoringRawMetric(
                metric_key=item.metric_key.value,
                unit=item.unit,
                value=item.value,
            )
            for item in observation.metrics
        ),
    )


def _owner_inputs() -> _OwnerInputs:
    decision = monitoring_decision()
    calendar = monitoring_calendar(decision)
    policy = monitoring_policy(decision, calendar)
    observation = monitoring_observation(
        period_index=0,
        decision=decision,
        calendar=calendar,
        policy=policy,
    )
    policy_definition = R4MonitoringPolicyDefinition.from_policy(policy)
    calendar_definition = R4MonitoringCalendarDefinition.from_calendar(calendar)
    raw_definition = _raw_definition(observation)
    return _OwnerInputs(
        policy=policy,
        calendar=calendar,
        observation=observation,
        policy_definition=policy_definition,
        calendar_definition=calendar_definition,
        raw_definition=raw_definition,
        policy_source=R4MonitoringOwnerSourceReceipt.create(
            record_kind=R4MonitoringOwnerRecordKind.POLICY,
            source_owner="research",
            source_receipt_id="policy-source",
            source_receipt_version="source.v1",
            definition_hash=policy_definition.content_hash,
            available_at=policy.recorded_at,
            valid_until=policy.active_until,
        ),
        calendar_source=R4MonitoringOwnerSourceReceipt.create(
            record_kind=R4MonitoringOwnerRecordKind.CALENDAR,
            source_owner="research",
            source_receipt_id="calendar-source",
            source_receipt_version="source.v1",
            definition_hash=calendar_definition.content_hash,
            available_at=policy.recorded_at,
            valid_until=calendar.valid_until,
        ),
        raw_source=PortfolioR4MonitoringRawFactSourceReceipt.create(
            source_receipt_id="raw-source",
            source_receipt_version="source.v1",
            definition_hash=raw_definition.content_hash,
            available_at=observation.available_at,
            valid_until=observation.valid_until,
        ),
    )


def _runtimes(
    inputs: _OwnerInputs,
) -> tuple[
    _DjangoR4MonitoringOwnerRegistrationRuntime,
    _DjangoPortfolioR4MonitoringRawFactRegistrationRuntime,
]:
    return (
        _build_django_r4_monitoring_owner_registration_runtime(
            policy_definition_provider=_ExactProvider(inputs.policy_definition),
            calendar_definition_provider=_ExactProvider(inputs.calendar_definition),
            policy_source_provider=_ExactProvider(inputs.policy_source),
            calendar_source_provider=_ExactProvider(inputs.calendar_source),
            clock=_Clock(inputs.policy.recorded_at),
        ),
        _build_django_portfolio_r4_monitoring_raw_fact_registration_runtime(
            definition_provider=_ExactProvider(inputs.raw_definition),
            source_provider=_ExactProvider(inputs.raw_source),
            clock=_Clock(inputs.observation.recorded_at),
        ),
    )


def _commands(
    inputs: _OwnerInputs,
) -> tuple[
    RegisterR4MonitoringPolicyCommand,
    RegisterR4MonitoringCalendarCommand,
    RegisterPortfolioR4MonitoringRawFactCommand,
]:
    return (
        RegisterR4MonitoringPolicyCommand(
            inputs.policy.policy_id,
            inputs.policy.policy_version,
            inputs.policy_source.source_receipt_id,
            inputs.policy_source.source_receipt_version,
            inputs.policy.recorded_at,
        ),
        RegisterR4MonitoringCalendarCommand(
            inputs.calendar.calendar_id,
            inputs.calendar.calendar_version,
            inputs.calendar_source.source_receipt_id,
            inputs.calendar_source.source_receipt_version,
            inputs.policy.recorded_at,
        ),
        RegisterPortfolioR4MonitoringRawFactCommand(
            inputs.observation.observation_id,
            inputs.observation.observation_version,
            inputs.raw_source.source_receipt_id,
            inputs.raw_source.source_receipt_version,
            inputs.observation.recorded_at,
        ),
    )


def _register_all(inputs: _OwnerInputs) -> tuple[object, object, object]:
    owner_runtime, raw_runtime = _runtimes(inputs)
    policy_command, calendar_command, raw_command = _commands(inputs)
    return (
        owner_runtime.register_policy.execute(policy_command),
        owner_runtime.register_calendar.execute(calendar_command),
        raw_runtime.register.execute(raw_command),
    )


def test_private_runtimes_roundtrip_exact_pit_idempotency_and_winner_fork() -> None:
    inputs = _owner_inputs()
    owner_runtime, raw_runtime = _runtimes(inputs)
    policy_command, calendar_command, raw_command = _commands(inputs)

    policy = owner_runtime.register_policy.execute(policy_command)
    calendar = owner_runtime.register_calendar.execute(calendar_command)
    raw = raw_runtime.register.execute(raw_command)
    assert owner_runtime.register_policy.execute(policy_command) == policy
    assert owner_runtime.register_calendar.execute(calendar_command) == calendar
    assert raw_runtime.register.execute(raw_command) == raw
    assert R4MonitoringPolicyLedgerModel._default_manager.count() == 1
    assert R4MonitoringCalendarLedgerModel._default_manager.count() == 1
    assert PortfolioR4MonitoringRawFactReceiptModel._default_manager.count() == 1

    before_policy = policy.active_from - timedelta(microseconds=1)
    assert (
        owner_runtime.policy_provider.get_exact(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_policy_hash=policy.content_hash,
            active_decision=policy.active_decision,
            as_of=before_policy,
        )
        is None
    )
    assert (
        owner_runtime.policy_provider.get_exact(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_policy_hash=policy.content_hash,
            active_decision=policy.active_decision,
            as_of=policy.active_from,
        )
        == policy
    )
    assert (
        owner_runtime.calendar_provider.get_exact(
            source_owner=calendar.source_owner,
            calendar_id=calendar.calendar_id,
            calendar_version=calendar.calendar_version,
            expected_calendar_hash=calendar.content_hash,
            as_of=calendar.valid_from - timedelta(microseconds=1),
        )
        is None
    )
    assert (
        owner_runtime.calendar_provider.get_exact(
            source_owner=calendar.source_owner,
            calendar_id=calendar.calendar_id,
            calendar_version=calendar.calendar_version,
            expected_calendar_hash=calendar.content_hash,
            as_of=calendar.valid_from,
        )
        == calendar
    )
    exact_raw = {
        "active_decision_id": raw.active_decision_id,
        "active_decision_version": raw.active_decision_version,
        "active_decision_hash": raw.active_decision_hash,
        "policy_id": raw.policy_id,
        "policy_version": raw.policy_version,
        "policy_hash": raw.policy_hash,
        "calendar_id": raw.calendar_id,
        "calendar_version": raw.calendar_version,
        "calendar_hash": raw.calendar_hash,
    }
    assert (
        raw_runtime.repository.list_exact(
            **exact_raw,
            as_of=raw.owner_recorded_at - timedelta(microseconds=1),
        )
        == ()
    )
    assert raw_runtime.repository.list_exact(
        **exact_raw,
        as_of=raw.owner_recorded_at,
    ) == (raw,)

    forked_definition = replace(
        inputs.policy_definition,
        maximum_observation_age_seconds=(
            inputs.policy_definition.maximum_observation_age_seconds + 1
        ),
    )
    forked_source = R4MonitoringOwnerSourceReceipt.create(
        record_kind=R4MonitoringOwnerRecordKind.POLICY,
        source_owner="research",
        source_receipt_id="policy-source-fork",
        source_receipt_version="source.v1",
        definition_hash=forked_definition.content_hash,
        available_at=inputs.policy.recorded_at,
        valid_until=inputs.policy.active_until,
    )
    forked_runtime = _build_django_r4_monitoring_owner_registration_runtime(
        policy_definition_provider=_ExactProvider(forked_definition),
        calendar_definition_provider=_ExactProvider(inputs.calendar_definition),
        policy_source_provider=_ExactProvider(forked_source),
        calendar_source_provider=_ExactProvider(inputs.calendar_source),
        clock=_Clock(inputs.policy.recorded_at),
    )
    with pytest.raises(R4MonitoringOwnerRegistryUnavailable, match="unavailable"):
        forked_runtime.register_policy.execute(
            replace(policy_command, source_receipt_id="policy-source-fork")
        )
    assert R4MonitoringPolicyLedgerModel._default_manager.count() == 1


def test_outer_rollback_and_every_orm_mutation_path_are_guarded() -> None:
    inputs = _owner_inputs()
    with pytest.raises(RuntimeError, match="outer rollback"):
        with transaction.atomic():
            _register_all(inputs)
            raise RuntimeError("outer rollback")
    assert R4MonitoringPolicyLedgerModel._default_manager.count() == 0
    assert R4MonitoringCalendarLedgerModel._default_manager.count() == 0
    assert PortfolioR4MonitoringRawFactReceiptModel._default_manager.count() == 0

    _register_all(inputs)
    model_instances: tuple[tuple[type[models.Model], models.Model], ...] = (
        (
            R4MonitoringPolicyLedgerModel,
            R4MonitoringPolicyLedgerModel._default_manager.get(),
        ),
        (
            R4MonitoringCalendarLedgerModel,
            R4MonitoringCalendarLedgerModel._default_manager.get(),
        ),
        (
            PortfolioR4MonitoringRawFactReceiptModel,
            PortfolioR4MonitoringRawFactReceiptModel._default_manager.get(),
        ),
    )
    for model, instance in model_instances:
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
            lambda model=model: model._default_manager.get_or_create(content_hash="f" * 64),
            lambda model=model: model._default_manager.update_or_create(content_hash="f" * 64),
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

    assert R4MonitoringPolicyLedgerModel._default_manager.count() == 1
    assert R4MonitoringCalendarLedgerModel._default_manager.count() == 1
    assert PortfolioR4MonitoringRawFactReceiptModel._default_manager.count() == 1


def test_public_canonical_runtime_is_inert_and_writes_no_assessment_rows() -> None:
    inputs = _owner_inputs()
    command = EvaluateR4PromotionMonitoringCommand(
        active_decision=R4PromotionDecisionIdentity.from_decision(monitoring_decision()),
        policy_id=inputs.policy.policy_id,
        policy_version=inputs.policy.policy_version,
        expected_policy_hash=inputs.policy.content_hash,
        as_of=inputs.calendar.valid_from + timedelta(hours=2, minutes=30),
    )
    runtime = build_django_canonical_r4_monitoring_runtime()

    with pytest.raises(R4MonitoringPersistenceUnavailable, match="providers are unavailable"):
        runtime.register.execute(command)
    assert R4MonitoringObservationLedgerModel._default_manager.count() == 0
    assert R4MonitoringAssessmentLedgerModel._default_manager.count() == 0
    assert R4MonitoringPolicyLedgerModel._default_manager.count() == 0
    assert R4MonitoringCalendarLedgerModel._default_manager.count() == 0
    assert PortfolioR4MonitoringRawFactReceiptModel._default_manager.count() == 0
