"""Seed the advisor_today terminal command."""

from __future__ import annotations

from django.db import migrations


def seed_advisor_today_command(apps, schema_editor):
    TerminalCommand = apps.get_model("terminal", "TerminalCommandORM")

    TerminalCommand.objects.update_or_create(
        name="advisor_today",
        defaults={
            "description": "按账户读取今日自动投顾建议单和建议订单清单。",
            "command_type": "api",
            "api_endpoint": "/api/decision/advisor/sheet/",
            "api_method": "GET",
            "response_jq_filter": "",
            "parameters": [
                {
                    "name": "account_id",
                    "type": "text",
                    "description": "账户 ID",
                    "required": True,
                    "default": "",
                    "prompt": "请输入账户 ID",
                },
                {
                    "name": "verbose",
                    "type": "boolean",
                    "description": "是否输出完整 JSON",
                    "required": False,
                    "default": False,
                    "prompt": "",
                },
            ],
            "timeout": 30,
            "provider_name": "",
            "model_name": "",
            "category": "decision",
            "tags": ["advisor", "decision", "account", "orders", "portfolio"],
            "is_active": True,
            "risk_level": "read",
            "requires_mcp": False,
            "enabled_in_terminal": True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("terminal", "0006_tui_metadata_registry"),
    ]

    operations = [
        migrations.RunPython(
            seed_advisor_today_command,
            migrations.RunPython.noop,
        ),
    ]
