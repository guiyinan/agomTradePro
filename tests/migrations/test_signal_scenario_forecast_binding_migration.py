"""Migration coverage for R7-C0 scenario forecast evidence fields."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_signal_scenario_forecast_binding_migration_preserves_legacy_rows() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    published_at = datetime(2026, 8, 1, tzinfo=UTC)
    try:
        executor.migrate([("signal", "0009_forecast_ledger")])
        old_apps = executor.loader.project_state([("signal", "0009_forecast_ledger")]).apps
        OldEntry = old_apps.get_model("signal", "ForecastLedgerEntry")
        OldEntry._default_manager.create(
            entry_id="legacy-directional-entry",
            published_at=published_at,
            direction="LONG",
            asset_code="000001.SZ",
            horizon_end=published_at + timedelta(days=30),
            benchmark_asset="000300.SH",
            probability=0.55,
            invalidation_rule_version="rule-v1",
            decision_snapshot_id="decision-v1",
            pit_manifest_id="manifest-v1",
            source="strategy",
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("signal", "0010_scenario_forecast_binding")])
        new_apps = executor.loader.project_state(
            [("signal", "0010_scenario_forecast_binding")]
        ).apps
        NewEntry = new_apps.get_model("signal", "ForecastLedgerEntry")
        legacy = NewEntry._default_manager.get(entry_id="legacy-directional-entry")

        assert legacy.scenario_revision_id is None
        assert legacy.scenario_set_revision_id is None
        assert legacy.subjective_probability is None
        assert legacy.subjective_probability_source_version == ""
        assert legacy.model_probability is None
        assert legacy.model_probability_source_version == ""
        assert legacy.model_promotion_decision_id == ""

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                NewEntry._default_manager.create(
                    entry_id="invalid-set-only-entry",
                    published_at=published_at,
                    direction="NEUTRAL",
                    asset_code="000300.SH",
                    horizon_end=published_at + timedelta(days=30),
                    benchmark_asset="000300.SH",
                    probability=0.55,
                    invalidation_rule_version="rule-v1",
                    decision_snapshot_id="decision-v1",
                    pit_manifest_id="manifest-v1",
                    source="scenario_research",
                    scenario_set_revision_id=uuid4(),
                )
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
