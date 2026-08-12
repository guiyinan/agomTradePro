"""Schema-only migration proof for the Signal calibration sample registry."""

from __future__ import annotations

from importlib import import_module

import pytest
from django.db import connection
from django.db.migrations import CreateModel, RunPython
from django.db.migrations.executor import MigrationExecutor


def test_signal_0013_is_leaf_schema_only_and_zero_seed_by_construction() -> None:
    """The migration creates exactly four tables and has no data operation."""

    module = import_module("apps.signal.migrations.0013_forecast_calibration_sample")
    migration = module.Migration

    assert migration.dependencies == [("signal", "0012_forecast_realization_source_definition")]
    assert [operation.name for operation in migration.operations] == [
        "ForecastCalibrationSampleDefinitionModel",
        "ForecastCalibrationExpectedMemberModel",
        "ForecastCalibrationSampleReceiptModel",
        "ForecastCalibrationSampleMemberReceiptModel",
    ]
    assert all(isinstance(operation, CreateModel) for operation in migration.operations)
    assert not any(isinstance(operation, RunPython) for operation in migration.operations)


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_signal_0013_forward_reverse_reforward_stays_zero_seed() -> None:
    """Forward/reforward remain empty and reverse removes only the new tables."""

    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    tables = {
        "signal_forecast_calibration_sample_definition",
        "signal_forecast_calibration_expected_member",
        "signal_forecast_calibration_sample_receipt",
        "signal_forecast_calibration_sample_member_receipt",
    }
    previous_table = "signal_forecast_realization_source_definition"
    try:
        MigrationExecutor(connection).migrate(
            [("signal", "0012_forecast_realization_source_definition")]
        )
        assert previous_table in connection.introspection.table_names()
        assert not tables.intersection(connection.introspection.table_names())

        executor = MigrationExecutor(connection)
        executor.migrate([("signal", "0013_forecast_calibration_sample")])
        apps = executor.loader.project_state([("signal", "0013_forecast_calibration_sample")]).apps
        for model_name in (
            "ForecastCalibrationSampleDefinitionModel",
            "ForecastCalibrationExpectedMemberModel",
            "ForecastCalibrationSampleReceiptModel",
            "ForecastCalibrationSampleMemberReceiptModel",
        ):
            assert apps.get_model("signal", model_name)._default_manager.count() == 0

        MigrationExecutor(connection).migrate(
            [("signal", "0012_forecast_realization_source_definition")]
        )
        assert previous_table in connection.introspection.table_names()
        assert not tables.intersection(connection.introspection.table_names())

        executor = MigrationExecutor(connection)
        executor.migrate([("signal", "0013_forecast_calibration_sample")])
        apps = executor.loader.project_state([("signal", "0013_forecast_calibration_sample")]).apps
        for model_name in (
            "ForecastCalibrationSampleDefinitionModel",
            "ForecastCalibrationExpectedMemberModel",
            "ForecastCalibrationSampleReceiptModel",
            "ForecastCalibrationSampleMemberReceiptModel",
        ):
            assert apps.get_model("signal", model_name)._default_manager.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
