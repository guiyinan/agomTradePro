"""Store optional fill-settlement release proof on the owning V4 trade."""

from __future__ import annotations

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps
from django.db.models import Q
from django.db.models.functions import Length
from django.db.models.lookups import Exact

_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"


def refuse_to_drop_order_fill_release_proof(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Preserve any trade row carrying release-proof payload or hash evidence."""

    trade_model = apps.get_model("simulated_trading", "SimulatedTradeModel")
    connection = schema_editor.connection
    if not connection.in_atomic_block:
        raise IrreversibleError(
            "Cannot inspect simulated order-fill release proof outside a transaction."
        )
    if connection.vendor == "postgresql":
        quoted_table = schema_editor.quote_name(trade_model._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {quoted_table} IN ACCESS EXCLUSIVE MODE")
    proof_exists = (
        trade_model._base_manager.using(connection.alias)
        .filter(
            Q(settlement_release_proof_payload__isnull=False)
            | Q(settlement_release_proof_hash__isnull=False)
        )
        .exists()
    )
    if proof_exists:
        raise IrreversibleError(
            "Cannot drop simulated order-fill release proof while proof evidence exists."
        )


class Migration(migrations.Migration):
    """Add nullable release-proof evidence without changing historical trades."""

    atomic = True

    dependencies = [
        ("simulated_trading", "0038_simulated_order_fill_initial_mark"),
    ]

    operations = [
        migrations.AddField(
            model_name="simulatedtrademodel",
            name="settlement_release_proof_payload",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name="simulatedtrademodel",
            name="settlement_release_proof_hash",
            field=models.CharField(blank=True, default=None, max_length=64, null=True),
        ),
        migrations.AddConstraint(
            model_name="simulatedtrademodel",
            constraint=models.CheckConstraint(
                condition=(
                    Q(
                        settlement_release_proof_payload__isnull=True,
                        settlement_release_proof_hash__isnull=True,
                    )
                    | (
                        Q(
                            settlement_release_proof_payload__isnull=False,
                            settlement_release_proof_hash__isnull=False,
                            settlement_release_proof_hash__regex=_SHA256_HEX_PATTERN,
                            action="buy",
                            settlement_plan_binding_version=4,
                            settlement_status="released",
                        )
                        & Q(
                            Exact(
                                Length("settlement_release_proof_hash"),
                                models.Value(64),
                            )
                        )
                    )
                ),
                name="sim_trade_release_proof_ck",
            ),
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_to_drop_order_fill_release_proof,
        ),
    ]
