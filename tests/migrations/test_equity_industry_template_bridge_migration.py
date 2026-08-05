"""Migration coverage for schema-versioned R1 forecast evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.equity.domain.operating_forecast import (
    LegacyOperatingForecastVersion,
    OperatingForecastLegacyHashRecipe,
    OperatingForecastLegacyHashStatus,
    OperatingForecastSourceLineageStatus,
)
from apps.equity.infrastructure.operating_forecast_repository import (
    DjangoOperatingForecastRepository,
)


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _legacy_hash(apps: Any, forecast_id: str, *, include_role: bool) -> str:
    Forecast = apps.get_model("equity", "OperatingForecastVersionModel")
    Fact = apps.get_model("equity", "OperatingForecastFactReferenceModel")
    Assumption = apps.get_model("equity", "OperatingForecastAssumptionModel")
    Projection = apps.get_model("equity", "OperatingForecastProjectionModel")
    Sensitivity = apps.get_model("equity", "OperatingForecastSensitivityModel")
    forecast = Forecast._default_manager.get(pk=forecast_id)
    assumptions: list[dict[str, object]] = []
    for row in Assumption._default_manager.filter(forecast_id=forecast_id).order_by(
        "scenario", "assumption_key"
    ):
        payload: dict[str, object] = {
            "scenario": row.scenario,
            "assumption_key": row.assumption_key,
            "value": _decimal_text(row.value),
            "unit": row.unit,
            "input_kind": row.input_kind,
            "rationale": row.rationale,
            "lineage_ref": f"data_center_pit_fact:{row.observed_fact_version_id}",
        }
        if include_role:
            payload["observed_metric_role"] = row.observed_metric_role or None
        assumptions.append(payload)
    projections: list[dict[str, object]] = []
    for row in Projection._default_manager.filter(forecast_id=forecast_id).order_by("scenario"):
        projections.append(
            {
                "scenario": row.scenario,
                "revenue": _decimal_text(row.revenue),
                "net_profit": _decimal_text(row.net_profit),
                "profit_margin_percent": _decimal_text(row.profit_margin_percent),
                "currency_unit": row.currency_unit,
                "sensitivities": [
                    {
                        "sensitivity_key": point.sensitivity_key,
                        "input_value": _decimal_text(point.input_value),
                        "input_unit": point.input_unit,
                        "output_value": _decimal_text(point.output_value),
                        "output_unit": point.output_unit,
                        "method_version": point.method_version,
                    }
                    for point in Sensitivity._default_manager.filter(projection_id=row.pk).order_by(
                        "sensitivity_key"
                    )
                ],
            }
        )
    payload = {
        "forecast_id": forecast.forecast_id,
        "forecast_key": forecast.forecast_key,
        "forecast_version": forecast.forecast_version,
        "subject_code": forecast.subject_code,
        "industry_code": forecast.industry_code,
        "as_of_time": forecast.as_of_time.astimezone(UTC).isoformat(),
        "target_period_end": forecast.target_period_end.isoformat(),
        "horizon_quarters": forecast.horizon_quarters,
        "methodology_ref": forecast.methodology_ref,
        "created_by_ref": forecast.created_by_ref,
        "valuation_consumable": forecast.valuation_consumable,
        "promotion_decision_id": forecast.promotion_decision_id,
        "facts": [
            {
                "version_id": row.pit_fact_version_id,
                "dataset": row.dataset,
                "business_key": row.business_key,
                "metric_code": row.metric_code,
                "subject_type": row.subject_type,
                "subject_code": row.subject_code,
                "effective_at": row.effective_at.astimezone(UTC).isoformat(),
                "available_at": row.available_at.astimezone(UTC).isoformat(),
                "source_record_id": row.source_record_id,
                "content_hash": row.pit_content_hash,
                "value": _decimal_text(row.value),
                "unit": row.unit,
            }
            for row in Fact._default_manager.filter(forecast_id=forecast_id).order_by(
                "pit_fact_version_id"
            )
        ],
        "assumptions": assumptions,
        "projections": projections,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _seed_legacy(
    apps: Any,
    *,
    suffix: str,
    include_role: bool,
    metric_code: str,
    fact_value: str = "100",
    assumption_value: str = "100",
    fact_unit: str = "count",
    assumption_unit: str = "count",
    fact_subject_code: str = "000001.SZ",
    include_fact: bool = True,
    corrupt_hash: bool = False,
) -> str:
    Forecast = apps.get_model("equity", "OperatingForecastVersionModel")
    Fact = apps.get_model("equity", "OperatingForecastFactReferenceModel")
    Assumption = apps.get_model("equity", "OperatingForecastAssumptionModel")
    Projection = apps.get_model("equity", "OperatingForecastProjectionModel")
    Sensitivity = apps.get_model("equity", "OperatingForecastSensitivityModel")
    forecast_id = f"legacy-{suffix}"
    forecast = Forecast._default_manager.create(
        forecast_id=forecast_id,
        forecast_key=f"000001.SZ-{suffix}",
        forecast_version=1,
        subject_code="000001.SZ",
        industry_code="consumer-service",
        as_of_time=datetime(2026, 4, 30, 8, tzinfo=UTC),
        target_period_end=date(2026, 6, 30),
        horizon_quarters=1,
        methodology_ref="legacy-research-note-v1",
        created_by_ref="analyst-7",
        valuation_consumable=True,
        promotion_decision_id=f"legacy-promotion-{suffix}",
        content_hash="0" * 64,
    )
    fact_version_id = 1000 + sum(ord(character) for character in suffix)
    if include_fact:
        Fact._default_manager.create(
            forecast=forecast,
            pit_fact_version_id=fact_version_id,
            dataset="research.operating_observation.v1",
            business_key=f"{metric_code}|{suffix}",
            metric_code=metric_code,
            subject_type="company",
            subject_code=fact_subject_code,
            effective_at=datetime(2026, 3, 31, tzinfo=UTC),
            available_at=datetime(2026, 4, 20, tzinfo=UTC),
            source_record_id=f"source-{suffix}",
            pit_content_hash=(suffix.encode().hex().ljust(64, "0")[:64]),
            value=Decimal(fact_value),
            unit=fact_unit,
        )
    for scenario in ("base", "bull", "bear"):
        kwargs: dict[str, object] = {}
        if include_role:
            kwargs["observed_metric_role"] = metric_code
        Assumption._default_manager.create(
            forecast=forecast,
            scenario=scenario,
            assumption_key="operating_driver",
            value=Decimal(assumption_value),
            unit=assumption_unit,
            input_kind="observed_fact",
            rationale="historical immutable input",
            observed_fact_version_id=fact_version_id,
            human_assumption_ref="",
            model_version="",
            **kwargs,
        )
        projection = Projection._default_manager.create(
            forecast=forecast,
            scenario=scenario,
            revenue=Decimal("120"),
            net_profit=Decimal("12"),
            profit_margin_percent=Decimal("10"),
            currency_unit="CNY_million",
        )
        Sensitivity._default_manager.create(
            projection=projection,
            sensitivity_key="pe_multiple",
            input_value=Decimal("10"),
            input_unit="multiple",
            output_value=Decimal("1200"),
            output_unit="CNY_million",
            method_version="legacy-sheet-v1",
        )
    content_hash = _legacy_hash(apps, forecast_id, include_role=include_role)
    if corrupt_hash:
        content_hash = "f" * 64
    Forecast._default_manager.filter(pk=forecast_id).update(content_hash=content_hash)
    return content_hash


def _assert_preserved_legacy(
    apps: Any,
    *,
    forecast_id: str,
    original_hash: str,
    expected_recipe: str,
) -> None:
    Forecast = apps.get_model("equity", "OperatingForecastVersionModel")
    Projection = apps.get_model("equity", "OperatingForecastProjectionModel")
    Stage = apps.get_model("equity", "OperatingForecastStageValueModel")
    Sensitivity = apps.get_model("equity", "OperatingForecastSensitivityModel")
    row = Forecast._default_manager.get(pk=forecast_id)
    assert row.content_hash == original_hash
    assert row.valuation_consumable is True
    assert row.promotion_decision_id == f"legacy-promotion-{forecast_id.removeprefix('legacy-')}"
    assert row.template_code == ""
    assert row.template_version is None
    assert row.template_content_hash == ""
    assert row.template_run_key == ""
    assert row.template_run_version is None
    assert row.template_run_content_hash == ""
    assert row.legacy_hash_recipe == expected_recipe
    assert row.legacy_hash_status == "verified"
    assert all(item.cash_flow is None for item in Projection._default_manager.filter(forecast=row))
    assert Stage._default_manager.filter(projection__forecast=row).count() == 0
    assert all(
        not item.source_binding_complete
        and item.source_artifact_ref == ""
        and item.source_artifact_hash == ""
        for item in Sensitivity._default_manager.filter(projection__forecast=row)
    )


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_0010_to_0012_preserves_untyped_hash_bytes_and_legacy_semantics() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("equity", "0010_operating_forecast_ledger")])
        old_apps = executor.loader.project_state(
            [("equity", "0010_operating_forecast_ledger")]
        ).apps
        original_hash = _seed_legacy(
            old_apps,
            suffix="0010",
            include_role=False,
            metric_code="store_count",
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("equity", "0012_industry_template_forecast_bridge")])
        new_apps = executor.loader.project_state(
            [("equity", "0012_industry_template_forecast_bridge")]
        ).apps
        _assert_preserved_legacy(
            new_apps,
            forecast_id="legacy-0010",
            original_hash=original_hash,
            expected_recipe="v1_0010_untyped",
        )
        Assumption = new_apps.get_model("equity", "OperatingForecastAssumptionModel")
        assumption = Assumption._default_manager.filter(forecast_id="legacy-0010").first()
        assert assumption is not None
        assert assumption.fact_binding_complete is True
        assert assumption.observed_metric_code == "store_count"
        assert assumption.observed_subject_type == "company"
        assert assumption.observed_subject_code == "000001.SZ"

        restored = DjangoOperatingForecastRepository().get_version("legacy-0010")
        assert isinstance(restored, LegacyOperatingForecastVersion)
        assert restored.content_hash == original_hash
        assert restored.historical_valuation_consumable is True
        assert restored.valuation_consumable is False
        assert restored.usage_scope == "legacy_research_only"
        assert restored.legacy_hash_recipe is OperatingForecastLegacyHashRecipe.V1_0010_UNTYPED
        assert restored.legacy_hash_status is OperatingForecastLegacyHashStatus.VERIFIED
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_0011_to_0012_preserves_typed_hash_bytes_and_legacy_role() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("equity", "0011_operating_forecast_typed_fact_binding")])
        old_apps = executor.loader.project_state(
            [("equity", "0011_operating_forecast_typed_fact_binding")]
        ).apps
        original_hash = _seed_legacy(
            old_apps,
            suffix="0011",
            include_role=True,
            metric_code="revenue",
            fact_unit="CNY_million",
            assumption_unit="CNY_million",
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("equity", "0012_industry_template_forecast_bridge")])
        new_apps = executor.loader.project_state(
            [("equity", "0012_industry_template_forecast_bridge")]
        ).apps
        _assert_preserved_legacy(
            new_apps,
            forecast_id="legacy-0011",
            original_hash=original_hash,
            expected_recipe="v1_0011_typed",
        )
        Assumption = new_apps.get_model("equity", "OperatingForecastAssumptionModel")
        assumption = Assumption._default_manager.filter(forecast_id="legacy-0011").first()
        assert assumption is not None
        assert assumption.legacy_observed_metric_role == "revenue"
        assert assumption.observed_metric_code == "revenue"

        restored = DjangoOperatingForecastRepository().get_version("legacy-0011")
        assert isinstance(restored, LegacyOperatingForecastVersion)
        assert restored.legacy_hash_recipe is OperatingForecastLegacyHashRecipe.V1_0011_TYPED
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_legacy_binding_mismatches_and_unknown_hash_remain_readable_unverified() -> None:
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("equity", "0010_operating_forecast_ledger")])
        old_apps = executor.loader.project_state(
            [("equity", "0010_operating_forecast_ledger")]
        ).apps
        _seed_legacy(
            old_apps,
            suffix="missing",
            include_role=False,
            metric_code="store_count",
            include_fact=False,
        )
        _seed_legacy(
            old_apps,
            suffix="value",
            include_role=False,
            metric_code="store_count",
            fact_value="101",
        )
        _seed_legacy(
            old_apps,
            suffix="unit",
            include_role=False,
            metric_code="store_count",
            fact_unit="stores",
        )
        _seed_legacy(
            old_apps,
            suffix="subject",
            include_role=False,
            metric_code="store_count",
            fact_subject_code="OTHER.SZ",
        )
        unknown_hash = _seed_legacy(
            old_apps,
            suffix="hash",
            include_role=False,
            metric_code="store_count",
            corrupt_hash=True,
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("equity", "0012_industry_template_forecast_bridge")])
        new_apps = executor.loader.project_state(
            [("equity", "0012_industry_template_forecast_bridge")]
        ).apps
        Forecast = new_apps.get_model("equity", "OperatingForecastVersionModel")
        Assumption = new_apps.get_model("equity", "OperatingForecastAssumptionModel")
        for suffix in ("missing", "value", "unit", "subject", "hash"):
            row = Forecast._default_manager.get(pk=f"legacy-{suffix}")
            assert row.source_lineage_status == "legacy_unverified"
        for suffix in ("missing", "value", "unit", "subject"):
            rows = Assumption._default_manager.filter(forecast_id=f"legacy-{suffix}")
            assert all(not row.fact_binding_complete for row in rows)
            assert all(row.observed_metric_code == "" for row in rows)

        hash_row = Forecast._default_manager.get(pk="legacy-hash")
        assert hash_row.content_hash == unknown_hash
        assert hash_row.legacy_hash_recipe == "unverified"
        assert hash_row.legacy_hash_status == "unverified"
        restored = DjangoOperatingForecastRepository().get_version("legacy-hash")
        assert isinstance(restored, LegacyOperatingForecastVersion)
        assert restored.content_hash == unknown_hash
        assert restored.source_lineage_status is (
            OperatingForecastSourceLineageStatus.LEGACY_UNVERIFIED
        )
        assert restored.legacy_hash_status is OperatingForecastLegacyHashStatus.UNVERIFIED
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
