"""Migration evidence for the schema-only governed R8 result ledger."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.db import IntegrityError, connection, migrations, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

LEGACY_RESULT_VERSION = "governed-optimization-result.v1"
CANONICAL_RESULT_VERSION = "governed-optimization-result.v2"


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
            result_version=LEGACY_RESULT_VERSION,
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


def test_0010_adds_exact_result_and_receipt_version_constraints() -> None:
    """The post-0009 slice is schema-only and preserves the nullable legacy column."""

    module = importlib.import_module(
        "apps.portfolio.migrations.0010_governed_optimization_receipt_constraint"
    )

    assert module.Migration.dependencies == [
        ("portfolio", "0009_governed_optimization_input_receipt")
    ]
    assert len(module.Migration.operations) == 2
    assert all(
        isinstance(operation, migrations.AddConstraint) for operation in module.Migration.operations
    )
    assert {operation.constraint.name for operation in module.Migration.operations} == {
        "pf_opt_result_receipt_ver_ck",
        "pf_opt_receipt_version_ck",
    }


def test_0009_postgresql_reverse_guard_locks_before_evidence_queries() -> None:
    """PostgreSQL takes parent/child write locks before either evidence read."""

    module = importlib.import_module(
        "apps.portfolio.migrations.0009_governed_optimization_input_receipt"
    )
    events: list[str] = []

    class FakeQuerySet:
        def __init__(self, label: str) -> None:
            self._label = label

        def filter(self, *args: object, **kwargs: object) -> FakeQuerySet:
            events.append(f"filter:{self._label}")
            return self

        def exists(self) -> bool:
            events.append(f"exists:{self._label}")
            return False

    class FakeManager:
        def __init__(self, label: str) -> None:
            self._label = label

        def using(self, alias: str) -> FakeQuerySet:
            assert alias == "migration"
            return FakeQuerySet(self._label)

    class ReceiptMeta:
        db_table = "portfolio_governed_optimization_input_receipt"

        class pk:
            column = "receipt_id"

    class ResultMeta:
        db_table = "portfolio_governed_optimization_result"

    class Receipt:
        _meta = ReceiptMeta()
        objects = FakeManager("receipt")

    class Result:
        _meta = ResultMeta()
        objects = FakeManager("result")

    class FakeApps:
        def get_model(self, app_label: str, model_name: str) -> object:
            assert app_label == "portfolio"
            if model_name == "GovernedOptimizationInputReceiptModel":
                return Receipt
            assert model_name == "GovernedOptimizationResearchResultModel"
            return Result

    class FakeCursor:
        def __enter__(self) -> FakeCursor:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, sql: str) -> None:
            events.append(sql)

    class FakeConnection:
        vendor = "postgresql"
        alias = "migration"

        def cursor(self) -> FakeCursor:
            return FakeCursor()

    class FakeSchemaEditor:
        connection = FakeConnection()

        @staticmethod
        def quote_name(value: str) -> str:
            return f'"{value}"'

    module.refuse_receipt_evidence_loss(FakeApps(), FakeSchemaEditor())

    assert events == [
        'LOCK TABLE "portfolio_governed_optimization_input_receipt" ' "IN ACCESS EXCLUSIVE MODE",
        'LOCK TABLE "portfolio_governed_optimization_result" IN ACCESS EXCLUSIVE MODE',
        "exists:receipt",
        "filter:result",
        "exists:result",
    ]


@pytest.mark.django_db
def test_0010_result_receipt_version_constraint_exists() -> None:
    """The live schema enforces exact result/FK and receipt schema versions."""

    with connection.cursor() as cursor:
        result_constraints = connection.introspection.get_constraints(
            cursor,
            "portfolio_governed_optimization_result",
        )
        receipt_constraints = connection.introspection.get_constraints(
            cursor,
            "portfolio_governed_optimization_input_receipt",
        )

    assert "pf_opt_result_receipt_ver_ck" in result_constraints
    assert "pf_opt_receipt_version_ck" in receipt_constraints


def _receipt_values(*, suffix: str) -> dict[str, object]:
    created_at = datetime(2026, 8, 5, 8, tzinfo=UTC)
    return {
        "receipt_id": suffix * 64,
        "receipt_version": "governed-optimization-input-receipt.v1",
        "owner": "portfolio",
        "input_set_id": f"input-set:{suffix}",
        "input_set_version": "input-set.v1",
        "contract_version": "optimization-contract.v1",
        "input_set_hash": suffix.upper() * 64,
        "portfolio_snapshot_id": f"snapshot:{suffix}",
        "portfolio_snapshot_hash": "1" * 64,
        "universe_hash": "2" * 64,
        "evidence_graph_hash": "3" * 64,
        "pit_manifest_set_hash": "4" * 64,
        "created_at": created_at,
        "recorded_at": created_at + timedelta(minutes=1),
        "valid_until": created_at + timedelta(days=1),
        "payload_count": 13,
        "owner_binding_count": 13,
        "promotion_count": 3,
        "canonical_payload": {"schema_version": "input-receipt.v1"},
        "content_hash": "5" * 63 + suffix,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def _result_values(
    *,
    result_id: str,
    result_version: str,
    input_receipt_id: str | None,
) -> dict[str, object]:
    evaluated_at = datetime(2026, 8, 5, 9, tzinfo=UTC)
    return {
        "result_id": result_id,
        "input_receipt_id": input_receipt_id,
        "result_version": result_version,
        "run_key": f"run:{result_id}",
        "run_version": "run.v1",
        "assembly_hash": "6" * 64,
        "problem_id": f"problem:{result_id}",
        "problem_hash": "7" * 64,
        "input_set_id": f"input-set:{result_id}",
        "input_set_hash": "8" * 64,
        "status": "blocked",
        "selected_candidate": "",
        "candidates": [],
        "problem_blockers": [["migration", "research_only"]],
        "evaluated_at": evaluated_at,
        "valid_until": evaluated_at + timedelta(days=1),
        "content_hash": (result_id[-1] if result_id[-1].isalnum() else "9") * 64,
        "canonical_payload": {"schema_version": result_version},
        "research_only": True,
        "must_not_execute": True,
        "must_not_use_for_decision": True,
    }


@pytest.mark.django_db(transaction=True)
def test_0010_accepts_only_exact_v1_or_v2_shapes_and_round_trips_data() -> None:
    """Valid legacy/canonical rows survive 0009 -> 0010 -> 0009 -> 0010."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    migration_0009 = [("portfolio", "0009_governed_optimization_input_receipt")]
    migration_0010 = [("portfolio", "0010_governed_optimization_receipt_constraint")]
    try:
        executor.migrate(migration_0009)
        apps_0009 = executor.loader.project_state(migration_0009).apps
        Receipt0009 = apps_0009.get_model(
            "portfolio",
            "GovernedOptimizationInputReceiptModel",
        )
        Result0009 = apps_0009.get_model(
            "portfolio",
            "GovernedOptimizationResearchResultModel",
        )
        receipt = Receipt0009.objects.create(**_receipt_values(suffix="a"))
        Result0009.objects.create(
            **_result_values(
                result_id="migration-roundtrip-v1",
                result_version=LEGACY_RESULT_VERSION,
                input_receipt_id=None,
            )
        )
        Result0009.objects.create(
            **_result_values(
                result_id="migration-roundtrip-v2",
                result_version=CANONICAL_RESULT_VERSION,
                input_receipt_id=receipt.receipt_id,
            )
        )

        executor = MigrationExecutor(connection)
        executor.migrate(migration_0010)
        apps_0010 = executor.loader.project_state(migration_0010).apps
        Result0010 = apps_0010.get_model(
            "portfolio",
            "GovernedOptimizationResearchResultModel",
        )
        assert set(Result0010.objects.values_list("result_version", "input_receipt_id")) == {
            (LEGACY_RESULT_VERSION, None),
            (CANONICAL_RESULT_VERSION, receipt.receipt_id),
        }

        invalid_shapes = (
            ("migration-unknown-u", "unknown-result.v9", None),
            ("migration-blank-b", "", None),
            ("migration-null-v2-n", CANONICAL_RESULT_VERSION, None),
            ("migration-alias-v1-r", LEGACY_RESULT_VERSION, receipt.receipt_id),
        )
        for result_id, result_version, receipt_id in invalid_shapes:
            with pytest.raises(IntegrityError), transaction.atomic():
                Result0010.objects.create(
                    **_result_values(
                        result_id=result_id,
                        result_version=result_version,
                        input_receipt_id=receipt_id,
                    )
                )

        executor = MigrationExecutor(connection)
        executor.migrate(migration_0009)
        apps_after_reverse = executor.loader.project_state(migration_0009).apps
        ReverseReceipt = apps_after_reverse.get_model(
            "portfolio",
            "GovernedOptimizationInputReceiptModel",
        )
        ReverseResult = apps_after_reverse.get_model(
            "portfolio",
            "GovernedOptimizationResearchResultModel",
        )
        assert ReverseReceipt.objects.filter(receipt_id=receipt.receipt_id).exists()
        assert ReverseResult.objects.filter(result_id="migration-roundtrip-v1").exists()
        assert ReverseResult.objects.filter(result_id="migration-roundtrip-v2").exists()

        executor = MigrationExecutor(connection)
        executor.migrate(migration_0010)
        final_apps = executor.loader.project_state(migration_0010).apps
        FinalResult = final_apps.get_model(
            "portfolio",
            "GovernedOptimizationResearchResultModel",
        )
        assert FinalResult.objects.count() == 2
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db(transaction=True)
def test_0009_reverse_to_0008_preserves_real_legacy_result() -> None:
    """A true v1/null legacy row remains intact when the empty receipt schema is removed."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    migration_0008 = [("portfolio", "0008_r5_relative_value_outcome_ledger")]
    migration_0009 = [("portfolio", "0009_governed_optimization_input_receipt")]
    try:
        executor.migrate(migration_0009)
        apps_0009 = executor.loader.project_state(migration_0009).apps
        Result0009 = apps_0009.get_model(
            "portfolio",
            "GovernedOptimizationResearchResultModel",
        )
        Result0009.objects.create(
            **_result_values(
                result_id="migration-legacy-reverse-1",
                result_version=LEGACY_RESULT_VERSION,
                input_receipt_id=None,
            )
        )

        executor = MigrationExecutor(connection)
        executor.migrate(migration_0008)
        apps_0008 = executor.loader.project_state(migration_0008).apps
        Result0008 = apps_0008.get_model(
            "portfolio",
            "GovernedOptimizationResearchResultModel",
        )
        legacy = Result0008.objects.get(result_id="migration-legacy-reverse-1")
        assert legacy.result_version == LEGACY_RESULT_VERSION
        assert not hasattr(legacy, "input_receipt_id")
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db(transaction=True)
def test_0009_reverse_to_0008_refuses_v2_receipt_evidence_without_data_loss() -> None:
    """The reverse guard fires before either the receipt row or FK column is dropped."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    migration_0008 = [("portfolio", "0008_r5_relative_value_outcome_ledger")]
    migration_0009 = [("portfolio", "0009_governed_optimization_input_receipt")]
    try:
        executor.migrate(migration_0009)
        apps_0009 = executor.loader.project_state(migration_0009).apps
        Receipt0009 = apps_0009.get_model(
            "portfolio",
            "GovernedOptimizationInputReceiptModel",
        )
        Result0009 = apps_0009.get_model(
            "portfolio",
            "GovernedOptimizationResearchResultModel",
        )
        receipt = Receipt0009.objects.create(**_receipt_values(suffix="b"))
        Result0009.objects.create(
            **_result_values(
                result_id="migration-v2-reverse-2",
                result_version=CANONICAL_RESULT_VERSION,
                input_receipt_id=receipt.receipt_id,
            )
        )

        with pytest.raises(IrreversibleError, match="receipt evidence exists"):
            MigrationExecutor(connection).migrate(migration_0008)

        assert (
            "portfolio",
            "0009_governed_optimization_input_receipt",
        ) in MigrationRecorder(connection).applied_migrations()
        assert Receipt0009.objects.filter(receipt_id=receipt.receipt_id).exists()
        stored = Result0009.objects.get(result_id="migration-v2-reverse-2")
        assert stored.result_version == CANONICAL_RESULT_VERSION
        assert stored.input_receipt_id == receipt.receipt_id

        Result0009.objects.all().delete()
        Receipt0009.objects.all().delete()
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db(transaction=True)
def test_0010_invalid_version_failure_is_atomic_and_preserves_0009_state() -> None:
    """An unknown historical version blocks 0010 without losing its source row."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    migration_0009 = [("portfolio", "0009_governed_optimization_input_receipt")]
    migration_0010 = [("portfolio", "0010_governed_optimization_receipt_constraint")]
    try:
        executor.migrate(migration_0009)
        apps_0009 = executor.loader.project_state(migration_0009).apps
        Result0009 = apps_0009.get_model(
            "portfolio",
            "GovernedOptimizationResearchResultModel",
        )
        Result0009.objects.create(
            **_result_values(
                result_id="migration-invalid-version-z",
                result_version="unknown-result.v9",
                input_receipt_id=None,
            )
        )

        with pytest.raises(IntegrityError):
            MigrationExecutor(connection).migrate(migration_0010)

        applied = MigrationRecorder(connection).applied_migrations()
        assert ("portfolio", "0009_governed_optimization_input_receipt") in applied
        assert ("portfolio", "0010_governed_optimization_receipt_constraint") not in applied
        preserved = Result0009.objects.get(result_id="migration-invalid-version-z")
        assert preserved.result_version == "unknown-result.v9"
        assert preserved.input_receipt_id is None

        Result0009.objects.all().delete()
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db(transaction=True)
def test_0010_invalid_receipt_version_failure_is_atomic() -> None:
    """An unknown receipt schema rolls back both 0010 constraints and its recorder row."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    migration_0009 = [("portfolio", "0009_governed_optimization_input_receipt")]
    migration_0010 = [("portfolio", "0010_governed_optimization_receipt_constraint")]
    try:
        executor.migrate(migration_0009)
        apps_0009 = executor.loader.project_state(migration_0009).apps
        Receipt0009 = apps_0009.get_model(
            "portfolio",
            "GovernedOptimizationInputReceiptModel",
        )
        values = _receipt_values(suffix="c")
        values["receipt_version"] = "unknown-input-receipt.v9"
        Receipt0009.objects.create(**values)

        with pytest.raises(IntegrityError):
            MigrationExecutor(connection).migrate(migration_0010)

        applied = MigrationRecorder(connection).applied_migrations()
        assert ("portfolio", "0009_governed_optimization_input_receipt") in applied
        assert ("portfolio", "0010_governed_optimization_receipt_constraint") not in applied
        preserved = Receipt0009.objects.get(receipt_id="c" * 64)
        assert preserved.receipt_version == "unknown-input-receipt.v9"
        with connection.cursor() as cursor:
            result_constraints = connection.introspection.get_constraints(
                cursor,
                "portfolio_governed_optimization_result",
            )
            receipt_constraints = connection.introspection.get_constraints(
                cursor,
                "portfolio_governed_optimization_input_receipt",
            )
        assert "pf_opt_result_receipt_ver_ck" not in result_constraints
        assert "pf_opt_receipt_version_ck" not in receipt_constraints

        Receipt0009.objects.all().delete()
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db(transaction=True)
def test_0011_monitoring_ledgers_are_schema_only_reversible_and_match_models() -> None:
    """0011 creates only its three constrained empty ledgers and reverses cleanly."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    migration_0010 = [("portfolio", "0010_governed_optimization_receipt_constraint")]
    migration_0011 = [("portfolio", "0011_governed_optimization_monitoring_ledgers")]
    table_names = {
        "portfolio_governed_optimization_monitoring_observation",
        "portfolio_governed_optimization_monitoring_assessment",
        "portfolio_governed_optimization_monitoring_audit_snapshot",
    }
    try:
        executor.migrate(migration_0010)
        with connection.cursor() as cursor:
            assert table_names.isdisjoint(connection.introspection.table_names(cursor))

        executor = MigrationExecutor(connection)
        executor.migrate(migration_0011)
        apps_0011 = executor.loader.project_state(migration_0011).apps
        historical_models = (
            apps_0011.get_model(
                "portfolio",
                "GovernedOptimizationMonitoringObservationModel",
            ),
            apps_0011.get_model(
                "portfolio",
                "GovernedOptimizationMonitoringAssessmentModel",
            ),
            apps_0011.get_model(
                "portfolio",
                "GovernedOptimizationMonitoringAuditSnapshotModel",
            ),
        )
        assert all(
            model._default_manager.using(connection.alias).count() == 0
            for model in historical_models
        )
        with connection.cursor() as cursor:
            assert table_names.issubset(connection.introspection.table_names(cursor))
            observation_constraints = connection.introspection.get_constraints(
                cursor,
                "portfolio_governed_optimization_monitoring_observation",
            )
        assert observation_constraints["pf_opt_mon_obs_period_uq"]["unique"] is True
        assert observation_constraints["pf_opt_mon_obs_period_uq"]["columns"] == [
            "assessment_id",
            "period_id",
        ]
        assert "pf_opt_mon_obs_ident_uq" not in observation_constraints
        historical_observation = historical_models[0]
        assert historical_observation._meta.get_field("content_hash").unique is False
        assert historical_observation._meta.get_field("domain_observation_hash").max_length == 64

        from apps.portfolio.infrastructure.governed_optimization_monitoring_models import (
            GovernedOptimizationMonitoringAssessmentModel,
            GovernedOptimizationMonitoringAuditSnapshotModel,
            GovernedOptimizationMonitoringObservationModel,
        )

        live_models = (
            GovernedOptimizationMonitoringObservationModel,
            GovernedOptimizationMonitoringAssessmentModel,
            GovernedOptimizationMonitoringAuditSnapshotModel,
        )
        assert [
            {constraint.name for constraint in model._meta.constraints}
            for model in historical_models
        ] == [{constraint.name for constraint in model._meta.constraints} for model in live_models]

        MigrationExecutor(connection).migrate(migration_0010)
        with connection.cursor() as cursor:
            assert table_names.isdisjoint(connection.introspection.table_names(cursor))

        MigrationExecutor(connection).migrate(migration_0011)
        apps_reforward = MigrationExecutor(connection).loader.project_state(migration_0011).apps
        assert all(
            apps_reforward.get_model("portfolio", model._meta.object_name)
            ._default_manager.using(connection.alias)
            .count()
            == 0
            for model in historical_models
        )
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
