"""Store explicit cost-basis and fee completeness without upgrading old rows."""

from __future__ import annotations

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps


def refuse_to_drop_unknown_cost_knowledge(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Keep the explicit unknown/partial state while any affected row remains."""
    connection = schema_editor.connection
    position_model = apps.get_model("simulated_trading", "PositionModel")
    trade_model = apps.get_model("simulated_trading", "SimulatedTradeModel")
    for model in (position_model, trade_model):
        if connection.vendor == "postgresql":
            if not connection.in_atomic_block:
                raise IrreversibleError(
                    "Cannot safely inspect cost knowledge outside a PostgreSQL transaction."
                )
            quoted_table = schema_editor.quote_name(model._meta.db_table)
            with connection.cursor() as cursor:
                cursor.execute(f"LOCK TABLE {quoted_table} IN ACCESS EXCLUSIVE MODE")

    unknown_positions = position_model._default_manager.using(connection.alias).filter(
        models.Q(cost_basis_known__isnull=True) | models.Q(cost_basis_known=False)
    )
    unknown_trades = trade_model._default_manager.using(connection.alias).filter(
        models.Q(fee_amounts_known__isnull=True)
        | models.Q(fee_amounts_known=False)
        | models.Q(cost_basis_known__isnull=True)
        | models.Q(cost_basis_known=False)
    )
    if unknown_positions.exists() or unknown_trades.exists():
        raise IrreversibleError(
            "Cannot remove explicit unknown or partial cost-basis knowledge while rows remain."
        )


class Migration(migrations.Migration):
    """Add nullable knowledge flags; historical numeric costs remain untouched."""

    atomic = True

    dependencies = [("simulated_trading", "0032_cash_knowledge")]

    operations = [
        migrations.AddField(
            model_name="positionmodel",
            name="cost_basis_known",
            field=models.BooleanField(
                blank=True,
                default=None,
                null=True,
                verbose_name="成本基数是否已知",
            ),
        ),
        migrations.AddField(
            model_name="simulatedtrademodel",
            name="fee_amounts_known",
            field=models.BooleanField(
                blank=True,
                default=None,
                null=True,
                verbose_name="费用金额是否完整已知",
            ),
        ),
        migrations.AddField(
            model_name="simulatedtrademodel",
            name="cost_basis_known",
            field=models.BooleanField(
                blank=True,
                default=None,
                null=True,
                verbose_name="成本基数是否已知",
            ),
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_to_drop_unknown_cost_knowledge,
        ),
    ]
