"""Migration evidence for the schema-only governed R8 result ledger."""

from __future__ import annotations

from datetime import UTC, datetime
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
