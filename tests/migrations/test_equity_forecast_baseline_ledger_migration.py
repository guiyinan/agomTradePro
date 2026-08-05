"""Migration evidence for the schema-only R1 forecast-baseline ledgers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor


def _raw_rows(table: str) -> list[tuple[object, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT * FROM "{table}" ORDER BY 1')
        return list(cursor.fetchall())


def _seed_0012_legacy_rows(apps: object) -> None:
    Forecast = apps.get_model("equity", "OperatingForecastVersionModel")
    Evaluation = apps.get_model("equity", "OperatingForecastEvaluationModel")
    recipes = (
        ("0010", 1, "legacy_unverified", "v1_0010_untyped", "verified"),
        ("0011", 1, "legacy_unverified", "v1_0011_typed", "verified"),
        ("0012", 2, "template_bound", "not_applicable", "not_applicable"),
    )
    for index, (suffix, schema, lineage, recipe, hash_status) in enumerate(recipes, start=1):
        forecast = Forecast._default_manager.create(
            forecast_id=f"legacy-preserve-{suffix}",
            forecast_key=f"000001.SZ-preserve-{suffix}",
            forecast_version=index,
            subject_code="000001.SZ",
            industry_code="consumer-service",
            as_of_time=datetime(2026, 4, index, 8, 7, 6, 500000, tzinfo=UTC),
            target_period_end=date(2026, 6, 30),
            horizon_quarters=1,
            methodology_ref=f"legacy-method-{suffix}",
            created_by_ref="analyst-7",
            evidence_schema_version=schema,
            source_lineage_status=lineage,
            legacy_hash_recipe=recipe,
            legacy_hash_status=hash_status,
            template_code="consumer-template" if schema == 2 else "",
            template_version=1 if schema == 2 else None,
            template_content_hash=("a" * 64 if schema == 2 else ""),
            template_run_key=(f"run-preserve-{suffix}" if schema == 2 else ""),
            template_run_version=1 if schema == 2 else None,
            template_run_content_hash=("b" * 64 if schema == 2 else ""),
            valuation_consumable=schema != 2,
            promotion_decision_id=(f"legacy-promotion-{suffix}" if schema != 2 else ""),
            content_hash=str(index) * 64,
        )
        Evaluation._default_manager.create(
            forecast=forecast,
            subject_code="000001.SZ",
            scenario="base",
            actual_period_end=date(2026, 6, 30),
            recorded_at=datetime(2026, 7, index, 9, 8, 7, 654321, tzinfo=UTC),
            actual_fact_evidence=[
                {
                    "fact_id": f"fact-{suffix}",
                    "hash": f"hash-{suffix}",
                    "nested": {"revision": index, "public": True},
                }
            ],
            forecast_revenue=Decimal("100.000000000001"),
            forecast_net_profit=Decimal("10.000000000001"),
            forecast_profit_margin_percent=Decimal("10.000000000001"),
            actual_revenue=Decimal("101.000000000001"),
            actual_net_profit=Decimal("11.000000000001"),
            actual_profit_margin_percent=Decimal("10.891089108911"),
            currency_unit="CNY_million",
            revenue_error=Decimal("-1.000000000000"),
            revenue_absolute_error=Decimal("1.000000000000"),
            revenue_absolute_percentage_error=Decimal("0.009900990099"),
            net_profit_error=Decimal("-1.000000000000"),
            net_profit_absolute_error=Decimal("1.000000000000"),
            net_profit_absolute_percentage_error=Decimal("0.090909090909"),
            profit_margin_error=Decimal("-0.891089108910"),
            profit_margin_absolute_error=Decimal("0.891089108910"),
            content_hash=chr(99 + index) * 64,
        )


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_0013_preserves_every_0012_legacy_header_json_hash_and_timestamp_byte() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("equity", "0012_industry_template_forecast_bridge")])
        old_apps = executor.loader.project_state(
            [("equity", "0012_industry_template_forecast_bridge")]
        ).apps
        _seed_0012_legacy_rows(old_apps)
        tables = (
            "equity_operating_forecast_version",
            "equity_operating_forecast_evaluation",
        )
        before = {table: _raw_rows(table) for table in tables}

        executor = MigrationExecutor(connection)
        executor.migrate([("equity", "0013_forecast_baseline_ledgers")])
        after = {table: _raw_rows(table) for table in tables}
        assert after == before
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_0013_has_zero_seed_four_tables_and_research_time_constraints() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("equity", "0012_industry_template_forecast_bridge")])
        old_apps = executor.loader.project_state(
            [("equity", "0012_industry_template_forecast_bridge")]
        ).apps
        for model_name in (
            "ForecastBaselineApprovalEvidenceModel",
            "ForecastBaselineSpecModel",
            "ForecastBaselineArtifactModel",
            "ForecastBaselineTrialResultModel",
        ):
            with pytest.raises(LookupError):
                old_apps.get_model("equity", model_name)

        executor = MigrationExecutor(connection)
        executor.migrate([("equity", "0013_forecast_baseline_ledgers")])
        apps = executor.loader.project_state([("equity", "0013_forecast_baseline_ledgers")]).apps
        Approval = apps.get_model("equity", "ForecastBaselineApprovalEvidenceModel")
        Spec = apps.get_model("equity", "ForecastBaselineSpecModel")
        Artifact = apps.get_model("equity", "ForecastBaselineArtifactModel")
        Trial = apps.get_model("equity", "ForecastBaselineTrialResultModel")
        assert [Approval._default_manager.count(), Spec._default_manager.count()] == [0, 0]
        assert [Artifact._default_manager.count(), Trial._default_manager.count()] == [0, 0]
        assert {
            Approval._meta.db_table,
            Spec._meta.db_table,
            Artifact._meta.db_table,
            Trial._meta.db_table,
        }.issubset(set(connection.introspection.table_names()))

        approved_at = datetime(2026, 8, 1, 9, tzinfo=UTC)
        recorded_at = datetime(2026, 8, 2, 9, tzinfo=UTC)
        origin = datetime(2026, 9, 1, 9, tzinfo=UTC)
        valid_until = datetime(2027, 1, 1, 9, tzinfo=UTC)
        approval = Approval._default_manager.create(
            approval_id="approval:migration",
            approval_version="v1",
            content_hash="a" * 64,
            owner="equity",
            status="approved",
            forecast_origin_at=origin,
            approved_at=approved_at,
            valid_until=valid_until,
            payload_schema="approval.v1",
            canonical_payload={"schema": "approval.v1"},
            research_only=True,
            must_not_use_for_decision=True,
            must_not_execute=True,
            recorded_at=recorded_at,
        )
        spec = Spec._default_manager.create(
            approval=approval,
            spec_id="spec:migration",
            spec_version="v1",
            content_hash="b" * 64,
            owner="equity",
            approval_evidence_id="approval:migration",
            approval_evidence_version="v1",
            approval_evidence_content_hash="a" * 64,
            approval_recorded_at=recorded_at,
            forecast_origin_at=origin,
            approved_at=approved_at,
            valid_until=valid_until,
            payload_schema="spec.v1",
            canonical_payload={"schema": "spec.v1"},
            research_only=True,
            must_not_use_for_decision=True,
            must_not_execute=True,
        )
        artifact = Artifact._default_manager.create(
            spec=spec,
            artifact_id="artifact:migration",
            artifact_version="v1",
            content_hash="c" * 64,
            owner="equity",
            spec_evidence_id="spec:migration",
            spec_evidence_version="v1",
            spec_evidence_content_hash="b" * 64,
            knowledge_as_of=origin,
            produced_at=origin,
            valid_until=valid_until,
            payload_schema="artifact.v1",
            canonical_payload={"schema": "artifact.v1"},
            research_only=True,
            must_not_use_for_decision=True,
            must_not_execute=True,
        )
        trial = Trial._default_manager.create(
            spec=spec,
            artifact=artifact,
            result_id="trial:migration",
            result_version="v1",
            content_hash="d" * 64,
            owner="equity",
            spec_evidence_id="spec:migration",
            spec_evidence_version="v1",
            spec_evidence_content_hash="b" * 64,
            artifact_evidence_id="artifact:migration",
            artifact_evidence_version="v1",
            artifact_evidence_content_hash="c" * 64,
            actual_manifest_id="actual:migration",
            actual_manifest_version="v1",
            actual_manifest_content_hash="e" * 64,
            research_trial_id="research:migration",
            research_trial_version="v1",
            research_trial_content_hash="f" * 64,
            evaluated_at=datetime(2026, 10, 1, 9, tzinfo=UTC),
            valid_until=valid_until,
            payload_schema="trial.v1",
            canonical_payload={"schema": "trial.v1"},
            research_only=True,
            must_not_use_for_decision=True,
            must_not_execute=True,
        )

        for model, kwargs in (
            (
                Approval,
                {
                    "approval_id": "approval:late",
                    "approval_version": "v1",
                    "content_hash": "1" * 64,
                    "owner": "equity",
                    "status": "approved",
                    "forecast_origin_at": origin,
                    "approved_at": approved_at,
                    "valid_until": valid_until,
                    "payload_schema": "approval.v1",
                    "canonical_payload": {"schema": "approval.v1"},
                    "research_only": True,
                    "must_not_use_for_decision": True,
                    "must_not_execute": True,
                    "recorded_at": origin.replace(day=2),
                },
            ),
            (
                Spec,
                {
                    "approval": approval,
                    "spec_id": "spec:unsafe",
                    "spec_version": "v1",
                    "content_hash": "2" * 64,
                    "owner": "equity",
                    "approval_evidence_id": "approval:migration",
                    "approval_evidence_version": "v1",
                    "approval_evidence_content_hash": "a" * 64,
                    "approval_recorded_at": recorded_at,
                    "forecast_origin_at": origin,
                    "approved_at": approved_at,
                    "valid_until": valid_until,
                    "payload_schema": "spec.v1",
                    "canonical_payload": {"schema": "spec.v1"},
                    "research_only": False,
                    "must_not_use_for_decision": True,
                    "must_not_execute": True,
                },
            ),
        ):
            with pytest.raises(IntegrityError):
                with transaction.atomic():
                    model._default_manager.create(**kwargs)
        for model, source, id_field, version_field, digest in (
            (Artifact, artifact, "artifact_id", "artifact_version", "3" * 64),
            (Trial, trial, "result_id", "result_version", "4" * 64),
        ):
            unsafe = {
                field.attname: getattr(source, field.attname)
                for field in model._meta.concrete_fields
                if not field.primary_key
            }
            unsafe[id_field] = f"{unsafe[id_field]}:unsafe"
            unsafe[version_field] = f"{unsafe[version_field]}:unsafe"
            unsafe["content_hash"] = digest
            unsafe["research_only"] = False
            with pytest.raises(IntegrityError):
                with transaction.atomic():
                    model._default_manager.create(**unsafe)
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
