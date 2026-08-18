"""Label A-share price-limit counts with their non-ST market scope."""

from __future__ import annotations

from typing import Any

from django.db import migrations

CURRENT_METADATA: dict[str, dict[str, str]] = {
    "CN_A_LIMIT_UP_COUNT": {
        "name_cn": "A股涨停家数（不含 ST）",
        "description": (
            "日度非 ST 股票涨停家数，用于观察A股交易热度；"
            "统计口径剔除名称含 ST（含 *ST）的股票，缺数时不得补零。"
        ),
    },
    "CN_A_LIMIT_DOWN_COUNT": {
        "name_cn": "A股跌停家数（不含 ST）",
        "description": (
            "日度非 ST 股票跌停家数，用于观察A股交易压力；"
            "统计口径剔除名称含 ST（含 *ST）的股票，缺数时不得补零。"
        ),
    },
}

PREVIOUS_METADATA: dict[str, dict[str, str]] = {
    "CN_A_LIMIT_UP_COUNT": {
        "name_cn": "A股涨停家数",
        "description": "日度涨停股票家数，用于观察A股交易热度；缺数时不得补零。",
    },
    "CN_A_LIMIT_DOWN_COUNT": {
        "name_cn": "A股跌停家数",
        "description": "日度跌停股票家数，用于观察A股交易压力；缺数时不得补零。",
    },
}


def apply_non_st_scope_labels(apps: Any, schema_editor: Any) -> None:
    """Update existing catalog rows with the explicit non-ST scope."""

    indicator_catalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for indicator_code, metadata in CURRENT_METADATA.items():
        indicator_catalog.objects.filter(code=indicator_code).update(**metadata)


def restore_previous_scope_labels(apps: Any, schema_editor: Any) -> None:
    """Restore the prior catalog labels and descriptions."""

    indicator_catalog = apps.get_model("data_center", "IndicatorCatalogModel")
    for indicator_code, metadata in PREVIOUS_METADATA.items():
        indicator_catalog.objects.filter(code=indicator_code).update(**metadata)


class Migration(migrations.Migration):
    dependencies = [
        ("data_center", "0071_syncexecutionidentitymodel"),
    ]

    operations = [
        migrations.RunPython(
            apply_non_st_scope_labels,
            restore_previous_scope_labels,
        ),
    ]
