"""Migration evidence for the schema-only Portfolio R5 outcome ledger."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from django.db import connection
from django.db.migrations import CreateModel
from django.db.migrations.executor import MigrationExecutor

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_HISTORICAL_MIGRATION_HASHES = {
    "0001_transfer_transition_plan_state.py": "43d966c6baa44d5a208e855937842c2600649d1f98bc129245c2be6fc412482f",
    "0002_transition_plan_evidence.py": "ae6074bab9e58f8bb897599ea5a5181793715c0cae879684ce684b7f6c18ffb2",
    "0003_transfer_order_intent_state.py": "8d42166ff63f8a82a03c0f4046b9dc06dc21af7441227a5e69590ebde2cd2e24",
    "0004_portfolio_planning_policy.py": "08c0cacce2c470fd5fe1626ae9aa62f6e4e5b31c2ecee852aa7c310ea68e791c",
    "0005_canonical_portfolio_snapshot_and_feedback.py": "9fa28a8aabdda971e39b8982ca371499da412b297a9db292e46bcf3477e86f7b",
    "0006_governed_optimization_research_ledger.py": "7149107ea28ada80b5d5cb7f307126001bb68e3f45688e67544c0bf7cb39d775",
    "0007_r4_rolling_research_ledger.py": "7679b54ee8ee231ed5f877afc4856700906cf0f3040fee2516dde4e47111bd4e",
}


def _rows(model: Any) -> list[dict[str, object]]:
    return list(model.objects.order_by(model._meta.pk.name).values())


def _canonical_migration_digest(path: Path) -> str:
    """Hash repository text independently of checkout line-ending policy."""

    return sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_0008_is_create_only_and_preserves_historical_migration_bytes() -> None:
    migration_directory = _REPOSITORY_ROOT / "apps" / "portfolio" / "migrations"
    for filename, expected_hash in _HISTORICAL_MIGRATION_HASHES.items():
        assert _canonical_migration_digest(migration_directory / filename) == expected_hash

    migration = importlib.import_module(
        "apps.portfolio.migrations.0008_r5_relative_value_outcome_ledger"
    ).Migration
    assert migration.dependencies == [("portfolio", "0007_r4_rolling_research_ledger")]
    assert len(migration.operations) == 1
    assert all(isinstance(operation, CreateModel) for operation in migration.operations)


@pytest.mark.django_db(transaction=True)
def test_0008_preserves_0007_sentinel_and_seeds_no_r5_rows() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    before = [("portfolio", "0007_r4_rolling_research_ledger")]
    after = [("portfolio", "0008_r5_relative_value_outcome_ledger")]
    try:
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        Receipt = old_apps.get_model("portfolio", "R4RollingResearchReceiptModel")
        Result = old_apps.get_model("portfolio", "R4RollingResearchResultModel")
        receipt = Receipt.objects.create(
            receipt_id="r4:migration0008:sentinel",
            record_version="portfolio-r4-rolling-research.v1",
            study_id="study:migration0008",
            study_version="study.v1",
            study_content_hash="1" * 64,
            r3_promotion_attestation_hash="2" * 64,
            split_contract_hash="3" * 64,
            evaluated_at=datetime(2026, 8, 6, 9, tzinfo=UTC),
            owner="portfolio",
            recorded_at=datetime(2026, 8, 6, 10, tzinfo=UTC),
            producer_code_version="migration0008",
            dependency_lock_hash="4" * 64,
            valid_until=datetime(2026, 9, 6, 10, tzinfo=UTC),
            study_payload={"sentinel": True},
            promotion_attestation_payload={"sentinel": True},
        )
        Result.objects.create(
            record_id="r4-result:migration0008:sentinel",
            receipt=receipt,
            artifact_hash="5" * 64,
            evidence_complete=False,
            eligible_for_research_comparison=False,
            subhashes=[],
            artifact_payload={"sentinel": True},
            record_hash="6" * 64,
            usage_scope="research_only",
            must_not_use_for_decision=True,
            must_not_execute=True,
        )
        expected_receipts = _rows(Receipt)
        expected_results = _rows(Result)

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        new_apps = executor.loader.project_state(after).apps
        MigratedReceipt = new_apps.get_model(
            "portfolio",
            "R4RollingResearchReceiptModel",
        )
        MigratedResult = new_apps.get_model(
            "portfolio",
            "R4RollingResearchResultModel",
        )
        Outcome = new_apps.get_model(
            "portfolio",
            "PortfolioR5RelativeValueOutcomeModel",
        )
        assert _rows(MigratedReceipt) == expected_receipts
        assert _rows(MigratedResult) == expected_results
        assert Outcome.objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0008_table_and_identity_clock_safety_constraints_exist() -> None:
    tables = set(connection.introspection.table_names())
    assert "portfolio_r5_relative_value_outcome" in tables
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(
            cursor,
            "portfolio_r5_relative_value_outcome",
        )
    assert {
        "pf_r5_outcome_identity_uq",
        "pf_r5_outcome_owner_uq",
        "pf_r5_outcome_observation_uq",
        "pf_r5_outcome_clock_ck",
        "pf_r5_outcome_safety_ck",
        "pf_r5_outcome_nonneg_ck",
        "pf_r5_outcome_drawdown_ck",
    } <= set(constraints)
