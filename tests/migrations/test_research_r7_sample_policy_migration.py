"""Migration evidence for schema-only Research R7 sample policy ledgers."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from typing import Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_MIGRATION_HASHES = {
    "0001_initial.py": "2A72A176E015B98F915DF2D9FEDEACF131DBC435E306AC1DE7D035AC8CCAD617",
    "0002_scenario_review_reminder_ledger.py": (
        "2E99BF9F17901ACB31873935C81E039A32DA34493929939FF4CBC89AFFB6E70D"
    ),
    "0003_r1_forecast_promotion_ledgers.py": (
        "8855F9DE31EE930967EDBECC1F46B924D78EA46297C57F6D1294CCC46F8357A7"
    ),
    "0004_r4_promotion_ledgers.py": (
        "B99038B51404025E3D798A5DCDBC7C566D3AE12B039241470B45F63FF3155516"
    ),
}
R7_TABLES = {
    "research_r7_sample_policy_approval",
    "research_r7_sample_policy",
}


def _rows(model: Any) -> list[dict[str, object]]:
    return list(model.objects.order_by(model._meta.pk.name).values())


def _canonical_migration_digest(path: Path) -> str:
    """Hash repository text independently of checkout line-ending policy."""

    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest().upper()


def test_legacy_research_migration_bytes_are_unchanged() -> None:
    migration_root = REPO_ROOT / "apps" / "research" / "migrations"
    for file_name, expected in LEGACY_MIGRATION_HASHES.items():
        assert _canonical_migration_digest(migration_root / file_name) == expected


def test_0005_is_schema_only_and_depends_only_on_research_0004() -> None:
    module = importlib.import_module("apps.research.migrations.0005_r7_sample_policy_ledger")
    migration = module.Migration

    assert migration.dependencies == [("research", "0004_r4_promotion_ledgers")]
    assert {type(item).__name__ for item in migration.operations} == {"CreateModel"}


@pytest.mark.django_db(transaction=True)
def test_0005_is_zero_seed_and_preserves_existing_research_rows() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    before = [("research", "0004_r4_promotion_ledgers")]
    after = [("research", "0005_r7_sample_policy_ledger")]
    try:
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        Experiment = old_apps.get_model("research", "ResearchExperiment")
        Experiment.objects.create(
            experiment_id="r7-migration-sentinel",
            question="Does R7 preserve old bytes?",
            hypothesis="Schema-only migration preserves the row.",
            status="draft",
        )
        expected = _rows(Experiment)

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        new_apps = executor.loader.project_state(after).apps
        Preserved = new_apps.get_model("research", "ResearchExperiment")
        assert _rows(Preserved) == expected
        assert (
            new_apps.get_model("research", "R7SamplePolicyApprovalReceiptModel").objects.count()
            == 0
        )
        assert new_apps.get_model("research", "R7SamplePolicyModel").objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0005_tables_constraints_index_and_protected_fk_exist() -> None:
    assert R7_TABLES <= set(connection.introspection.table_names())
    expected_constraints = {
        "research_r7_sample_policy_approval": {
            "res_r7_auth_identity_uq",
            "res_r7_auth_owner_uq",
            "res_r7_auth_policy_uq",
            "res_r7_auth_clock_ck",
        },
        "research_r7_sample_policy": {
            "res_r7_policy_pit_ix",
            "res_r7_policy_identity_uq",
            "res_r7_policy_clock_ck",
            "res_r7_policy_safety_ck",
        },
    }
    with connection.cursor() as cursor:
        for table, expected in expected_constraints.items():
            constraints = connection.introspection.get_constraints(cursor, table)
            assert expected <= set(constraints)
        policy_constraints = connection.introspection.get_constraints(
            cursor,
            "research_r7_sample_policy",
        )
        foreign_targets = {
            details["foreign_key"][0]
            for details in policy_constraints.values()
            if details.get("foreign_key")
        }
        assert foreign_targets == {"research_r7_sample_policy_approval"}
