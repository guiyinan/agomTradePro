"""Persist qualified local daily-match decisions without backfilling history."""

from __future__ import annotations

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps
from django.db.models import Q


def refuse_to_drop_local_daily_match_history(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Refuse reversal once any account decision or source evidence was recorded."""

    model = apps.get_model("simulated_trading", "LocalDailyMatchModel")
    connection = schema_editor.connection
    if not connection.in_atomic_block:
        raise IrreversibleError(
            "Cannot inspect local daily match history outside an atomic transaction."
        )
    if connection.vendor == "postgresql":
        table = schema_editor.quote_name(model._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE")
    if model._base_manager.using(connection.alias).exists():
        raise IrreversibleError(
            "Cannot drop local daily match schema while decision history exists."
        )


class Migration(migrations.Migration):
    """Add the append-only producer ledger with no synthetic historical decisions."""

    atomic = True

    dependencies = [
        ("simulated_trading", "0040_simulated_fee_correction"),
    ]

    operations = [
        migrations.CreateModel(
            name="LocalDailyMatchModel",
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
                ("operation_key", models.CharField(max_length=128)),
                ("request_hash", models.CharField(max_length=64)),
                ("qmt_binding_id", models.CharField(max_length=512)),
                ("session_date", models.DateField()),
                ("security_id", models.CharField(max_length=64)),
                ("asset_code", models.CharField(max_length=20)),
                ("observation_id", models.CharField(max_length=96)),
                (
                    "outcome",
                    models.CharField(
                        choices=[("matched", "Matched"), ("no_match", "No match")],
                        max_length=16,
                    ),
                ),
                ("reason_code", models.CharField(max_length=128)),
                ("source_namespace", models.CharField(max_length=128)),
                ("source_version", models.CharField(max_length=128)),
                ("event_id", models.CharField(max_length=128)),
                ("qualified_input_payload", models.JSONField()),
                ("qualified_input_hash", models.CharField(max_length=64)),
                ("observation_source_hash", models.CharField(max_length=64)),
                ("decision_payload", models.JSONField()),
                ("event_payload", models.TextField(blank=True, null=True)),
                ("recorded_at", models.DateTimeField()),
                ("record_digest", models.CharField(max_length=64)),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=models.deletion.PROTECT,
                        related_name="local_daily_match_decisions",
                        to="simulated_trading.simulatedaccountmodel",
                    ),
                ),
                (
                    "reservation",
                    models.ForeignKey(
                        on_delete=models.deletion.PROTECT,
                        related_name="local_daily_match_decisions",
                        to="simulated_trading.simulatedorderreservationmodel",
                    ),
                ),
            ],
            options={
                "verbose_name": "本地日线撮合决定",
                "verbose_name_plural": "本地日线撮合决定",
                "db_table": "simulated_local_daily_match",
                "ordering": ["account_id", "session_date", "security_id", "pk"],
                "base_manager_name": "objects",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("account", "operation_key"),
                        name="ldmatch_account_op_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("reservation", "observation_id"),
                        name="ldmatch_res_observation_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            Q(outcome="matched", event_payload__isnull=False)
                            | Q(outcome="no_match", event_payload__isnull=True)
                        ),
                        name="ldmatch_outcome_event_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            Q(request_hash__regex=r"^[0-9a-f]{64}$")
                            & Q(qualified_input_hash__regex=r"^[0-9a-f]{64}$")
                            & Q(observation_source_hash__regex=r"^[0-9a-f]{64}$")
                            & Q(record_digest__regex=r"^[0-9a-f]{64}$")
                        ),
                        name="ldmatch_hashes_sha256_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            Q(account__isnull=False)
                            & Q(reservation__isnull=False)
                            & Q(operation_key__gt="")
                            & Q(qmt_binding_id__gt="")
                            & Q(security_id__gt="")
                            & Q(asset_code__gt="")
                            & Q(observation_id__gt="")
                            & Q(reason_code__gt="")
                            & Q(source_namespace__gt="")
                            & Q(source_version__gt="")
                            & Q(event_id__gt="")
                        ),
                        name="ldmatch_identity_nonempty_ck",
                    ),
                ],
                "indexes": [
                    models.Index(
                        fields=["account", "security_id", "session_date", "outcome"],
                        name="ldmatch_capacity_idx",
                    ),
                    models.Index(
                        fields=["reservation", "outcome"],
                        name="ldmatch_order_pending_idx",
                    ),
                ],
            },
        ),
        # Reverse execution checks before CreateModel is reversed.
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_to_drop_local_daily_match_history,
        ),
    ]
