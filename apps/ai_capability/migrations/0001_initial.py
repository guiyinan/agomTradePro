from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CapabilityCatalogModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "capability_key",
                    models.CharField(
                        db_index=True,
                        help_text="Unique capability identifier (e.g., builtin.system_status)",
                        max_length=255,
                        unique=True,
                    ),
                ),
                (
                    "source_type",
                    models.CharField(
                        choices=[
                            ("builtin", "builtin"),
                            ("terminal_command", "terminal_command"),
                            ("mcp_tool", "mcp_tool"),
                            ("api", "api"),
                        ],
                        db_index=True,
                        help_text="Source type: builtin, terminal_command, mcp_tool, api",
                        max_length=30,
                    ),
                ),
                (
                    "source_ref",
                    models.CharField(
                        help_text="Reference to original source (e.g., tool name, API path)",
                        max_length=255,
                    ),
                ),
                (
                    "name",
                    models.CharField(help_text="Human-readable capability name", max_length=255),
                ),
                ("summary", models.TextField(help_text="Short summary for AI routing")),
                (
                    "description",
                    models.TextField(blank=True, default="", help_text="Detailed description"),
                ),
                (
                    "route_group",
                    models.CharField(
                        choices=[
                            ("builtin", "builtin"),
                            ("tool", "tool"),
                            ("read_api", "read_api"),
                            ("write_api", "write_api"),
                            ("unsafe_api", "unsafe_api"),
                        ],
                        db_index=True,
                        default="tool",
                        help_text="Routing group: builtin, tool, read_api, write_api, unsafe_api",
                        max_length=20,
                    ),
                ),
                (
                    "category",
                    models.CharField(
                        db_index=True,
                        default="general",
                        help_text="Capability category",
                        max_length=100,
                    ),
                ),
                (
                    "tags",
                    models.JSONField(blank=True, default=list, help_text="List of tags for search"),
                ),
                (
                    "when_to_use",
                    models.JSONField(blank=True, default=list, help_text="List of usage scenarios"),
                ),
                (
                    "when_not_to_use",
                    models.JSONField(
                        blank=True, default=list, help_text="List of non-usage scenarios"
                    ),
                ),
                (
                    "examples",
                    models.JSONField(blank=True, default=list, help_text="List of example queries"),
                ),
                (
                    "input_schema",
                    models.JSONField(
                        blank=True, default=dict, help_text="JSON Schema for input parameters"
                    ),
                ),
                (
                    "execution_kind",
                    models.CharField(
                        choices=[("sync", "sync"), ("async", "async"), ("streaming", "streaming")],
                        default="sync",
                        help_text="Execution type: sync, async, streaming",
                        max_length=20,
                    ),
                ),
                (
                    "execution_target",
                    models.JSONField(
                        blank=True, default=dict, help_text="Execution target configuration"
                    ),
                ),
                (
                    "risk_level",
                    models.CharField(
                        choices=[
                            ("safe", "safe"),
                            ("low", "low"),
                            ("medium", "medium"),
                            ("high", "high"),
                            ("critical", "critical"),
                        ],
                        db_index=True,
                        default="safe",
                        help_text="Risk level: safe, low, medium, high, critical",
                        max_length=20,
                    ),
                ),
                (
                    "requires_mcp",
                    models.BooleanField(default=False, help_text="Requires MCP permission"),
                ),
                (
                    "requires_confirmation",
                    models.BooleanField(
                        default=False, help_text="Requires user confirmation before execution"
                    ),
                ),
                (
                    "enabled_for_routing",
                    models.BooleanField(
                        db_index=True, default=True, help_text="Enabled for AI routing"
                    ),
                ),
                (
                    "enabled_for_terminal",
                    models.BooleanField(default=True, help_text="Enabled for terminal entrypoint"),
                ),
                (
                    "enabled_for_chat",
                    models.BooleanField(default=True, help_text="Enabled for chat entrypoint"),
                ),
                (
                    "enabled_for_agent",
                    models.BooleanField(default=True, help_text="Enabled for agent entrypoint"),
                ),
                (
                    "visibility",
                    models.CharField(
                        choices=[
                            ("public", "public"),
                            ("internal", "internal"),
                            ("admin", "admin"),
                            ("hidden", "hidden"),
                        ],
                        db_index=True,
                        default="public",
                        help_text="Visibility level: public, internal, admin, hidden",
                        max_length=20,
                    ),
                ),
                (
                    "auto_collected",
                    models.BooleanField(
                        default=False, help_text="Automatically collected from source"
                    ),
                ),
                (
                    "review_status",
                    models.CharField(
                        choices=[
                            ("auto", "auto"),
                            ("pending", "pending"),
                            ("approved", "approved"),
                            ("rejected", "rejected"),
                        ],
                        db_index=True,
                        default="auto",
                        help_text="Review status: auto, pending, approved, rejected",
                        max_length=20,
                    ),
                ),
                (
                    "priority_weight",
                    models.FloatField(
                        default=1.0,
                        help_text="Priority weight for scoring (higher = more important)",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "last_synced_at",
                    models.DateTimeField(
                        blank=True, help_text="Last synchronization timestamp", null=True
                    ),
                ),
            ],
            options={
                "verbose_name": "AI Capability",
                "verbose_name_plural": "AI Capability Catalog",
                "db_table": "ai_capability_catalog",
                "ordering": ["-priority_weight", "name"],
            },
        ),
        migrations.CreateModel(
            name="CapabilityRoutingLogModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "entrypoint",
                    models.CharField(
                        db_index=True, help_text="Entrypoint: terminal, chat, agent", max_length=50
                    ),
                ),
                ("session_id", models.CharField(db_index=True, max_length=100)),
                ("raw_message", models.TextField()),
                (
                    "retrieved_candidates",
                    models.JSONField(default=list, help_text="List of retrieved capability keys"),
                ),
                (
                    "selected_capability_key",
                    models.CharField(blank=True, db_index=True, max_length=255, null=True),
                ),
                ("confidence", models.FloatField(default=0.0)),
                (
                    "decision",
                    models.CharField(
                        choices=[
                            ("capability", "capability"),
                            ("ask_confirmation", "ask_confirmation"),
                            ("chat", "chat"),
                            ("fallback", "fallback"),
                        ],
                        default="chat",
                        max_length=30,
                    ),
                ),
                ("fallback_reason", models.TextField(blank=True, default="")),
                ("execution_result", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Capability Routing Log",
                "verbose_name_plural": "Capability Routing Logs",
                "db_table": "ai_capability_routing_log",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="CapabilitySyncLogModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "sync_type",
                    models.CharField(
                        choices=[
                            ("full", "Full Sync"),
                            ("incremental", "Incremental Sync"),
                            ("init", "Initialization"),
                        ],
                        db_index=True,
                        max_length=30,
                    ),
                ),
                ("started_at", models.DateTimeField()),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("total_discovered", models.IntegerField(default=0)),
                ("created_count", models.IntegerField(default=0)),
                ("updated_count", models.IntegerField(default=0)),
                ("disabled_count", models.IntegerField(default=0)),
                ("error_count", models.IntegerField(default=0)),
                ("summary_payload", models.JSONField(blank=True, default=dict)),
            ],
            options={
                "verbose_name": "Capability Sync Log",
                "verbose_name_plural": "Capability Sync Logs",
                "db_table": "ai_capability_sync_log",
                "ordering": ["-started_at"],
            },
        ),
        migrations.AddIndex(
            model_name="capabilitycatalogmodel",
            index=models.Index(
                fields=["source_type", "enabled_for_routing"], name="ai_cap_src_en_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="capabilitycatalogmodel",
            index=models.Index(
                fields=["route_group", "enabled_for_routing"], name="ai_cap_grp_en_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="capabilitycatalogmodel",
            index=models.Index(
                fields=["category", "enabled_for_routing"], name="ai_cap_cat_en_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="capabilitycatalogmodel",
            index=models.Index(
                fields=["risk_level", "enabled_for_routing"], name="ai_cap_risk_en_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="capabilitycatalogmodel",
            index=models.Index(fields=["review_status"], name="ai_cap_review_idx"),
        ),
    ]
