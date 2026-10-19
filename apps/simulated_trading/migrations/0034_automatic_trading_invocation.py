"""Persist the idempotency and frozen scope for one automatic simulated run."""

from __future__ import annotations

import uuid

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps
from django.db.models import Q


def refuse_to_drop_automatic_invocations(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Retain run identities while any automatic invocation row exists."""

    invocation_model = apps.get_model("simulated_trading", "AutomaticTradingInvocationModel")
    connection = schema_editor.connection
    if connection.vendor == "postgresql":
        if not connection.in_atomic_block:
            raise IrreversibleError(
                "Cannot safely inspect automatic invocation records outside a "
                "PostgreSQL transaction."
            )
        quoted_table = schema_editor.quote_name(invocation_model._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {quoted_table} IN ACCESS EXCLUSIVE MODE")
    if invocation_model._base_manager.using(connection.alias).exists():
        raise IrreversibleError(
            "Cannot drop automatic invocation records while they protect retry identity "
            "and outcomes."
        )


class Migration(migrations.Migration):
    """Create one durable, non-financial automatic run record per caller key."""

    atomic = True

    dependencies = [("simulated_trading", "0033_cost_basis_knowledge")]

    operations = [
        migrations.CreateModel(
            name="AutomaticTradingInvocationModel",
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
                    "invocation_id",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("namespace", models.CharField(max_length=96)),
                ("invocation_key", models.CharField(max_length=128)),
                ("request_hash", models.CharField(max_length=64)),
                ("request_payload", models.JSONField()),
                ("trade_date", models.DateField()),
                ("account_ids", models.JSONField()),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("ready", "Ready"),
                            ("preparing", "Preparing"),
                            ("started", "Started"),
                            ("finished", "Finished"),
                        ],
                        default="ready",
                        max_length=16,
                    ),
                ),
                ("claim_token", models.UUIDField(blank=True, null=True)),
                ("outcome_payload", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "simulated_auto_trading_invocation",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("namespace", "invocation_key"),
                        name="simautoinv_namespace_key_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            Q(
                                state="ready",
                                claim_token__isnull=True,
                                started_at__isnull=True,
                                finished_at__isnull=True,
                                outcome_payload__isnull=True,
                            )
                            | Q(
                                state="preparing",
                                claim_token__isnull=False,
                                started_at__isnull=True,
                                finished_at__isnull=True,
                                outcome_payload__isnull=True,
                            )
                            | Q(
                                state="started",
                                claim_token__isnull=False,
                                started_at__isnull=False,
                                finished_at__isnull=True,
                                outcome_payload__isnull=True,
                            )
                            | Q(
                                state="finished",
                                claim_token__isnull=False,
                                started_at__isnull=False,
                                finished_at__isnull=False,
                                outcome_payload__isnull=False,
                            )
                        ),
                        name="simautoinv_state_shape_ck",
                    ),
                ],
                "indexes": [
                    models.Index(
                        fields=("state", "created_at"),
                        name="simautoinv_state_ct_idx",
                    ),
                ],
            },
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_to_drop_automatic_invocations,
        ),
    ]
