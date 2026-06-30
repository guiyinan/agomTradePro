"""Seed the advisor_query terminal command."""

from __future__ import annotations

from django.db import migrations


def seed_advisor_query_command(apps, schema_editor):
    TerminalCommand = apps.get_model("terminal", "TerminalCommandORM")

    TerminalCommand.objects.update_or_create(
        name="advisor_query",
        defaults={
            "description": "对指定账户执行自动投顾自然语言查询。",
            "command_type": "api",
            "api_endpoint": "/api/dashboard/auto-advisor-query/",
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
                    "name": "question",
                    "type": "text",
                    "description": "自然语言问题",
                    "required": True,
                    "default": "",
                    "prompt": "请输入问题",
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
            "tags": ["advisor", "decision", "account", "query", "qa"],
            "is_active": True,
            "risk_level": "read",
            "requires_mcp": False,
            "enabled_in_terminal": True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("terminal", "0007_seed_advisor_today_command"),
    ]

    operations = [
        migrations.RunPython(
            seed_advisor_query_command,
            migrations.RunPython.noop,
        ),
    ]
