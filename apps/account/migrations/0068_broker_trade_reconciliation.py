"""Persist broker transaction reconciliation state and classify legacy rows."""

from __future__ import annotations

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps
from django.db.models import Q

_REVERSIBLE_STATES: frozenset[str] = frozenset({"not_applicable", "legacy_unverified"})


def classify_existing_broker_transactions(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Mark rows with historical broker identifiers as unverified, without rewriting facts."""
    transaction_model = apps.get_model("account", "TransactionModel")
    alias = schema_editor.connection.alias
    broker_rows = transaction_model._default_manager.using(alias).filter(
        Q(import_batch_id__isnull=False)
        | (Q(broker_trade_key__isnull=False) & ~Q(broker_trade_key=""))
        | ~Q(external_trade_id="")
    )
    broker_rows.update(
        broker_reconciliation_state="legacy_unverified",
        broker_reconciliation_details={},
    )


def refuse_unsafe_broker_reconciliation_reverse(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Refuse field removal unless all remaining classifications are reconstructable."""
    transaction_model = apps.get_model("account", "TransactionModel")
    connection = schema_editor.connection
    if connection.vendor == "postgresql":
        if not connection.in_atomic_block:
            raise IrreversibleError(
                "Cannot safely inspect broker reconciliation state outside a PostgreSQL transaction."
            )
        quoted_table = schema_editor.quote_name(transaction_model._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {quoted_table} IN ACCESS EXCLUSIVE MODE")

    rows = transaction_model._default_manager.using(connection.alias).values_list(
        "broker_reconciliation_state",
        "broker_reconciliation_details",
    )
    for state, details in rows.iterator(chunk_size=1000):
        if state not in _REVERSIBLE_STATES or details != {}:
            raise IrreversibleError(
                "Cannot remove broker reconciliation fields while "
                "non-reconstructable state or details remain."
            )


class Migration(migrations.Migration):
    """Add broker reconciliation fields and classify existing import facts."""

    atomic = True

    dependencies = [("account", "0067_transaction_fee_availability_flags")]

    operations = [
        migrations.AddField(
            model_name="transactionmodel",
            name="broker_reconciliation_state",
            field=models.CharField(
                choices=[
                    ("not_applicable", "not_applicable"),
                    ("legacy_unverified", "legacy_unverified"),
                    ("awaiting_baseline", "awaiting_baseline"),
                    ("projection_pending", "projection_pending"),
                    ("projection_blocked", "projection_blocked"),
                    ("projected", "projected"),
                    ("already_in_baseline", "already_in_baseline"),
                ],
                db_index=True,
                default="not_applicable",
                max_length=32,
                verbose_name="券商成交核对状态",
            ),
        ),
        migrations.AddField(
            model_name="transactionmodel",
            name="broker_reconciliation_details",
            field=models.JSONField(
                blank=True,
                default=dict,
                verbose_name="券商成交核对详情",
            ),
        ),
        migrations.RunPython(
            classify_existing_broker_transactions,
            reverse_code=refuse_unsafe_broker_reconciliation_reverse,
        ),
        migrations.AddConstraint(
            model_name="transactionmodel",
            constraint=models.CheckConstraint(
                condition=Q(
                    broker_reconciliation_state__in=[
                        "not_applicable",
                        "legacy_unverified",
                        "awaiting_baseline",
                        "projection_pending",
                        "projection_blocked",
                        "projected",
                        "already_in_baseline",
                    ]
                ),
                name="acct_trx_br_state_ck",
            ),
        ),
    ]
