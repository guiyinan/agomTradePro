from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from apps.portfolio.application.r5_monitoring_raw_fact_registry import (
    PortfolioR5MonitoringRawFactUnavailable,
    RegisterPortfolioR5MonitoringRawFact,
    RegisterPortfolioR5MonitoringRawFactCommand,
)
from apps.portfolio.domain.r5_monitoring_raw_fact_registry import (
    PortfolioR5MonitoringRawFactDefinition,
    PortfolioR5MonitoringRawFactSourceReceipt,
)
from tests.unit.research.test_r5_relative_value_monitoring import (
    _facts,
    _policy,
)


@dataclass
class _DefinitionProvider:
    value: PortfolioR5MonitoringRawFactDefinition
    unit_of_work_key: str = "django:default"
    calls: int = 0

    def get_exact(
        self,
        *,
        fact_id: str,
        fact_version: str,
        as_of: datetime,
    ) -> PortfolioR5MonitoringRawFactDefinition:
        del fact_id, fact_version, as_of
        self.calls += 1
        return self.value


@dataclass
class _SourceProvider:
    value: PortfolioR5MonitoringRawFactSourceReceipt
    unit_of_work_key: str = "django:default"
    calls: int = 0

    def get_exact(
        self,
        *,
        fact_id: str,
        fact_version: str,
        definition_hash: str,
        as_of: datetime,
    ) -> PortfolioR5MonitoringRawFactSourceReceipt:
        del fact_id, fact_version, definition_hash, as_of
        self.calls += 1
        return self.value


class _Store:
    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.values: list[object] = []
        self.atomic_entries = 0

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.atomic_entries += 1
        yield

    def append(
        self,
        *,
        definition: PortfolioR5MonitoringRawFactDefinition,
        source: PortfolioR5MonitoringRawFactSourceReceipt,
        ledger_recorded_at: datetime,
    ) -> object:
        del source, ledger_recorded_at
        self.values.append(definition.fact)
        return definition.fact


@dataclass
class _Clock:
    current: datetime
    unit_of_work_key: str = "django:default"
    calls: int = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.current


class _ThrowingClock(_Clock):
    def now(self) -> datetime:
        raise RuntimeError("clock failed")


def test_raw_fact_registration_double_reads_and_accepts_no_metric_payload() -> None:
    fact = _facts(_policy())[0]
    definition = PortfolioR5MonitoringRawFactDefinition.from_fact(fact)
    source = PortfolioR5MonitoringRawFactSourceReceipt.create(
        source_owner="portfolio",
        source_receipt_id="portfolio-source-receipt",
        source_receipt_version="v1",
        fact_id=fact.fact_id,
        fact_version=fact.fact_version,
        definition_hash=definition.content_hash,
        available_at=fact.recorded_at,
        valid_until=fact.valid_until,
    )
    definition_provider = _DefinitionProvider(definition)
    source_provider = _SourceProvider(source)
    store = _Store()
    clock = _Clock(fact.recorded_at + timedelta(minutes=1))

    result = RegisterPortfolioR5MonitoringRawFact(
        definition_provider=definition_provider,
        source_provider=source_provider,
        store=store,
        clock=clock,
    ).execute(
        RegisterPortfolioR5MonitoringRawFactCommand(
            fact_id=fact.fact_id,
            fact_version=fact.fact_version,
        )
    )

    assert result == fact
    assert definition_provider.calls == 2
    assert source_provider.calls == 2
    assert clock.calls == 1
    assert store.atomic_entries == 1
    assert store.values == [fact]
    assert tuple(RegisterPortfolioR5MonitoringRawFactCommand.__dataclass_fields__) == (
        "fact_id",
        "fact_version",
    )


def test_raw_fact_clock_mismatch_drift_throw_and_owner_replacement_are_zero_write() -> None:
    fact = _facts(_policy())[0]
    definition = PortfolioR5MonitoringRawFactDefinition.from_fact(fact)
    source = PortfolioR5MonitoringRawFactSourceReceipt.create(
        source_owner="portfolio",
        source_receipt_id="portfolio-source-receipt",
        source_receipt_version="v1",
        fact_id=fact.fact_id,
        fact_version=fact.fact_version,
        definition_hash=definition.content_hash,
        available_at=fact.recorded_at,
        valid_until=fact.valid_until,
    )
    now = fact.recorded_at + timedelta(minutes=1)
    with pytest.raises(PortfolioR5MonitoringRawFactUnavailable, match="unit of work"):
        RegisterPortfolioR5MonitoringRawFact(
            definition_provider=_DefinitionProvider(definition),
            source_provider=_SourceProvider(source),
            store=_Store(),
            clock=_Clock(now, unit_of_work_key="django:other"),
        )

    store = _Store()
    clock = _Clock(now)
    service = RegisterPortfolioR5MonitoringRawFact(
        definition_provider=_DefinitionProvider(definition),
        source_provider=_SourceProvider(source),
        store=store,
        clock=clock,
    )
    command = RegisterPortfolioR5MonitoringRawFactCommand(fact.fact_id, fact.fact_version)
    clock.unit_of_work_key = "django:other"
    with pytest.raises(PortfolioR5MonitoringRawFactUnavailable, match="unit of work"):
        service.execute(command)
    assert store.values == []

    clock.unit_of_work_key = "django:default"
    object.__setattr__(service, "_source_provider", _SourceProvider(source))
    with pytest.raises(PortfolioR5MonitoringRawFactUnavailable, match="replaced"):
        service.execute(command)
    assert store.values == []

    throwing_store = _Store()
    throwing = RegisterPortfolioR5MonitoringRawFact(
        definition_provider=_DefinitionProvider(definition),
        source_provider=_SourceProvider(source),
        store=throwing_store,
        clock=_ThrowingClock(now),
    )
    with pytest.raises(PortfolioR5MonitoringRawFactUnavailable, match="unavailable"):
        throwing.execute(command)
    assert throwing_store.values == []
