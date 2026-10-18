"""Represent cash knowledge without treating real-account placeholders as balances."""

from __future__ import annotations

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps
from django.db.models import Q


def classify_existing_cash_knowledge(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Keep simulated ledger balances known and classify real balances as unverified."""

    account_model = apps.get_model("simulated_trading", "SimulatedAccountModel")
    manager = account_model._base_manager.using(schema_editor.connection.alias)
    manager.filter(account_type="simulated").update(
        cash_known=True,
        cash_reconciliation_status="simulated_ledger",
    )
    manager.filter(account_type="real").update(
        cash_known=False,
        cash_reconciliation_status="unverified",
    )


def refuse_to_drop_cash_knowledge(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Retain cash knowledge while any real or otherwise unknown cash row exists."""

    account_model = apps.get_model("simulated_trading", "SimulatedAccountModel")
    connection = schema_editor.connection
    if connection.vendor == "postgresql":
        if not connection.in_atomic_block:
            raise IrreversibleError(
                "Cannot safely inspect account cash knowledge outside a PostgreSQL transaction."
            )
        quoted_table = schema_editor.quote_name(account_model._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {quoted_table} IN ACCESS EXCLUSIVE MODE")

    unsafe_rows = account_model._base_manager.using(connection.alias).filter(
        Q(account_type="real")
        | Q(cash_known=False)
        | ~Q(cash_reconciliation_status="simulated_ledger")
    )
    if unsafe_rows.exists():
        raise IrreversibleError(
            "Cannot remove cash knowledge while real or unknown cash rows remain."
        )


class Migration(migrations.Migration):
    """Add cash knowledge while preserving existing economic values and clocks."""

    atomic = True

    dependencies = [("simulated_trading", "0031_position_valuation_knowledge")]

    operations = [
        migrations.AddField(
            model_name="simulatedaccountmodel",
            name="cash_known",
            field=models.BooleanField(default=False, verbose_name="现金余额是否有依据"),
        ),
        migrations.AddField(
            model_name="simulatedaccountmodel",
            name="cash_reconciliation_status",
            field=models.CharField(
                choices=[
                    ("simulated_ledger", "模拟账本"),
                    ("unverified", "未核实"),
                    ("quantity_only", "仅同步持仓数量"),
                ],
                default="unverified",
                max_length=24,
                verbose_name="现金核对状态",
            ),
        ),
        migrations.RunPython(
            classify_existing_cash_knowledge,
            reverse_code=refuse_to_drop_cash_knowledge,
        ),
        migrations.AddConstraint(
            model_name="simulatedaccountmodel",
            constraint=models.CheckConstraint(
                condition=(
                    Q(
                        account_type="simulated",
                        cash_known=True,
                        cash_reconciliation_status="simulated_ledger",
                    )
                    | Q(
                        account_type="real",
                        cash_known=False,
                        cash_reconciliation_status__in=("unverified", "quantity_only"),
                    )
                ),
                name="sim_account_cash_knowledge_ck",
            ),
        ),
    ]
