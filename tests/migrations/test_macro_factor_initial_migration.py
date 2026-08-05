"""Migration coverage for the append-only R3 macro-factor result table."""

from datetime import UTC, datetime

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_macro_factor_initial_migration_creates_fail_closed_constraints() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("macro_factor", None)])
        executor = MigrationExecutor(connection)
        executor.migrate([("macro_factor", "0001_initial")])
        apps = executor.loader.project_state([("macro_factor", "0001_initial")]).apps
        Result = apps.get_model("macro_factor", "MacroFactorResearchResultModel")

        valid = {
            "result_id": "migration-r3-v1",
            "factor_version": "macro-growth-v1",
            "target_code": "growth_nowcast_1m",
            "evidence_produced_at": datetime(2026, 7, 2, tzinfo=UTC),
            "pit_manifest_id": "pit-r3-growth-v1",
            "pit_manifest_hash": "a" * 64,
            "code_version": "git:0123456789abcdef",
            "parameter_version": "macro-growth-params-v1",
            "external_evidence_id": "external-lasso-selection-v1",
            "lifecycle_status": "research_only",
            "content_hash": "b" * 64,
            "payload": {"factor_version": "macro-growth-v1"},
            "research_only": True,
            "must_not_use_for_decision": True,
        }
        Result._default_manager.create(**valid)

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Result._default_manager.create(
                    **{
                        **valid,
                        "result_id": "migration-r3-invalid",
                        "factor_version": "macro-growth-v2",
                        "research_only": False,
                    }
                )
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
