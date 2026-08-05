"""Migrate the former Account code catalog into canonical Risk Center revisions."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from django.db import migrations

MIGRATION_REF = "risk_center.0004_seed_legacy_stress_scenarios"
SOURCE_FILE = "apps/account/application/stress_testing_use_cases.py"
CREATED_AT = datetime(2026, 8, 4, tzinfo=UTC)
UUID_NAMESPACE = uuid.UUID("f08f95f8-1f4d-4ea3-ae75-30e0b9217b62")

LEGACY_SCENARIOS = (
    {
        "scenario_key": "historical.cn_equity.2015_crash",
        "legacy_alias": "2015_crash",
        "name": "2015股灾",
        "description": "2015年6月-8月股市暴跌",
        "start_date": "2015-06-12",
        "end_date": "2015-08-26",
    },
    {
        "scenario_key": "historical.global_equity.2020_covid",
        "legacy_alias": "2020_covid",
        "name": "2020疫情冲击",
        "description": "2020年1月-3月COVID-19疫情冲击",
        "start_date": "2020-01-14",
        "end_date": "2020-03-23",
    },
    {
        "scenario_key": "historical.cn_equity.2018_trade_war",
        "legacy_alias": "2018_trade_war",
        "name": "2018贸易战",
        "description": "2018年全年中美贸易战",
        "start_date": "2018-01-02",
        "end_date": "2018-12-28",
    },
)


def _content_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def seed_legacy_scenarios(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    """Insert each legacy definition/revision once and reject divergent collisions."""

    Definition = apps.get_model("risk_center", "StressScenarioDefinitionModel")
    Revision = apps.get_model("risk_center", "StressScenarioRevisionModel")
    for item in LEGACY_SCENARIOS:
        definition_defaults = {
            "name": item["name"],
            "category": "historical_stress",
            "owner": "risk_center",
            "status": "active",
            "description": item["description"],
            "legacy_aliases": [item["legacy_alias"]],
            "created_at": CREATED_AT,
        }
        definition, created = Definition.objects.get_or_create(
            scenario_key=item["scenario_key"],
            defaults=definition_defaults,
        )
        if not created:
            for field_name, expected in definition_defaults.items():
                if getattr(definition, field_name) != expected:
                    raise RuntimeError(
                        f"legacy scenario definition collision: {item['scenario_key']}:{field_name}"
                    )

        parameters = {
            "start_date": item["start_date"],
            "end_date": item["end_date"],
            "source": "legacy.account.tushare_stock_adapter",
            "event_description": item["description"],
        }
        assumptions = ("Migrated without semantic changes from the legacy Account catalog.",)
        source_evidence = (
            {
                "migration_ref": MIGRATION_REF,
                "source_file": SOURCE_FILE,
                "legacy_scenario_id": item["legacy_alias"],
                "original_start_date": item["start_date"],
                "original_end_date": item["end_date"],
            },
        )
        content_hash = _content_hash(
            {
                "scenario_key": item["scenario_key"],
                "scenario_type": "historical_window",
                "parameters": parameters,
                "assumptions": list(assumptions),
                "source_evidence": list(source_evidence),
            }
        )
        revision_defaults = {
            "revision_id": uuid.uuid5(UUID_NAMESPACE, str(item["scenario_key"])),
            "based_on_version": None,
            "status": "approved",
            "scenario_type": "historical_window",
            "parameters": parameters,
            "assumptions": list(assumptions),
            "source_evidence": list(source_evidence),
            "source_type": "legacy_code_migration",
            "content_hash": content_hash,
            "created_by": "system:migration",
            "change_reason": "Migrate the legacy Account historical scenario catalog.",
            "effective_at": CREATED_AT,
            "created_at": CREATED_AT,
        }
        revision, revision_created = Revision.objects.get_or_create(
            definition_id=definition.pk,
            version=1,
            defaults=revision_defaults,
        )
        if not revision_created:
            for field_name, expected in revision_defaults.items():
                if getattr(revision, field_name) != expected:
                    raise RuntimeError(
                        f"legacy scenario revision collision: {item['scenario_key']}:{field_name}"
                    )


def unseed_legacy_scenarios(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    """Remove only rows owned by this exact migration."""

    Definition = apps.get_model("risk_center", "StressScenarioDefinitionModel")
    Revision = apps.get_model("risk_center", "StressScenarioRevisionModel")
    keys = [item["scenario_key"] for item in LEGACY_SCENARIOS]
    Revision.objects.filter(
        definition__scenario_key__in=keys,
        version=1,
        source_type="legacy_code_migration",
        created_by="system:migration",
    ).delete()
    Definition.objects.filter(scenario_key__in=keys, revisions__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("risk_center", "0003_scenario_governance_models")]

    operations = [migrations.RunPython(seed_legacy_scenarios, unseed_legacy_scenarios)]
