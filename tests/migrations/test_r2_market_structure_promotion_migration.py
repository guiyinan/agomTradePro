"""Migration contract for schema-only R2 promotion ledgers."""

from __future__ import annotations

import importlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.operations.special import RunPython

pytestmark = pytest.mark.django_db(transaction=True)


def test_r2_promotion_migration_is_schema_only_and_depends_on_r6() -> None:
    migration_module = importlib.import_module(
        "apps.research.migrations.0009_r2_market_structure_promotion_ledgers"
    )
    migration = migration_module.Migration

    assert migration.dependencies == [("research", "0008_r6_qualification_ledgers")]
    assert not any(isinstance(operation, RunPython) for operation in migration.operations)
    assert [operation.name for operation in migration.operations] == [
        "R2MarketStructurePromotionPolicyModel",
        "R2MarketStructurePromotionDecisionModel",
        "R2MarketStructurePromotionLifecycleEventModel",
    ]


def test_r2_promotion_migration_creates_empty_append_only_tables() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate([("research", "0008_r6_qualification_ledgers")])
    executor = MigrationExecutor(connection)
    executor.migrate([("research", "0009_r2_market_structure_promotion_ledgers")])

    tables = set(connection.introspection.table_names())
    expected = {
        "research_r2_ms_promotion_policy",
        "research_r2_ms_promotion_decision",
        "research_r2_ms_promotion_lifecycle",
    }
    assert expected <= tables
    with connection.cursor() as cursor:
        for table in sorted(expected):
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            assert cursor.fetchone() == (0,)

    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
