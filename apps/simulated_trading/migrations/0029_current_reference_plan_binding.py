"""Allow exact current-reference V3 bindings without rewriting stored rows."""

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps
from django.db.models import Q


def prevent_dropping_current_reference_bindings(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Keep V3 binding rows intact when reversing the version check."""

    trade_model = apps.get_model("simulated_trading", "SimulatedTradeModel")
    connection = schema_editor.connection
    if connection.vendor == "postgresql":
        if not connection.in_atomic_block:
            raise IrreversibleError(
                "Cannot safely check current-reference bindings outside a PostgreSQL transaction."
            )
        quoted_table = schema_editor.quote_name(trade_model._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {quoted_table} IN ACCESS EXCLUSIVE MODE")

    has_current_reference_binding = trade_model.objects.using(connection.alias).filter(
        settlement_plan_binding_version=3
    )
    if has_current_reference_binding.exists():
        raise IrreversibleError(
            "Cannot remove current-reference binding support while simulated trades retain it."
        )


class Migration(migrations.Migration):
    """Add V3 as a new stored discriminator without changing existing evidence."""

    dependencies = [("simulated_trading", "0028_preserve_trade_execution_time")]

    operations = [
        migrations.RemoveConstraint(
            model_name="simulatedtrademodel",
            name="sim_trade_plan_binding_pair_ck",
        ),
        migrations.AddConstraint(
            model_name="simulatedtrademodel",
            constraint=models.CheckConstraint(
                condition=Q(
                    settlement_plan_binding_version=0,
                    settlement_plan_binding_payload__isnull=True,
                    settlement_plan_binding_hash__isnull=True,
                    settlement_exchange__isnull=True,
                )
                | Q(
                    settlement_plan_binding_version=1,
                    idempotency_key__isnull=False,
                    request_payload_hash__isnull=False,
                    settlement_plan_binding_payload__isnull=False,
                    settlement_plan_binding_hash__isnull=False,
                    settlement_exchange__isnull=True,
                )
                | Q(
                    settlement_plan_binding_version=2,
                    idempotency_key__isnull=False,
                    request_payload_hash__isnull=False,
                    settlement_plan_binding_payload__isnull=False,
                    settlement_plan_binding_hash__isnull=False,
                    settlement_exchange__isnull=False,
                )
                | Q(
                    settlement_plan_binding_version=3,
                    idempotency_key__isnull=False,
                    request_payload_hash__isnull=False,
                    settlement_plan_binding_payload__isnull=False,
                    settlement_plan_binding_hash__isnull=False,
                    settlement_exchange__isnull=False,
                ),
                name="sim_trade_plan_binding_pair_ck",
            ),
        ),
        # On reversal this guard runs before the narrowed constraint is restored.
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=prevent_dropping_current_reference_bindings,
        ),
    ]
