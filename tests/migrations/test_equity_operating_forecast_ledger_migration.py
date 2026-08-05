"""Migration coverage for the Equity R1 operating-forecast ledger."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_equity_operating_forecast_migration_creates_append_ledger_constraints() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("equity", "0009_enforce_single_active_configs")])
        old_apps = executor.loader.project_state(
            [("equity", "0009_enforce_single_active_configs")]
        ).apps
        with pytest.raises(LookupError):
            old_apps.get_model("equity", "OperatingForecastVersionModel")

        executor = MigrationExecutor(connection)
        executor.migrate([("equity", "0010_operating_forecast_ledger")])
        apps = executor.loader.project_state([("equity", "0010_operating_forecast_ledger")]).apps
        Forecast = apps.get_model("equity", "OperatingForecastVersionModel")
        Projection = apps.get_model("equity", "OperatingForecastProjectionModel")
        Assumption = apps.get_model("equity", "OperatingForecastAssumptionModel")
        for model_name in (
            "OperatingForecastFactReferenceModel",
            "OperatingForecastEvaluationModel",
            "OperatingForecastSensitivityModel",
        ):
            assert apps.get_model("equity", model_name) is not None

        forecast = Forecast._default_manager.create(
            forecast_id="migration-valid-v1",
            forecast_key="000001.SZ-2026Q2",
            forecast_version=1,
            subject_code="000001.SZ",
            industry_code="consumer-service",
            as_of_time=datetime(2026, 4, 30, tzinfo=UTC),
            target_period_end=date(2026, 6, 30),
            horizon_quarters=1,
            methodology_ref="research-note-v1",
            created_by_ref="analyst-7",
            valuation_consumable=False,
            promotion_decision_id="",
            content_hash="a" * 64,
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Forecast._default_manager.create(
                    forecast_id="migration-invalid-promotion",
                    forecast_key="000001.SZ-2026Q3",
                    forecast_version=1,
                    subject_code="000001.SZ",
                    industry_code="consumer-service",
                    as_of_time=datetime(2026, 7, 31, tzinfo=UTC),
                    target_period_end=date(2026, 9, 30),
                    horizon_quarters=1,
                    methodology_ref="research-note-v1",
                    created_by_ref="analyst-7",
                    valuation_consumable=True,
                    promotion_decision_id="",
                    content_hash="b" * 64,
                )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Projection._default_manager.create(
                    forecast=forecast,
                    scenario="base",
                    revenue=Decimal("0"),
                    net_profit=Decimal("1"),
                    profit_margin_percent=Decimal("0"),
                    currency_unit="CNY_million",
                )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Assumption._default_manager.create(
                    forecast=forecast,
                    scenario="base",
                    assumption_key="invalid-observed-lineage",
                    value=Decimal("1"),
                    unit="count",
                    input_kind="observed_fact",
                    rationale="Missing PIT version id must fail.",
                    observed_fact_version_id=None,
                    human_assumption_ref="",
                    model_version="",
                )
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
