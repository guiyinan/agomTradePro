from __future__ import annotations

import hashlib
import json
from datetime import UTC
from decimal import Decimal, InvalidOperation
from typing import Any

import django.db.models.deletion
from django.db import migrations, models


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _same_decimal(left: object, right: object) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, ValueError):
        return False


def _legacy_hash(
    *,
    forecast: Any,
    FactReference: Any,
    Assumption: Any,
    Projection: Any,
    Sensitivity: Any,
    database: str,
    include_metric_role: bool,
) -> str:
    facts = (
        FactReference._default_manager.using(database)
        .filter(forecast_id=forecast.pk)
        .order_by("pit_fact_version_id")
    )
    assumptions = (
        Assumption._default_manager.using(database)
        .filter(forecast_id=forecast.pk)
        .order_by("scenario", "assumption_key")
    )
    projections = (
        Projection._default_manager.using(database)
        .filter(forecast_id=forecast.pk)
        .order_by("scenario")
    )
    assumption_payloads: list[dict[str, object]] = []
    for row in assumptions.iterator():
        payload: dict[str, object] = {
            "scenario": row.scenario,
            "assumption_key": row.assumption_key,
            "value": _decimal_text(row.value),
            "unit": row.unit,
            "input_kind": row.input_kind,
            "rationale": row.rationale,
            "lineage_ref": (
                f"data_center_pit_fact:{row.observed_fact_version_id}"
                if row.input_kind == "observed_fact"
                else (
                    row.human_assumption_ref
                    if row.input_kind == "human_assumption"
                    else row.model_version
                )
            ),
        }
        if include_metric_role:
            payload["observed_metric_role"] = row.legacy_observed_metric_role or None
        assumption_payloads.append(payload)
    projection_payloads: list[dict[str, object]] = []
    for row in projections.iterator():
        sensitivities = (
            Sensitivity._default_manager.using(database)
            .filter(projection_id=row.pk)
            .order_by("sensitivity_key")
        )
        projection_payloads.append(
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
                    for point in sensitivities.iterator()
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
            for row in facts.iterator()
        ],
        "assumptions": assumption_payloads,
        "projections": projection_payloads,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def classify_legacy_forecasts(apps: Any, schema_editor: Any) -> None:
    """Classify exact v1 hash recipes and backfill only proven generic fact identity."""

    Forecast = apps.get_model("equity", "OperatingForecastVersionModel")
    Assumption = apps.get_model("equity", "OperatingForecastAssumptionModel")
    FactReference = apps.get_model("equity", "OperatingForecastFactReferenceModel")
    Projection = apps.get_model("equity", "OperatingForecastProjectionModel")
    Sensitivity = apps.get_model("equity", "OperatingForecastSensitivityModel")
    database = schema_editor.connection.alias
    for forecast in Forecast._default_manager.using(database).all().iterator():
        untyped_hash = _legacy_hash(
            forecast=forecast,
            FactReference=FactReference,
            Assumption=Assumption,
            Projection=Projection,
            Sensitivity=Sensitivity,
            database=database,
            include_metric_role=False,
        )
        typed_hash = _legacy_hash(
            forecast=forecast,
            FactReference=FactReference,
            Assumption=Assumption,
            Projection=Projection,
            Sensitivity=Sensitivity,
            database=database,
            include_metric_role=True,
        )
        if forecast.content_hash == untyped_hash:
            hash_recipe = "v1_0010_untyped"
            hash_status = "verified"
        elif forecast.content_hash == typed_hash:
            hash_recipe = "v1_0011_typed"
            hash_status = "verified"
        else:
            hash_recipe = "unverified"
            hash_status = "unverified"

        lineage_unverified = hash_status != "verified"
        observed = Assumption._default_manager.using(database).filter(
            forecast_id=forecast.pk,
            input_kind="observed_fact",
        )
        for assumption in observed.iterator():
            matches = list(
                FactReference._default_manager.using(database).filter(
                    forecast_id=forecast.pk,
                    pit_fact_version_id=assumption.observed_fact_version_id,
                )[:2]
            )
            fact = matches[0] if len(matches) == 1 else None
            exact = bool(
                fact is not None
                and fact.subject_type == "company"
                and fact.subject_code == forecast.subject_code
                and fact.unit == assumption.unit
                and _same_decimal(fact.value, assumption.value)
                and (
                    hash_recipe != "v1_0011_typed"
                    or (
                        bool(assumption.legacy_observed_metric_role)
                        and assumption.legacy_observed_metric_role == fact.metric_code
                    )
                )
            )
            if not exact:
                lineage_unverified = True
                continue
            Assumption._default_manager.using(database).filter(pk=assumption.pk).update(
                fact_binding_complete=True,
                observed_metric_code=fact.metric_code,
                observed_fact_content_hash=fact.pit_content_hash,
                observed_subject_type=fact.subject_type,
                observed_subject_code=fact.subject_code,
            )
        Forecast._default_manager.using(database).filter(pk=forecast.pk).update(
            legacy_hash_recipe=hash_recipe,
            legacy_hash_status=hash_status,
            source_lineage_status=("legacy_unverified" if lineage_unverified else "legacy_unbound"),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("equity", "0011_operating_forecast_typed_fact_binding"),
    ]

    operations = [
        migrations.AddField(
            model_name="operatingforecastversionmodel",
            name="evidence_schema_version",
            field=models.PositiveSmallIntegerField(default=1, editable=False),
        ),
        migrations.AddField(
            model_name="operatingforecastversionmodel",
            name="source_lineage_status",
            field=models.CharField(
                choices=[
                    ("legacy_unbound", "legacy_unbound"),
                    ("legacy_unverified", "legacy_unverified"),
                    ("template_bound", "template_bound"),
                ],
                default="legacy_unbound",
                editable=False,
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="operatingforecastversionmodel",
            name="legacy_hash_recipe",
            field=models.CharField(
                choices=[
                    ("v1_0010_untyped", "v1_0010_untyped"),
                    ("v1_0011_typed", "v1_0011_typed"),
                    ("unverified", "unverified"),
                    ("not_applicable", "not_applicable"),
                ],
                default="unverified",
                editable=False,
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="operatingforecastversionmodel",
            name="legacy_hash_status",
            field=models.CharField(
                choices=[
                    ("verified", "verified"),
                    ("unverified", "unverified"),
                    ("not_applicable", "not_applicable"),
                ],
                default="unverified",
                editable=False,
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="operatingforecastversionmodel",
            name="template_code",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.AddField(
            model_name="operatingforecastversionmodel",
            name="template_content_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="operatingforecastversionmodel",
            name="template_run_content_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="operatingforecastversionmodel",
            name="template_run_key",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="operatingforecastversionmodel",
            name="template_run_version",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="operatingforecastversionmodel",
            name="template_version",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.RenameField(
            model_name="operatingforecastassumptionmodel",
            old_name="observed_metric_role",
            new_name="legacy_observed_metric_role",
        ),
        migrations.AddField(
            model_name="operatingforecastassumptionmodel",
            name="fact_binding_complete",
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.AddField(
            model_name="operatingforecastassumptionmodel",
            name="observed_fact_content_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="operatingforecastassumptionmodel",
            name="observed_metric_code",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="operatingforecastassumptionmodel",
            name="observed_subject_code",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.AddField(
            model_name="operatingforecastassumptionmodel",
            name="observed_subject_type",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="operatingforecastprojectionmodel",
            name="cash_flow",
            field=models.DecimalField(
                blank=True,
                decimal_places=12,
                max_digits=50,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="operatingforecastsensitivitymodel",
            name="source_artifact_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="operatingforecastsensitivitymodel",
            name="source_artifact_ref",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="operatingforecastsensitivitymodel",
            name="source_binding_complete",
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.CreateModel(
            name="OperatingForecastStageValueModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "stage",
                    models.CharField(
                        choices=[
                            ("revenue", "revenue"),
                            ("cost", "cost"),
                            ("gross_profit", "gross_profit"),
                            ("expense", "expense"),
                            ("net_profit", "net_profit"),
                            ("cash_flow", "cash_flow"),
                        ],
                        max_length=24,
                    ),
                ),
                ("node_key", models.CharField(max_length=80)),
                ("value", models.DecimalField(decimal_places=12, max_digits=50)),
                ("unit", models.CharField(max_length=40)),
                (
                    "projection",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stage_values",
                        to="equity.operatingforecastprojectionmodel",
                    ),
                ),
            ],
            options={
                "db_table": "equity_operating_forecast_stage_value",
                "indexes": [
                    models.Index(
                        fields=["projection", "stage"],
                        name="equity_fc_stage_projection_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("projection", "stage"),
                        name="equity_forecast_projection_stage_uniq",
                    )
                ],
            },
        ),
        migrations.RunPython(
            classify_legacy_forecasts,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="operatingforecastversionmodel",
            constraint=models.UniqueConstraint(
                condition=models.Q(evidence_schema_version=2),
                fields=("template_run_key", "template_run_version"),
                name="equity_forecast_template_run_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="operatingforecastversionmodel",
            constraint=models.CheckConstraint(
                condition=(
                    (
                        models.Q(
                            evidence_schema_version=1,
                            source_lineage_status__in=(
                                "legacy_unbound",
                                "legacy_unverified",
                            ),
                            template_code="",
                            template_content_hash="",
                            template_run_content_hash="",
                            template_run_key="",
                            template_run_version__isnull=True,
                            template_version__isnull=True,
                        )
                        & (
                            models.Q(
                                legacy_hash_recipe__in=(
                                    "v1_0010_untyped",
                                    "v1_0011_typed",
                                ),
                                legacy_hash_status="verified",
                            )
                            | models.Q(
                                legacy_hash_recipe="unverified",
                                legacy_hash_status="unverified",
                                source_lineage_status="legacy_unverified",
                            )
                        )
                    )
                    | (
                        models.Q(
                            evidence_schema_version=2,
                            source_lineage_status="template_bound",
                            template_run_version__isnull=False,
                            template_version__isnull=False,
                            legacy_hash_recipe="not_applicable",
                            legacy_hash_status="not_applicable",
                            valuation_consumable=False,
                            promotion_decision_id="",
                        )
                        & ~models.Q(template_code="")
                        & ~models.Q(template_content_hash="")
                        & ~models.Q(template_run_key="")
                        & ~models.Q(template_run_content_hash="")
                    )
                ),
                name="equity_forecast_template_binding_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="operatingforecastassumptionmodel",
            constraint=models.CheckConstraint(
                condition=(
                    (
                        models.Q(fact_binding_complete=True, input_kind="observed_fact")
                        & ~models.Q(observed_metric_code="")
                        & ~models.Q(observed_fact_content_hash="")
                        & ~models.Q(observed_subject_type="")
                        & ~models.Q(observed_subject_code="")
                    )
                    | (
                        models.Q(
                            fact_binding_complete=True,
                            observed_fact_content_hash="",
                            observed_metric_code="",
                            observed_subject_code="",
                            observed_subject_type="",
                        )
                        & ~models.Q(input_kind="observed_fact")
                    )
                    | models.Q(
                        fact_binding_complete=False,
                        observed_fact_content_hash="",
                        observed_metric_code="",
                        observed_subject_code="",
                        observed_subject_type="",
                    )
                ),
                name="equity_forecast_assumption_fact_binding_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="operatingforecastsensitivitymodel",
            constraint=models.CheckConstraint(
                condition=(
                    (
                        models.Q(source_binding_complete=True)
                        & ~models.Q(source_artifact_ref="")
                        & ~models.Q(source_artifact_hash="")
                    )
                    | models.Q(
                        source_binding_complete=False,
                        source_artifact_ref="",
                        source_artifact_hash="",
                    )
                ),
                name="equity_forecast_sensitivity_source_ck",
            ),
        ),
        migrations.AlterModelOptions(
            name="operatingforecastassumptionmodel",
            options={
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.AlterModelOptions(
            name="operatingforecastevaluationmodel",
            options={
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.AlterModelOptions(
            name="operatingforecastfactreferencemodel",
            options={
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.AlterModelOptions(
            name="operatingforecastprojectionmodel",
            options={
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.AlterModelOptions(
            name="operatingforecastsensitivitymodel",
            options={
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.AlterModelOptions(
            name="operatingforecaststagevaluemodel",
            options={
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.AlterModelOptions(
            name="operatingforecastversionmodel",
            options={
                "base_manager_name": "objects",
                "default_manager_name": "objects",
            },
        ),
    ]
