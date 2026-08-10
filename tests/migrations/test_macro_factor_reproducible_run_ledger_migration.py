"""Migration coverage for the schema-only reproducible R3 run ledger."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import ProtectedError


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_0003_creates_reversible_zero_seed_lifecycle_stream_commit_ledger() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("macro_factor", "0002_reproducible_run_ledger")])
        executor = MigrationExecutor(connection)
        executor.migrate([("macro_factor", "0003_lifecycle_stream_commit_anchor")])
        apps = executor.loader.project_state(
            [("macro_factor", "0003_lifecycle_stream_commit_anchor")]
        ).apps
        Commit = apps.get_model("macro_factor", "MacroFactorLifecycleStreamCommitModel")
        Head = apps.get_model("macro_factor", "MacroFactorLifecycleStreamHeadModel")

        assert Commit._default_manager.count() == 0
        assert Head._default_manager.count() == 0
        assert "macro_factor_lifecycle_stream_commit" in connection.introspection.table_names()
        assert "macro_factor_lifecycle_stream_head" in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate([("macro_factor", "0002_reproducible_run_ledger")])
        assert "macro_factor_lifecycle_stream_commit" not in connection.introspection.table_names()
        assert "macro_factor_lifecycle_stream_head" not in connection.introspection.table_names()

        executor = MigrationExecutor(connection)
        executor.migrate([("macro_factor", "0003_lifecycle_stream_commit_anchor")])
        apps = executor.loader.project_state(
            [("macro_factor", "0003_lifecycle_stream_commit_anchor")]
        ).apps
        Commit = apps.get_model("macro_factor", "MacroFactorLifecycleStreamCommitModel")
        Head = apps.get_model("macro_factor", "MacroFactorLifecycleStreamHeadModel")
        assert Commit._default_manager.count() == 0
        assert Head._default_manager.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_0002_preserves_legacy_and_creates_empty_fail_closed_protected_ledger() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("macro_factor", "0001_initial")])
        old_apps = executor.loader.project_state([("macro_factor", "0001_initial")]).apps
        LegacyResult = old_apps.get_model("macro_factor", "MacroFactorResearchResultModel")
        produced_at = datetime(2026, 7, 2, 10, tzinfo=UTC)
        legacy_payload = {
            "factor_version": "legacy-macro-growth-v1",
            "legacy_marker": ["preserve", 1],
        }
        legacy = LegacyResult._default_manager.create(
            result_id="legacy-r3-result-v1",
            factor_version="legacy-macro-growth-v1",
            target_code="legacy_growth_target",
            evidence_produced_at=produced_at,
            pit_manifest_id="legacy-pit-v1",
            pit_manifest_hash="a" * 64,
            code_version="git:legacy012345",
            parameter_version="legacy-params-v1",
            external_evidence_id="legacy-external-v1",
            lifecycle_status="research_only",
            content_hash="b" * 64,
            payload=legacy_payload,
            research_only=True,
            must_not_use_for_decision=True,
        )
        legacy_created_at = legacy.created_at

        executor = MigrationExecutor(connection)
        executor.migrate([("macro_factor", "0002_reproducible_run_ledger")])
        apps = executor.loader.project_state(
            [("macro_factor", "0002_reproducible_run_ledger")]
        ).apps
        Result = apps.get_model("macro_factor", "MacroFactorResearchResultModel")
        Artifact = apps.get_model("macro_factor", "MacroFactorRunArtifactModel")
        Output = apps.get_model("macro_factor", "MacroFactorDatedOutputModel")
        Event = apps.get_model("macro_factor", "MacroFactorLifecycleEventModel")

        preserved = Result._default_manager.get(result_id="legacy-r3-result-v1")
        assert preserved.factor_version == "legacy-macro-growth-v1"
        assert preserved.content_hash == "b" * 64
        assert preserved.payload == legacy_payload
        assert preserved.lifecycle_status == "research_only"
        assert preserved.created_at == legacy_created_at
        assert Artifact._default_manager.count() == 0
        assert Output._default_manager.count() == 0
        assert Event._default_manager.count() == 0

        artifact_values = {
            "artifact_id": "1" * 64,
            "run_key": "migration-r3-run",
            "run_version": 1,
            "factor_version": preserved.factor_version,
            "target_code": preserved.target_code,
            "output_role": "forward_expectation",
            "produced_at": produced_at,
            "source_result": preserved,
            "source_result_hash": preserved.content_hash,
            "external_evidence_id": "external-runner-v1",
            "external_producer_ref": "approved-runner:migration",
            "external_artifact_hash": "2" * 64,
            "external_artifact_media_type": ("application/vnd.agom.macro-factor.nested-cv+json"),
            "external_artifact_content_length": 2,
            "external_artifact_bytes": b"{}",
            "request_hash": "3" * 64,
            "pit_manifest_id": "pit-r3-v1",
            "pit_manifest_hash": "4" * 64,
            "dataset_hash": "5" * 64,
            "benchmark_version": "mean-v1",
            "benchmark_hash": "6" * 64,
            "fixed_fmp_version": "fmp-v1",
            "fixed_fmp_hash": "7" * 64,
            "cost_model_version": "cost-v1",
            "cost_model_hash": "8" * 64,
            "split_contract_version": "split-v1",
            "split_contract_hash": "9" * 64,
            "plan_hash": "a" * 64,
            "selection_protocol_version": "selection-v1",
            "selection_protocol_hash": "b" * 64,
            "metrics_protocol_version": "metrics-v1",
            "metrics_protocol_hash": "c" * 64,
            "timing_policy_version": "timing-v1",
            "timing_policy_hash": "d" * 64,
            "code_version": "git:migration123",
            "dependency_lock_hash": "e" * 64,
            "parameter_version": "params-v1",
            "parameter_hash": "f" * 64,
            "random_seed": 1729,
            "content_hash": "0" * 64,
            "payload": {"schema": "migration-only"},
            "research_only": True,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }
        artifact = Artifact._default_manager.create(**artifact_values)

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Artifact._default_manager.create(
                    **{
                        **artifact_values,
                        "artifact_id": "2" * 64,
                        "run_key": "invalid-flags",
                        "request_hash": "1" * 64,
                        "content_hash": "3" * 64,
                        "must_not_execute": False,
                    }
                )

        output_values = {
            "output_id": "4" * 64,
            "artifact": artifact,
            "artifact_hash": artifact.content_hash,
            "factor_version": artifact.factor_version,
            "target_code": artifact.target_code,
            "output_role": "forward_expectation",
            "observation_date": date(2026, 6, 30),
            "target_period_start": date(2026, 8, 1),
            "target_period_end": date(2026, 8, 31),
            "horizon_periods": 1,
            "horizon_unit": "month",
            "knowledge_as_of": produced_at - timedelta(days=1),
            "produced_at": produced_at,
            "valid_until": produced_at + timedelta(days=7),
            "value": Decimal("0.42"),
            "unit": "index",
            "pit_manifest_id": artifact.pit_manifest_id,
            "pit_manifest_hash": artifact.pit_manifest_hash,
            "content_hash": "5" * 64,
            "payload": {"schema": "migration-only"},
            "research_only": True,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }
        Output._default_manager.create(**output_values)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Output._default_manager.create(
                    **{
                        **output_values,
                        "output_id": "6" * 64,
                        "content_hash": "7" * 64,
                        "output_role": "current_state",
                        "horizon_periods": 1,
                    }
                )

        event_values = {
            "event_id": "migration-recorded-v1",
            "artifact": artifact,
            "artifact_hash": artifact.content_hash,
            "factor_version": artifact.factor_version,
            "event_type": "recorded",
            "sequence": 1,
            "occurred_at": produced_at,
            "recorded_at": produced_at,
            "policy_version": "retirement-v1",
            "policy_hash": "8" * 64,
            "reason_codes": ["run_recorded"],
            "evidence_hash": artifact.content_hash,
            "previous_event_hash": None,
            "owner_attestation_issued_at": None,
            "content_hash": "9" * 64,
            "payload": {"schema": "migration-only"},
            "research_only": True,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }
        Event._default_manager.create(**event_values)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Event._default_manager.create(
                    **{
                        **event_values,
                        "event_id": "migration-invalid-root",
                        "event_type": "retired",
                        "content_hash": "a" * 64,
                    }
                )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Event._default_manager.create(
                    **{
                        **event_values,
                        "event_id": "migration-retired-before-attestation",
                        "event_type": "retired",
                        "sequence": 2,
                        "occurred_at": produced_at + timedelta(days=1),
                        "recorded_at": produced_at + timedelta(days=2),
                        "previous_event_hash": event_values["content_hash"],
                        "owner_attestation_id": "owner-attestation-v1",
                        "owner_attestation_hash": "b" * 64,
                        "owner_attestation_owner_ref": "research-risk-owner",
                        "owner_attestation_media_type": "application/json",
                        "owner_attestation_content_length": 2,
                        "owner_attestation_issued_at": produced_at,
                        "owner_attestation_bytes": b"{}",
                        "content_hash": "c" * 64,
                    }
                )

        with pytest.raises(ProtectedError):
            preserved.delete()
        with pytest.raises(ProtectedError):
            artifact.delete()
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
