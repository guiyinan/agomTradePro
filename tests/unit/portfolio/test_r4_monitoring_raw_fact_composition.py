"""Composition tests for Portfolio-owned R4 monitoring raw-fact receipts."""

from __future__ import annotations

from datetime import datetime

import pytest

from apps.portfolio.application.r4_monitoring_raw_fact_receipt import (
    PortfolioR4MonitoringRawFactUnavailable,
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
    build_django_portfolio_r4_monitoring_raw_fact_runtime,
)
from tests.unit.research.r4_promotion_monitoring_factories import monitoring_observation


class _ExactProvider:
    unit_of_work_key = "django:default"

    def __init__(self, value: object) -> None:
        self.value = value

    def get_exact(self, **kwargs: object) -> object:
        return self.value


class _Clock:
    unit_of_work_key = "django:default"

    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def _definition() -> R4MonitoringRawFactDefinition:
    original = monitoring_observation(period_index=0)
    return R4MonitoringRawFactDefinition(
        observation_id=original.observation_id,
        observation_version=original.observation_version,
        period_id=original.period_id,
        calendar_id=original.period_calendar_id,
        calendar_version=original.period_calendar_version,
        calendar_hash=original.period_calendar_hash,
        period_start=original.period_start,
        period_end=original.period_end,
        active_decision_id=original.active_decision.decision_id,
        active_decision_version=original.active_decision.decision_version,
        active_decision_hash=original.active_decision.content_hash,
        policy_id=original.policy_id,
        policy_version=original.policy_version,
        policy_hash=original.policy_hash,
        portfolio_record_id=original.portfolio_record_id,
        portfolio_record_hash=original.portfolio_record_hash,
        portfolio_record_content_hash=original.portfolio_record_content_hash,
        r3_attestation_content_hash=original.r3_attestation_content_hash,
        observed_at=original.observed_at,
        available_at=original.available_at,
        valid_until=original.valid_until,
        pit_manifest_id=original.pit_manifest_id,
        pit_manifest_hash=original.pit_manifest_hash,
        evidence_ref=original.evidence_ref,
        label_protocol_version=original.label_protocol_version,
        observed_label_set_hash=original.observed_label_set_hash,
        observed_data_schema_hash=original.observed_data_schema_hash,
        metrics=tuple(
            PortfolioR4MonitoringRawMetric(item.metric_key.value, item.unit, item.value)
            for item in original.metrics
        ),
    )


@pytest.mark.django_db
def test_public_raw_fact_registration_is_inert_and_zero_write() -> None:
    runtime = build_django_portfolio_r4_monitoring_raw_fact_runtime()
    original = monitoring_observation(period_index=0)

    with pytest.raises(PortfolioR4MonitoringRawFactUnavailable, match="source provider"):
        runtime.register.execute(
            RegisterPortfolioR4MonitoringRawFactCommand(
                original.observation_id,
                original.observation_version,
                "raw-source",
                "source.v1",
                original.recorded_at,
            )
        )

    assert PortfolioR4MonitoringRawFactReceiptModel._default_manager.count() == 0
    assert not hasattr(runtime.repository, "append")
    assert not hasattr(runtime.repository, "_token")


@pytest.mark.django_db
def test_private_test_composition_builds_and_restores_raw_receipt() -> None:
    definition = _definition()
    original = monitoring_observation(period_index=0)
    source = PortfolioR4MonitoringRawFactSourceReceipt.create(
        source_receipt_id="raw-source",
        source_receipt_version="source.v1",
        definition_hash=definition.content_hash,
        available_at=original.available_at,
        valid_until=original.valid_until,
    )
    runtime = _build_django_portfolio_r4_monitoring_raw_fact_registration_runtime(
        definition_provider=_ExactProvider(definition),
        source_provider=_ExactProvider(source),
        clock=_Clock(original.recorded_at),
    )

    stored = runtime.register.execute(
        RegisterPortfolioR4MonitoringRawFactCommand(
            original.observation_id,
            original.observation_version,
            "raw-source",
            "source.v1",
            original.recorded_at,
        )
    )
    restored = runtime.repository.list_exact(
        active_decision_id=definition.active_decision_id,
        active_decision_version=definition.active_decision_version,
        active_decision_hash=definition.active_decision_hash,
        policy_id=definition.policy_id,
        policy_version=definition.policy_version,
        policy_hash=definition.policy_hash,
        calendar_id=definition.calendar_id,
        calendar_version=definition.calendar_version,
        calendar_hash=definition.calendar_hash,
        as_of=original.recorded_at,
    )

    assert restored == (stored,)
