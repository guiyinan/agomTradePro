"""Schema-only migration proof for canonical R5 monitoring owners."""

from __future__ import annotations

from importlib import import_module

from django.db import migrations

from apps.portfolio.infrastructure.r5_monitoring_raw_fact_models import (
    PortfolioR5MonitoringRawFactReceiptModel,
)
from apps.research.infrastructure.r5_monitoring_owner_models import (
    R5MonitoringCalendarRegistryModel,
    R5MonitoringPolicyRegistryModel,
)


def test_r5_owner_models_publish_three_distinct_append_only_tables() -> None:
    assert (
        R5MonitoringPolicyRegistryModel._meta.db_table == "research_r5_monitoring_policy_registry"
    )
    assert (
        R5MonitoringCalendarRegistryModel._meta.db_table
        == "research_r5_monitoring_calendar_registry"
    )
    assert (
        PortfolioR5MonitoringRawFactReceiptModel._meta.db_table
        == "portfolio_r5_monitoring_raw_fact_receipt"
    )


def test_r5_owner_migrations_use_exclusive_leaves_and_zero_seed() -> None:
    research = import_module("apps.research.migrations.0022_r5_monitoring_owner_registry").Migration
    portfolio = import_module(
        "apps.portfolio.migrations.0014_r5_monitoring_raw_fact_registry"
    ).Migration

    assert research.dependencies == [("research", "0021_r2_trial_policy_registry")]
    assert portfolio.dependencies == [("portfolio", "0013_r8_monitoring_calendar_registry")]
    assert [type(operation) for operation in research.operations] == [
        migrations.CreateModel,
        migrations.CreateModel,
        migrations.AddConstraint,
        migrations.AddConstraint,
        migrations.AddConstraint,
        migrations.AddConstraint,
        migrations.AddConstraint,
        migrations.AddConstraint,
    ]
    assert [operation.name for operation in research.operations[:2]] == [
        "R5MonitoringPolicyRegistryModel",
        "R5MonitoringCalendarRegistryModel",
    ]
    assert [type(operation) for operation in portfolio.operations] == [
        migrations.CreateModel,
        migrations.AddConstraint,
        migrations.AddConstraint,
        migrations.AddConstraint,
        migrations.AddConstraint,
    ]
    assert portfolio.operations[0].name == "PortfolioR5MonitoringRawFactReceiptModel"
    assert not any(
        isinstance(operation, (migrations.RunPython, migrations.RunSQL))
        for operation in (*research.operations, *portfolio.operations)
    )
