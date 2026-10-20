"""Add versioned initial mark evidence to immutable order-fill receipts."""

from __future__ import annotations

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps
from django.db.models import Q


def refuse_to_drop_initial_mark_evidence(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Retain receipts whose version or initial mark evidence is not legacy V1."""

    receipt_model = apps.get_model("simulated_trading", "SimulatedOrderFillReceiptModel")
    connection = schema_editor.connection
    if not connection.in_atomic_block:
        raise IrreversibleError(
            "Cannot inspect simulated fill receipt versions outside a transaction."
        )
    if connection.vendor == "postgresql":
        quoted_table = schema_editor.quote_name(receipt_model._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {quoted_table} IN ACCESS EXCLUSIVE MODE")
    if (
        receipt_model._base_manager.using(connection.alias)
        .exclude(
            receipt_version=1,
            initial_position_mark_evidence__isnull=True,
        )
        .exists()
    ):
        raise IrreversibleError(
            "Cannot drop simulated fill receipt version or initial mark evidence while non-V1 history exists."
        )


class Migration(migrations.Migration):
    """Add receipt version and nullable first-mark evidence without changing legacy rows."""

    atomic = True

    dependencies = [("simulated_trading", "0037_simulated_order_reservation_sqlite_precision")]

    operations = [
        migrations.AddField(
            model_name="simulatedorderfillreceiptmodel",
            name="receipt_version",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="simulatedorderfillreceiptmodel",
            name="initial_position_mark_evidence",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="simulatedorderfillreceiptmodel",
            constraint=models.CheckConstraint(
                condition=(
                    Q(receipt_version=1, initial_position_mark_evidence__isnull=True)
                    | Q(receipt_version=2, initial_position_mark_evidence__isnull=False)
                ),
                name="simfill_version_mark_pair_ck",
            ),
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_to_drop_initial_mark_evidence,
        ),
    ]
