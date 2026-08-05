"""Migration evidence for the legacy Account stress-scenario catalog."""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_legacy_scenario_seed_is_reversible_and_idempotent() -> None:
    """Three aliases and exact windows survive a down/up migration cycle once."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("risk_center", "0002_riskdailyreportmodel")])
        executor = MigrationExecutor(connection)
        executor.migrate([("risk_center", "0004_seed_legacy_stress_scenarios")])
        apps = executor.loader.project_state(
            [("risk_center", "0004_seed_legacy_stress_scenarios")]
        ).apps
        Definition = apps.get_model("risk_center", "StressScenarioDefinitionModel")
        Revision = apps.get_model("risk_center", "StressScenarioRevisionModel")

        assert Revision.objects.filter(source_type="legacy_code_migration").count() == 3
        aliases = {
            tuple(item.legacy_aliases): (item.revisions.get(version=1).parameters)
            for item in Definition.objects.filter(revisions__source_type="legacy_code_migration")
        }
        assert aliases == {
            ("2015_crash",): {
                "start_date": "2015-06-12",
                "end_date": "2015-08-26",
                "source": "legacy.account.tushare_stock_adapter",
                "event_description": "2015年6月-8月股市暴跌",
            },
            ("2020_covid",): {
                "start_date": "2020-01-14",
                "end_date": "2020-03-23",
                "source": "legacy.account.tushare_stock_adapter",
                "event_description": "2020年1月-3月COVID-19疫情冲击",
            },
            ("2018_trade_war",): {
                "start_date": "2018-01-02",
                "end_date": "2018-12-28",
                "source": "legacy.account.tushare_stock_adapter",
                "event_description": "2018年全年中美贸易战",
            },
        }

        executor = MigrationExecutor(connection)
        executor.migrate([("risk_center", "0003_scenario_governance_models")])
        executor = MigrationExecutor(connection)
        executor.migrate([("risk_center", "0004_seed_legacy_stress_scenarios")])
        apps = executor.loader.project_state(
            [("risk_center", "0004_seed_legacy_stress_scenarios")]
        ).apps
        Revision = apps.get_model("risk_center", "StressScenarioRevisionModel")
        assert Revision.objects.filter(source_type="legacy_code_migration").count() == 3
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
