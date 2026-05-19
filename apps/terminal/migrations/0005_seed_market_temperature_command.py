"""Seed the market_temperature terminal command."""

from __future__ import annotations

from django.db import migrations


def seed_market_temperature_command(apps, schema_editor):
    TerminalCommand = apps.get_model("terminal", "TerminalCommandORM")

    TerminalCommand.objects.update_or_create(
        name="market_temperature",
        defaults={
            "description": "读取当前市场温度计分数、分段与过热风险。",
            "command_type": "api",
            "api_endpoint": "/api/data-center/market-thermometer/current/",
            "api_method": "GET",
            "response_jq_filter": "",
            "parameters": [
                {
                    "name": "use_personal_thresholds",
                    "type": "boolean",
                    "description": "是否使用当前用户阈值覆盖",
                    "required": False,
                    "default": True,
                    "prompt": "",
                },
                {
                    "name": "verbose",
                    "type": "boolean",
                    "description": "是否输出更详细的原始字段",
                    "required": False,
                    "default": False,
                    "prompt": "",
                },
            ],
            "timeout": 30,
            "provider_name": "",
            "model_name": "",
            "category": "market",
            "tags": ["market", "temperature", "heat", "overheat", "retail", "risk"],
            "is_active": True,
            "risk_level": "read",
            "requires_mcp": False,
            "enabled_in_terminal": True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("terminal", "0004_terminalruntimesettingsorm_fallback_chat_system_prompt"),
    ]

    operations = [
        migrations.RunPython(
            seed_market_temperature_command,
            migrations.RunPython.noop,
        ),
    ]
