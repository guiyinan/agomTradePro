"""Persist exact original settlement-plan evidence on simulated trades."""

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps
from django.db.models import Q


def prevent_dropping_settlement_plan_bindings(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Refuse reversal when rows contain evidence that this migration would remove."""

    trade_model = apps.get_model("simulated_trading", "SimulatedTradeModel")
    connection = schema_editor.connection
    alias = connection.alias
    if connection.vendor == "postgresql":
        if not connection.in_atomic_block:
            raise IrreversibleError(
                "Cannot safely check settlement-plan bindings outside a PostgreSQL transaction."
            )
        quoted_table = schema_editor.quote_name(trade_model._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {quoted_table} IN ACCESS EXCLUSIVE MODE")

    has_binding = trade_model.objects.using(alias).filter(
        ~Q(settlement_plan_binding_version=0)
        | Q(settlement_plan_binding_payload__isnull=False)
        | Q(settlement_plan_binding_hash__isnull=False)
    )
    if has_binding.exists():
        raise IrreversibleError(
            "Cannot remove settlement-plan bindings while simulated trades retain them."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("simulated_trading", "0025_fee_policy_v2_contract"),
    ]

    operations = [
        # Existing rows receive only an explicit legacy discriminator. No plan
        # evidence is inferred or backfilled from their other columns.
        migrations.AddField(
            model_name="simulatedtrademodel",
            name="settlement_plan_binding_version",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="simulatedtrademodel",
            name="settlement_plan_binding_payload",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="simulatedtrademodel",
            name="settlement_plan_binding_hash",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddConstraint(
            model_name="simulatedtrademodel",
            constraint=models.CheckConstraint(
                condition=Q(
                    settlement_plan_binding_version=0,
                    settlement_plan_binding_payload__isnull=True,
                    settlement_plan_binding_hash__isnull=True,
                )
                | Q(
                    settlement_plan_binding_version=1,
                    idempotency_key__isnull=False,
                    request_payload_hash__isnull=False,
                    settlement_plan_binding_payload__isnull=False,
                    settlement_plan_binding_hash__isnull=False,
                ),
                name="sim_trade_plan_binding_pair_ck",
            ),
        ),
        # This must remain last: on reversal Django executes this guard before
        # dropping the constraint or either evidence column.
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=prevent_dropping_settlement_plan_bindings,
        ),
    ]
