"""TDD contracts for Portfolio-owned R4 raw-fact receipts."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import fields
from datetime import datetime

import pytest

from apps.portfolio.application.r4_monitoring_raw_fact_receipt import (
    PortfolioR4MonitoringRawFactUnavailable,
    RegisterPortfolioR4MonitoringRawFact,
    RegisterPortfolioR4MonitoringRawFactCommand,
)
from apps.portfolio.domain.r4_monitoring_raw_fact_receipt import (
    PortfolioR4MonitoringRawFactSourceReceipt,
    PortfolioR4MonitoringRawMetric,
    R4MonitoringRawFactDefinition,
)
from tests.unit.research.r4_promotion_monitoring_factories import (
    monitoring_observation,
)


class _Provider:
    unit_of_work_key = "django:default"

    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    def get_exact(self, **kwargs: object) -> object:
        self.calls += 1
        return self.value


class _Store:
    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.value = None

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def append(self, receipt: object, **lineage: object) -> object:
        self.value = receipt
        return receipt


class _Clock:
    unit_of_work_key = "django:default"

    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class _ThrowingClock(_Clock):
    def now(self) -> datetime:
        raise RuntimeError("clock unavailable")


def test_raw_fact_registration_is_id_only_and_double_read() -> None:
    assert {item.name for item in fields(RegisterPortfolioR4MonitoringRawFactCommand)} == {
        "observation_id",
        "observation_version",
        "source_receipt_id",
        "source_receipt_version",
        "as_of",
    }
    original = monitoring_observation(period_index=0)
    definition = R4MonitoringRawFactDefinition(
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
            PortfolioR4MonitoringRawMetric(
                metric_key=item.metric_key.value,
                unit=item.unit,
                value=item.value,
            )
            for item in original.metrics
        ),
    )
    definition_provider = _Provider(definition)
    source_provider = _Provider(
        PortfolioR4MonitoringRawFactSourceReceipt.create(
            source_receipt_id="portfolio-r4-fact-receipt",
            source_receipt_version="receipt.v1",
            definition_hash=definition.content_hash,
            available_at=original.available_at,
            valid_until=original.valid_until,
        )
    )
    store = _Store()
    service = RegisterPortfolioR4MonitoringRawFact(
        definition_provider=definition_provider,
        source_provider=source_provider,
        store=store,
        clock=_Clock(original.recorded_at),
    )

    result = service.execute(
        RegisterPortfolioR4MonitoringRawFactCommand(
            observation_id=original.observation_id,
            observation_version=original.observation_version,
            source_receipt_id="portfolio-r4-fact-receipt",
            source_receipt_version="receipt.v1",
            as_of=original.recorded_at,
        )
    )

    assert result.observation_id == original.observation_id
    assert result.owner_recorded_at == original.recorded_at
    assert definition_provider.calls == 2
    assert source_provider.calls == 2
    assert store.value == result


def test_raw_fact_clock_mismatch_drift_throw_and_owner_replacement_are_inert() -> None:
    original = monitoring_observation(period_index=0)
    definition = R4MonitoringRawFactDefinition(
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
            PortfolioR4MonitoringRawMetric(
                metric_key=item.metric_key.value,
                unit=item.unit,
                value=item.value,
            )
            for item in original.metrics
        ),
    )
    source = PortfolioR4MonitoringRawFactSourceReceipt.create(
        source_receipt_id="portfolio-r4-fact-receipt",
        source_receipt_version="receipt.v1",
        definition_hash=definition.content_hash,
        available_at=original.available_at,
        valid_until=original.valid_until,
    )
    command = RegisterPortfolioR4MonitoringRawFactCommand(
        original.observation_id,
        original.observation_version,
        "portfolio-r4-fact-receipt",
        "receipt.v1",
        original.recorded_at,
    )
    mismatch_clock = _Clock(original.recorded_at)
    mismatch_clock.unit_of_work_key = "django:other"
    with pytest.raises(PortfolioR4MonitoringRawFactUnavailable, match="unit of work"):
        RegisterPortfolioR4MonitoringRawFact(
            definition_provider=_Provider(definition),
            source_provider=_Provider(source),
            store=_Store(),
            clock=mismatch_clock,
        )

    store = _Store()
    clock = _Clock(original.recorded_at)
    service = RegisterPortfolioR4MonitoringRawFact(
        definition_provider=_Provider(definition),
        source_provider=_Provider(source),
        store=store,
        clock=clock,
    )
    clock.unit_of_work_key = "django:other"
    with pytest.raises(PortfolioR4MonitoringRawFactUnavailable, match="unit of work"):
        service.execute(command)
    assert store.value is None

    clock.unit_of_work_key = "django:default"
    object.__setattr__(service, "_source_provider", _Provider(source))
    with pytest.raises(PortfolioR4MonitoringRawFactUnavailable, match="replaced"):
        service.execute(command)
    assert store.value is None

    throwing = RegisterPortfolioR4MonitoringRawFact(
        definition_provider=_Provider(definition),
        source_provider=_Provider(source),
        store=store,
        clock=_ThrowingClock(original.recorded_at),
    )
    with pytest.raises(PortfolioR4MonitoringRawFactUnavailable, match="unavailable"):
        throwing.execute(command)
    assert store.value is None
