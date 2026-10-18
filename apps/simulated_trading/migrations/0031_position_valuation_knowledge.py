"""Add an explicit knowledge flag for position valuation state."""

from __future__ import annotations

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps


def refuse_to_drop_unknown_valuation(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Retain valuation knowledge while any position has unknown valuation."""
    position_model = apps.get_model("simulated_trading", "PositionModel")
    connection = schema_editor.connection
    if connection.vendor == "postgresql":
        if not connection.in_atomic_block:
            raise IrreversibleError(
                "Cannot safely inspect unknown position valuation outside a PostgreSQL transaction."
            )
        quoted_table = schema_editor.quote_name(position_model._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {quoted_table} IN ACCESS EXCLUSIVE MODE")

    unknown_rows = position_model._default_manager.using(connection.alias).filter(
        valuation_known=False
    )
    if unknown_rows.exists():
        raise IrreversibleError(
            "Cannot remove position valuation knowledge flag while unknown rows remain."
        )


class Migration(migrations.Migration):
    """Add a compatibility-defaulted flag without rewriting position facts."""

    atomic = True

    dependencies = [("simulated_trading", "0030_position_knowledge_flags")]

    operations = [
        migrations.AddField(
            model_name="positionmodel",
            name="valuation_known",
            field=models.BooleanField(default=True, verbose_name="持仓估值是否已知"),
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_to_drop_unknown_valuation,
        ),
    ]
