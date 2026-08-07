"""Migration evidence for the schema-only R7 research result ledger."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

RESULT_TABLE = "research_r7_research_result"


def _rows(model: Any) -> list[dict[str, object]]:
    return list(model.objects.order_by(model._meta.pk.name).values())


def test_0007_is_schema_only_and_depends_on_research_0006() -> None:
    module = importlib.import_module("apps.research.migrations.0007_r7_research_result_ledger")
    migration = module.Migration

    assert migration.dependencies == [("research", "0006_r5_relative_value_promotion_ledgers")]
    assert {type(item).__name__ for item in migration.operations} == {"CreateModel"}


@pytest.mark.django_db(transaction=True)
def test_0007_is_zero_seed_and_preserves_existing_research_rows() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    before = [("research", "0006_r5_relative_value_promotion_ledgers")]
    after = [("research", "0007_r7_research_result_ledger")]
    try:
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        Experiment = old_apps.get_model("research", "ResearchExperiment")
        Experiment.objects.create(
            experiment_id="r7-result-migration-sentinel",
            question="Does R7 result persistence preserve existing rows?",
            hypothesis="The schema-only migration preserves exact bytes.",
            status="draft",
        )
        expected = _rows(Experiment)

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        new_apps = executor.loader.project_state(after).apps
        Preserved = new_apps.get_model("research", "ResearchExperiment")
        Result = new_apps.get_model("research", "R7ResearchResultModel")
        assert _rows(Preserved) == expected
        assert Result.objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0007_table_constraints_index_and_protected_policy_fk_exist() -> None:
    assert RESULT_TABLE in set(connection.introspection.table_names())
    expected = {
        "res_r7_result_pit_ix",
        "res_r7_result_identity_uq",
        "res_r7_result_clock_ck",
        "res_r7_result_safety_ck",
    }
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, RESULT_TABLE)
    assert expected <= set(constraints)
    foreign_targets = {
        details["foreign_key"][0] for details in constraints.values() if details.get("foreign_key")
    }
    assert foreign_targets == {"research_r7_sample_policy"}
