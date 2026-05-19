"""Seed the market temperature AI capability."""

from __future__ import annotations

from django.db import migrations


def seed_market_temperature_capability(apps, schema_editor):
    CapabilityCatalog = apps.get_model("ai_capability", "CapabilityCatalogModel")

    CapabilityCatalog.objects.update_or_create(
        capability_key="terminal_command.market_temperature",
        defaults={
            "source_type": "terminal_command",
            "source_ref": "terminal:market_temperature",
            "name": "market_temperature",
            "summary": "Get the current market thermometer score, band, and overheating risk.",
            "description": "Read the latest market thermometer snapshot, including personal thresholds, key heating reasons, and chasing-risk warning.",
            "route_group": "tool",
            "category": "market",
            "tags": [
                "market",
                "temperature",
                "heat",
                "overheat",
                "散户热度",
                "接盘风险",
                "追高",
            ],
            "when_to_use": [
                "User asks whether the market is overheated.",
                "User asks about market heat, retail heat, or emotional chasing risk.",
            ],
            "when_not_to_use": [
                "Do not use for order placement or account mutation.",
            ],
            "examples": [
                "市场是不是过热了",
                "现在散户热度高吗",
                "我会不会接盘",
            ],
            "input_schema": {
                "type": "object",
                "properties": {
                    "use_personal_thresholds": {"type": "boolean", "default": True},
                    "verbose": {"type": "boolean", "default": False},
                },
            },
            "execution_kind": "sync",
            "execution_target": {
                "type": "terminal_command",
                "command_name": "market_temperature",
            },
            "risk_level": "safe",
            "requires_mcp": False,
            "requires_confirmation": False,
            "enabled_for_routing": True,
            "enabled_for_terminal": True,
            "enabled_for_chat": True,
            "enabled_for_agent": True,
            "visibility": "public",
            "auto_collected": False,
            "review_status": "approved",
            "priority_weight": 8.0,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("ai_capability", "0002_rename_ai_cap_src_en_idx_ai_capabili_source__f3ec7e_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(
            seed_market_temperature_capability,
            migrations.RunPython.noop,
        ),
    ]
