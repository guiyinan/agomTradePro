"""Migration evidence for schema-only Research R5 promotion ledgers."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from typing import Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

REPO_ROOT = Path(__file__).resolve().parents[2]
PREVIOUS_MIGRATION_HASH = "5BFDD5EABCC8E3318890A8622DF48CA8805CD30745DC941A3553A1DA204746AE"
R5_TABLES = {
    "research_r5_promotion_artifact",
    "research_r5_promotion_decision_auth",
    "research_r5_promotion_decision_bundle",
    "research_r5_promotion_lifecycle_auth",
    "research_r5_promotion_lifecycle_event",
}


def _rows(model: Any) -> list[dict[str, object]]:
    return list(model.objects.order_by(model._meta.pk.name).values())


def test_0005_bytes_are_unchanged() -> None:
    path = REPO_ROOT / "apps" / "research" / "migrations" / "0005_r7_sample_policy_ledger.py"
    assert hashlib.sha256(path.read_bytes()).hexdigest().upper() == PREVIOUS_MIGRATION_HASH


def test_0006_is_schema_only_and_depends_only_on_research_0005() -> None:
    module = importlib.import_module(
        "apps.research.migrations.0006_r5_relative_value_promotion_ledgers"
    )
    migration = module.Migration

    assert migration.dependencies == [("research", "0005_r7_sample_policy_ledger")]
    assert {type(item).__name__ for item in migration.operations} <= {
        "CreateModel",
        "AddConstraint",
        "AddIndex",
    }


@pytest.mark.django_db(transaction=True)
def test_0006_is_zero_seed_and_preserves_existing_research_rows() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    before = [("research", "0005_r7_sample_policy_ledger")]
    after = [("research", "0006_r5_relative_value_promotion_ledgers")]
    try:
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        Experiment = old_apps.get_model("research", "ResearchExperiment")
        Experiment.objects.create(
            experiment_id="r5-promotion-migration-sentinel",
            question="Does R5 preserve existing Research evidence?",
            hypothesis="A schema-only migration preserves every old row.",
            status="draft",
        )
        expected = _rows(Experiment)

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        new_apps = executor.loader.project_state(after).apps
        Preserved = new_apps.get_model("research", "ResearchExperiment")
        assert _rows(Preserved) == expected
        for model_name in (
            "R5PromotionArtifactModel",
            "R5PromotionDecisionAuthorizationModel",
            "R5PromotionDecisionBundleModel",
            "R5PromotionLifecycleAuthorizationModel",
            "R5PromotionLifecycleEventModel",
        ):
            assert new_apps.get_model("research", model_name).objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0006_constraints_indexes_and_research_only_foreign_keys_exist() -> None:
    assert R5_TABLES <= set(connection.introspection.table_names())
    expected_constraints = {
        "research_r5_promotion_artifact": {
            "res_r5_art_identity_uq",
            "res_r5_art_kind_ck",
            "res_r5_art_authority_ck",
            "res_r5_art_time_ck",
            "res_r5_art_research_ck",
        },
        "research_r5_promotion_decision_auth": {
            "res_r5_da_identity_uq",
            "res_r5_da_authority_ck",
            "res_r5_da_time_ck",
        },
        "research_r5_promotion_decision_bundle": {
            "res_r5_db_identity_uq",
            "res_r5_db_authority_ck",
            "res_r5_db_time_ck",
            "res_r5_db_research_ck",
        },
        "research_r5_promotion_lifecycle_auth": {
            "res_r5_la_evidence_uq",
            "res_r5_la_auth_uq",
            "res_r5_la_event_uq",
            "res_r5_la_target_ck",
            "res_r5_la_time_ck",
        },
        "research_r5_promotion_lifecycle_event": {
            "res_r5_le_stream_rec_ix",
            "res_r5_le_identity_uq",
            "res_r5_le_stream_seq_uq",
            "res_r5_le_previous_uq",
            "res_r5_le_time_ck",
            "res_r5_le_link_ck",
            "res_r5_le_target_ck",
            "res_r5_le_research_ck",
        },
    }
    with connection.cursor() as cursor:
        for table, expected in expected_constraints.items():
            constraints = connection.introspection.get_constraints(cursor, table)
            assert expected <= set(constraints)
            foreign_targets = {
                details["foreign_key"][0]
                for details in constraints.values()
                if details.get("foreign_key")
            }
            assert all(target.startswith("research_r5_") for target in foreign_targets)
