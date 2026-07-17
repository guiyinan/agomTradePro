"""Harden routing metadata for market temperature and public fund ranking."""

from __future__ import annotations

from django.db import migrations


def apply_routing_contracts(apps, schema_editor):
    """Publish aliases and the strict parameter schema used by the router."""

    catalog = apps.get_model("ai_capability", "CapabilityCatalogModel")
    catalog.objects.filter(capability_key="terminal_command.market_temperature").update(
        summary="Get the current market temperature score, band, observation time, and overheating risk.",
        description=(
            "读取当前市场温度、市场热度、市场温度计分数、分段、数据时间、" "过热风险和追高提示。"
        ),
        tags=[
            "market",
            "temperature",
            "market temperature",
            "sentiment temperature",
            "市场温度",
            "市场热度",
            "过热风险",
        ],
        examples=[
            "获取市场温度",
            "请获取当前最新的市场温度数据",
            "市场是不是过热了",
            "market temperature",
        ],
    )
    catalog.objects.filter(capability_key="api.get.api.fund.rank").update(
        input_schema={
            "type": "object",
            "properties": {
                "regime": {
                    "type": "string",
                    "enum": ["Recovery", "Overheat", "Stagflation", "Deflation"],
                    "default": "Recovery",
                },
                "max_count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    )


class Migration(migrations.Migration):
    dependencies = [("ai_capability", "0005_semantic_governance")]

    operations = [
        migrations.RunPython(apply_routing_contracts, migrations.RunPython.noop),
    ]
