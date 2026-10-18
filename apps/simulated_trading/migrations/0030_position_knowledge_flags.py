"""Store whether imported holding quantity and first-buy date are known."""

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps
from django.db.models import Q


def refuse_to_drop_unknown_knowledge(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Keep the flags while any adopted row relies on their unknown state."""
    position_model = apps.get_model("simulated_trading", "PositionModel")
    connection = schema_editor.connection
    if connection.vendor == "postgresql":
        if not connection.in_atomic_block:
            raise IrreversibleError(
                "Cannot safely inspect unknown position flags outside a PostgreSQL transaction."
            )
        quoted_table = schema_editor.quote_name(position_model._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {quoted_table} IN ACCESS EXCLUSIVE MODE")
    unknown_rows = position_model.objects.using(connection.alias).filter(
        Q(available_quantity_known=False) | Q(first_buy_date_known=False)
    )
    if unknown_rows.exists():
        raise IrreversibleError("Cannot remove position knowledge flags while unknown rows remain.")


class Migration(migrations.Migration):
    """Add compatibility-defaulted flags without rewriting existing positions."""

    dependencies = [("simulated_trading", "0029_current_reference_plan_binding")]

    operations = [
        migrations.AddField(
            model_name="positionmodel",
            name="available_quantity_known",
            field=models.BooleanField(default=True, verbose_name="可卖数量是否已知"),
        ),
        migrations.AddField(
            model_name="positionmodel",
            name="first_buy_date_known",
            field=models.BooleanField(default=True, verbose_name="首次买入日期是否已知"),
        ),
        migrations.RunPython(migrations.RunPython.noop, refuse_to_drop_unknown_knowledge),
    ]
