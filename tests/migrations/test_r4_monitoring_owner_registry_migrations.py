"""Schema-only migration contract for R4 canonical monitoring owners."""

from __future__ import annotations

from importlib import import_module

from django.db import migrations

from apps.portfolio.infrastructure.r4_monitoring_raw_fact_models import (
    PortfolioR4MonitoringRawFactReceiptModel,
)
from apps.research.infrastructure.r4_promotion_monitoring_owner_models import (
    R4MonitoringCalendarLedgerModel,
    R4MonitoringPolicyLedgerModel,
)


def test_owner_registry_models_publish_distinct_schema_only_tables() -> None:
    assert R4MonitoringPolicyLedgerModel._meta.db_table == "research_r4_monitoring_policy"
    assert (
        R4MonitoringCalendarLedgerModel._meta.db_table == "research_r4_monitoring_period_calendar"
    )
    assert (
        PortfolioR4MonitoringRawFactReceiptModel._meta.db_table
        == "portfolio_r4_monitoring_raw_fact_receipt"
    )


def test_owner_registry_migrations_are_leaf_schema_only_and_zero_seed() -> None:
    research = import_module("apps.research.migrations.0019_r4_monitoring_owner_registry").Migration
    portfolio = import_module(
        "apps.portfolio.migrations.0012_r4_monitoring_raw_fact_receipt"
    ).Migration

    assert research.dependencies == [("research", "0018_r7_result_family_lifecycle_ledgers")]
    assert portfolio.dependencies == [
        ("portfolio", "0011_governed_optimization_monitoring_ledgers")
    ]
    assert [type(operation) for operation in research.operations] == [
        migrations.CreateModel,
        migrations.CreateModel,
    ]
    assert [operation.name for operation in research.operations] == [
        "R4MonitoringCalendarLedgerModel",
        "R4MonitoringPolicyLedgerModel",
    ]
    assert [type(operation) for operation in portfolio.operations] == [migrations.CreateModel]
    assert [operation.name for operation in portfolio.operations] == [
        "PortfolioR4MonitoringRawFactReceiptModel"
    ]
    assert not any(
        isinstance(operation, (migrations.RunPython, migrations.RunSQL))
        for operation in (*research.operations, *portfolio.operations)
    )
