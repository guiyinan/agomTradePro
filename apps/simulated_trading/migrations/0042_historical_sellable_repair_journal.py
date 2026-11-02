"""Add append-only audit events for the bounded G5 sellable correction."""

from __future__ import annotations

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps
from django.db.models import Q


def refuse_to_drop_g5_repair_history(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Keep any completed repair or rollback event durably addressable."""

    connection = schema_editor.connection
    if not connection.in_atomic_block:
        raise IrreversibleError("G5 repair journal reversal requires an atomic transaction.")
    model = apps.get_model("simulated_trading", "HistoricalSellableRepairJournalModel")
    if connection.vendor == "postgresql":
        table = schema_editor.quote_name(model._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE")
    if model._base_manager.using(connection.alias).exists():
        raise IrreversibleError("Cannot drop G5 repair history while journal events exist.")


class Migration(migrations.Migration):
    """Persist each bounded repair step without tying its history to Position rows."""

    atomic = True

    dependencies = [("simulated_trading", "0041_local_daily_match_decisions")]

    operations = [
        migrations.CreateModel(
            name="HistoricalSellableRepairJournalModel",
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
                    "action",
                    models.CharField(
                        choices=[("apply", "Apply"), ("rollback", "Rollback")],
                        max_length=12,
                    ),
                ),
                ("account_id", models.PositiveBigIntegerField()),
                ("owner_user_id", models.PositiveBigIntegerField()),
                ("actor_user_id", models.PositiveBigIntegerField()),
                ("source_scope", models.CharField(max_length=32)),
                ("source_position_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("target_position_id", models.PositiveBigIntegerField()),
                ("position_mapping_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("security_id", models.CharField(max_length=64)),
                ("asset_code", models.CharField(max_length=20)),
                ("idempotency_key", models.CharField(max_length=128)),
                ("request_hash", models.CharField(max_length=64)),
                ("apply_event_id", models.PositiveBigIntegerField(blank=True, null=True)),
                (
                    "source_total_quantity",
                    models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True),
                ),
                ("target_total_quantity", models.DecimalField(decimal_places=6, max_digits=20)),
                ("source_record_updated_at", models.DateTimeField(blank=True, null=True)),
                ("evidence_cutoff_at", models.DateTimeField()),
                ("evidence_proof_hash", models.CharField(max_length=64)),
                ("before_available_quantity", models.DecimalField(decimal_places=6, max_digits=20)),
                ("before_available_quantity_known", models.BooleanField()),
                ("after_available_quantity", models.DecimalField(decimal_places=6, max_digits=20)),
                ("after_available_quantity_known", models.BooleanField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "sim_historical_sellable_repair_journal",
                "ordering": ["account_id", "pk"],
                "base_manager_name": "objects",
            },
        ),
        migrations.AddConstraint(
            model_name="historicalsellablerepairjournalmodel",
            constraint=models.UniqueConstraint(
                fields=("account_id", "idempotency_key"),
                name="sim_g5_repair_account_key_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="historicalsellablerepairjournalmodel",
            constraint=models.UniqueConstraint(
                condition=Q(action="rollback", apply_event_id__isnull=False),
                fields=("apply_event_id",),
                name="sim_g5_repair_one_rollback_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="historicalsellablerepairjournalmodel",
            constraint=models.CheckConstraint(
                condition=(
                    Q(action="apply", apply_event_id__isnull=True)
                    | Q(action="rollback", apply_event_id__gt=0)
                ),
                name="sim_g5_repair_action_link_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="historicalsellablerepairjournalmodel",
            constraint=models.CheckConstraint(
                condition=(
                    Q(account_id__gt=0)
                    & Q(owner_user_id__gt=0)
                    & Q(actor_user_id__gt=0)
                    & Q(target_position_id__gt=0)
                    & Q(idempotency_key__gt="")
                    & Q(request_hash__regex=r"^[0-9a-f]{64}$")
                    & Q(evidence_proof_hash__regex=r"^[0-9a-f]{64}$")
                    & Q(target_total_quantity__gte=0)
                    & Q(before_available_quantity__gte=0)
                    & Q(after_available_quantity__gte=0)
                    & (
                        Q(
                            source_scope="simulated_position",
                            source_position_id__isnull=True,
                            position_mapping_id__isnull=True,
                            source_total_quantity__isnull=True,
                            source_record_updated_at__isnull=True,
                        )
                        | Q(
                            source_scope="account_position_mapping",
                            source_position_id__gt=0,
                            position_mapping_id__gt=0,
                            source_total_quantity__gte=0,
                        )
                    )
                ),
                name="sim_g5_repair_identity_values_ck",
            ),
        ),
        migrations.AddIndex(
            model_name="historicalsellablerepairjournalmodel",
            index=models.Index(
                fields=["account_id", "target_position_id", "created_at"],
                name="sim_g5_repair_scope_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="historicalsellablerepairjournalmodel",
            index=models.Index(
                fields=["actor_user_id", "created_at"],
                name="sim_g5_repair_actor_idx",
            ),
        ),
        migrations.RunPython(migrations.RunPython.noop, refuse_to_drop_g5_repair_history),
    ]
