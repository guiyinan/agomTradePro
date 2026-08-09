"""Migration evidence for the schema-only governed R8 result ledger."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


def _rows(model: Any) -> list[dict[str, object]]:
    return list(model.objects.order_by("snapshot_id").values())


@pytest.mark.django_db(transaction=True)
def test_0006_is_schema_only_and_preserves_0005_snapshot_rows() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    before = [("portfolio", "0005_canonical_portfolio_snapshot_and_feedback")]
    after = [("portfolio", "0006_governed_optimization_research_ledger")]
    try:
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        Snapshot = old_apps.get_model("portfolio", "CanonicalPortfolioSnapshotModel")
        Snapshot.objects.create(
            snapshot_id="portfolio_snapshot:migration0006",
            account_ref="account:migration",
            as_of=datetime(2026, 8, 5, 9, tzinfo=UTC),
            base_currency="CNY",
            cash_balance=Decimal("100"),
            cash_version="cash.v1",
            positions_version="positions.v1",
            cash_observed_at=datetime(2026, 8, 5, 8, tzinfo=UTC),
            positions_observed_at=datetime(2026, 8, 5, 9, tzinfo=UTC),
            positions=[],
            source_evidence=[],
            content_hash="a" * 64,
        )
        expected = _rows(Snapshot)

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        new_apps = executor.loader.project_state(after).apps
        NewSnapshot = new_apps.get_model(
            "portfolio",
            "CanonicalPortfolioSnapshotModel",
        )
        Result = new_apps.get_model(
            "portfolio",
            "GovernedOptimizationResearchResultModel",
        )
        Event = new_apps.get_model(
            "portfolio",
            "OptimizationResearchLifecycleEventModel",
        )
        assert _rows(NewSnapshot) == expected
        assert Result.objects.count() == 0
        assert Event.objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0006_tables_and_append_only_identity_constraints_exist() -> None:
    tables = set(connection.introspection.table_names())
    assert "portfolio_governed_optimization_result" in tables
    assert "portfolio_optimization_lifecycle_event" in tables
    with connection.cursor() as cursor:
        result_constraints = connection.introspection.get_constraints(
            cursor,
            "portfolio_governed_optimization_result",
        )
        lifecycle_constraints = connection.introspection.get_constraints(
            cursor,
            "portfolio_optimization_lifecycle_event",
        )
    assert {
        "pf_opt_result_run_ver_uq",
        "pf_opt_result_valid_eval_ck",
        "pf_opt_result_research_ck",
    } <= set(result_constraints)
    assert {
        "pf_opt_lc_result_seq_uq",
        "pf_opt_lc_shape_ck",
        "pf_opt_lc_research_ck",
    } <= set(lifecycle_constraints)


@pytest.mark.django_db(transaction=True)
def test_0009_is_schema_only_preserves_legacy_results_and_does_not_backfill() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    before = [("portfolio", "0008_r5_relative_value_outcome_ledger")]
    after = [("portfolio", "0009_governed_optimization_input_receipt")]
    evaluated_at = datetime(2026, 8, 5, 9, tzinfo=UTC)
    try:
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        LegacyResult = old_apps.get_model(
            "portfolio",
            "GovernedOptimizationResearchResultModel",
        )
        LegacyResult.objects.create(
            result_id="optimization-result:migration0009",
            result_version="governed-optimization-research-result.v1",
            run_key="migration0009-run",
            run_version="run.v1",
            assembly_hash="1" * 64,
            problem_id="problem:migration0009",
            problem_hash="2" * 64,
            input_set_id="legacy-input-set:migration0009",
            input_set_hash="3" * 64,
            status="blocked",
            selected_candidate="",
            candidates=[],
            problem_blockers=[["legacy.result", "receipt_not_historically_available"]],
            evaluated_at=evaluated_at,
            valid_until=evaluated_at + timedelta(days=1),
            content_hash="4" * 64,
            canonical_payload={"schema": "legacy-result.v1"},
            research_only=True,
            must_not_execute=True,
            must_not_use_for_decision=True,
        )

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        new_apps = executor.loader.project_state(after).apps
        Result = new_apps.get_model(
            "portfolio",
            "GovernedOptimizationResearchResultModel",
        )
        Receipt = new_apps.get_model(
            "portfolio",
            "GovernedOptimizationInputReceiptModel",
        )
        row = Result.objects.get(result_id="optimization-result:migration0009")
        assert row.input_receipt_id is None
        assert row.input_set_id == "legacy-input-set:migration0009"
        assert Receipt.objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0009_receipt_table_constraints_and_nullable_legacy_fk_exist() -> None:
    tables = set(connection.introspection.table_names())
    assert "portfolio_governed_optimization_input_receipt" in tables
    with connection.cursor() as cursor:
        receipt_constraints = connection.introspection.get_constraints(
            cursor,
            "portfolio_governed_optimization_input_receipt",
        )
        result_constraints = connection.introspection.get_constraints(
            cursor,
            "portfolio_governed_optimization_result",
        )
    assert {
        "pf_opt_receipt_clock_ck",
        "pf_opt_receipt_safety_ck",
        "pf_opt_receipt_pit_idx",
    } <= set(receipt_constraints)
    assert any(
        constraint.get("foreign_key")
        == ("portfolio_governed_optimization_input_receipt", "receipt_id")
        for constraint in result_constraints.values()
    )
