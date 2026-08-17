"""Migration evidence for the schema-only Portfolio R4 rolling ledger."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


def _rows(model: Any) -> list[dict[str, object]]:
    return list(model.objects.order_by(model._meta.pk.name).values())


@pytest.mark.django_db(transaction=True)
def test_0007_is_schema_only_zero_seed_and_preserves_0006_rows() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    before = [("portfolio", "0006_governed_optimization_research_ledger")]
    after = [("portfolio", "0007_r4_rolling_research_ledger")]
    try:
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        Snapshot = old_apps.get_model("portfolio", "CanonicalPortfolioSnapshotModel")
        OldResult = old_apps.get_model(
            "portfolio",
            "GovernedOptimizationResearchResultModel",
        )
        OldEvent = old_apps.get_model(
            "portfolio",
            "OptimizationResearchLifecycleEventModel",
        )
        Snapshot.objects.create(
            snapshot_id="portfolio_snapshot:migration0007",
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
        old_result = OldResult.objects.create(
            result_id="r8:migration0007",
            result_version="governed-optimization-result.v1",
            run_key="run:migration0007",
            run_version="run.v1",
            assembly_hash="1" * 64,
            problem_id="problem:migration0007",
            problem_hash="2" * 64,
            input_set_id="input:migration0007",
            input_set_hash="3" * 64,
            status="blocked",
            selected_candidate="",
            candidates=[],
            problem_blockers=[],
            evaluated_at=datetime(2026, 8, 5, 9, tzinfo=UTC),
            valid_until=datetime(2026, 8, 6, 9, tzinfo=UTC),
            content_hash="4" * 64,
            canonical_payload={},
            research_only=True,
            must_not_execute=True,
            must_not_use_for_decision=True,
        )
        OldEvent.objects.create(
            event_id="r8-event:migration0007",
            result=old_result,
            result_hash=old_result.content_hash,
            event_type="recorded",
            sequence=1,
            occurred_at=datetime(2026, 8, 5, 9, tzinfo=UTC),
            recorded_at=datetime(2026, 8, 5, 9, tzinfo=UTC),
            reason_codes=[],
            previous_event_hash=None,
            promotion_attestation=None,
            owner_attestation=None,
            content_hash="5" * 64,
            canonical_payload={},
            research_only=True,
            must_not_execute=True,
            must_not_use_for_decision=True,
        )
        expected_snapshot = _rows(Snapshot)
        expected_result = _rows(OldResult)
        expected_event = _rows(OldEvent)

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        new_apps = executor.loader.project_state(after).apps
        NewSnapshot = new_apps.get_model(
            "portfolio",
            "CanonicalPortfolioSnapshotModel",
        )
        NewOldResult = new_apps.get_model(
            "portfolio",
            "GovernedOptimizationResearchResultModel",
        )
        NewOldEvent = new_apps.get_model(
            "portfolio",
            "OptimizationResearchLifecycleEventModel",
        )
        Receipt = new_apps.get_model("portfolio", "R4RollingResearchReceiptModel")
        Result = new_apps.get_model("portfolio", "R4RollingResearchResultModel")
        assert _rows(NewSnapshot) == expected_snapshot
        assert _rows(NewOldResult) == expected_result
        assert _rows(NewOldEvent) == expected_event
        assert Receipt.objects.count() == 0
        assert Result.objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0007_tables_and_identity_clock_research_constraints_exist() -> None:
    tables = set(connection.introspection.table_names())
    assert "portfolio_r4_rolling_research_receipt" in tables
    assert "portfolio_r4_rolling_research_result" in tables
    with connection.cursor() as cursor:
        receipt_constraints = connection.introspection.get_constraints(
            cursor,
            "portfolio_r4_rolling_research_receipt",
        )
        result_constraints = connection.introspection.get_constraints(
            cursor,
            "portfolio_r4_rolling_research_result",
        )
    assert {
        "pf_r4_receipt_identity_uq",
        "pf_r4_receipt_eval_record_ck",
        "pf_r4_receipt_record_valid_ck",
        "pf_r4_receipt_owner_ck",
    } <= set(receipt_constraints)
    assert {
        "pf_r4_result_receipt_uq",
        "pf_r4_result_eligible_ck",
        "pf_r4_result_research_ck",
    } <= set(result_constraints)
