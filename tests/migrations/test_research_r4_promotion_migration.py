"""Migration evidence for the schema-only Research R4 promotion ledgers."""

from __future__ import annotations

import hashlib
import importlib
from datetime import UTC, datetime
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
}
R4_TABLES = {
    "research_r4_promotion_policy",
    "research_r4_promotion_decision_receipt",
    "research_r4_promotion_decision_bundle",
    "research_r4_promotion_lifecycle_auth_receipt",
    "research_r4_promotion_lifecycle_event",
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


def test_0004_operation_allowlist_has_no_seed_or_portfolio_dependency() -> None:
    module = importlib.import_module("apps.research.migrations.0004_r4_promotion_ledgers")
    migration = module.Migration
    assert migration.dependencies == [("research", "0003_r1_forecast_promotion_ledgers")]
    assert {type(item).__name__ for item in migration.operations} <= {
        "CreateModel",
        "AddField",
        "AddConstraint",
        "AddIndex",
    }


@pytest.mark.django_db(transaction=True)
def test_0004_is_zero_seed_and_preserves_complete_0003_policy_row() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    before = [("research", "0003_r1_forecast_promotion_ledgers")]
    after = [("research", "0004_r4_promotion_ledgers")]
    try:
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        OldPolicy = old_apps.get_model("research", "R1ForecastPromotionPolicyModel")
        OldPolicy.objects.create(
            policy_id="r1-policy:migration0004",
            policy_version="policy.v1",
            owner="research",
            capability="r1",
            purpose="valuation",
            status="active",
            scope_id="r1-scope:migration0004",
            scope_content_hash="1" * 64,
            subject_code="000001.SZ",
            industry_code="bank",
            candidate_scenario="base",
            horizon_quarters=4,
            calendar_schedule_hash="2" * 64,
            metric_codes=["revenue"],
            approved_at=datetime(2026, 1, 1, tzinfo=UTC),
            recorded_at=datetime(2026, 1, 2, tzinfo=UTC),
            active_from=datetime(2026, 1, 3, tzinfo=UTC),
            active_until=datetime(2026, 12, 31, tzinfo=UTC),
            canonical_payload={"sentinel": ["bytes", 7, True]},
            content_hash="3" * 64,
            research_only=True,
            must_not_use_for_decision=True,
            must_not_execute=True,
        )
        expected = _rows(OldPolicy)

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        new_apps = executor.loader.project_state(after).apps
        Preserved = new_apps.get_model("research", "R1ForecastPromotionPolicyModel")
        assert _rows(Preserved) == expected
        for model_name in (
            "R4PromotionPolicyModel",
            "R4PromotionDecisionReceiptModel",
            "R4PromotionDecisionBundleModel",
            "R4PromotionLifecycleAuthorizationReceiptModel",
            "R4PromotionLifecycleEventModel",
        ):
            assert new_apps.get_model("research", model_name).objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0004_physical_constraints_indexes_and_fk_ownership_exist() -> None:
    assert R4_TABLES <= set(connection.introspection.table_names())
    expected_constraints = {
        "research_r4_promotion_policy": {
            "res_r4_pol_identity_uq",
            "res_r4_pol_authority_ck",
            "res_r4_pol_time_ck",
            "res_r4_pol_research_ck",
        },
        "research_r4_promotion_decision_receipt": {
            "res_r4_dr_identity_uq",
            "res_r4_dr_decision_uq",
            "res_r4_dr_authority_ck",
            "res_r4_dr_time_ck",
        },
        "research_r4_promotion_decision_bundle": {
            "res_r4_db_identity_uq",
            "res_r4_db_authority_ck",
            "res_r4_db_time_ck",
            "res_r4_db_research_ck",
        },
        "research_r4_promotion_lifecycle_auth_receipt": {
            "res_r4_lr_auth_identity_uq",
            "res_r4_lr_event_identity_uq",
            "res_r4_lr_authority_ck",
            "res_r4_lr_time_ck",
            "res_r4_lr_target_ck",
        },
        "research_r4_promotion_lifecycle_event": {
            "res_r4_le_stream_rec_ix",
            "res_r4_le_identity_uq",
            "res_r4_le_stream_seq_uq",
            "res_r4_le_previous_uq",
            "res_r4_le_time_ck",
            "res_r4_le_link_ck",
            "res_r4_le_target_ck",
            "res_r4_le_research_ck",
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
            assert all(not target.startswith("portfolio_") for target in foreign_targets)
