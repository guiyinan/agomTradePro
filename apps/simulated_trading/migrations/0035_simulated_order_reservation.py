"""Persist simulated order commitments without creating trade-ledger rows."""

from __future__ import annotations

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps
from django.db.models import Q


def refuse_to_drop_order_reservations(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Keep durable idempotency and hold history when reservation rows exist."""

    reservation_model = apps.get_model(
        "simulated_trading",
        "SimulatedOrderReservationModel",
    )
    connection = schema_editor.connection
    if connection.vendor == "postgresql":
        if not connection.in_atomic_block:
            raise IrreversibleError(
                "Cannot inspect simulated order reservations outside a PostgreSQL transaction."
            )
        quoted_table = schema_editor.quote_name(reservation_model._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f"LOCK TABLE {quoted_table} IN ACCESS EXCLUSIVE MODE")
    if reservation_model._base_manager.using(connection.alias).exists():
        raise IrreversibleError(
            "Cannot drop simulated order reservations while their idempotency keys "
            "and resource audit records exist."
        )


class Migration(migrations.Migration):
    """Create a single owner-scoped durable simulated order reservation table."""

    atomic = True

    dependencies = [("simulated_trading", "0034_automatic_trading_invocation")]

    operations = [
        migrations.CreateModel(
            name="SimulatedOrderReservationModel",
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
                ("owner_user_id", models.PositiveBigIntegerField()),
                ("idempotency_key", models.CharField(max_length=128)),
                ("intent_payload_hash", models.CharField(max_length=64)),
                ("reservation_request_hash", models.CharField(max_length=64)),
                ("security_id", models.CharField(max_length=64)),
                ("asset_code", models.CharField(max_length=20)),
                ("asset_name", models.CharField(max_length=100)),
                (
                    "side",
                    models.CharField(
                        choices=[("buy", "Buy"), ("sell", "Sell")],
                        max_length=8,
                    ),
                ),
                ("asset_type", models.CharField(max_length=20)),
                ("market", models.CharField(max_length=20)),
                ("board", models.CharField(max_length=20)),
                ("quantity", models.DecimalField(decimal_places=6, max_digits=20)),
                ("limit_price", models.DecimalField(decimal_places=4, max_digits=10)),
                ("notional", models.DecimalField(decimal_places=2, max_digits=15)),
                ("fee_estimate", models.DecimalField(decimal_places=2, max_digits=15)),
                (
                    "fee_budget",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
                ),
                ("commission_estimate", models.DecimalField(decimal_places=2, max_digits=15)),
                ("transfer_fee_estimate", models.DecimalField(decimal_places=2, max_digits=15)),
                ("stamp_duty_estimate", models.DecimalField(decimal_places=2, max_digits=15)),
                ("slippage_estimate", models.DecimalField(decimal_places=2, max_digits=15)),
                ("cash_reserved", models.DecimalField(decimal_places=2, max_digits=15)),
                ("shares_reserved", models.DecimalField(decimal_places=6, max_digits=20)),
                (
                    "filled_quantity",
                    models.DecimalField(decimal_places=6, default=0, max_digits=20),
                ),
                ("cash_consumed", models.DecimalField(decimal_places=2, default=0, max_digits=15)),
                (
                    "shares_consumed",
                    models.DecimalField(decimal_places=6, default=0, max_digits=20),
                ),
                ("cash_released", models.DecimalField(decimal_places=2, default=0, max_digits=15)),
                (
                    "shares_released",
                    models.DecimalField(decimal_places=6, default=0, max_digits=20),
                ),
                ("fee_policy_id", models.CharField(max_length=192)),
                ("fee_policy_version", models.PositiveIntegerField()),
                ("fee_config_id", models.PositiveBigIntegerField()),
                ("fee_policy_hash", models.CharField(max_length=64)),
                ("plan_snapshot_version", models.PositiveSmallIntegerField(default=1)),
                ("plan_snapshot", models.JSONField()),
                ("plan_snapshot_hash", models.CharField(max_length=64)),
                (
                    "source_book_cash",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
                ),
                (
                    "source_sellable_quantity",
                    models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True),
                ),
                ("source_snapshot_at", models.DateTimeField()),
                ("market_session", models.DateField()),
                ("settlement_lag_sessions", models.PositiveSmallIntegerField()),
                ("settlement_release_date", models.DateField(blank=True, null=True)),
                ("reserved_at", models.DateTimeField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("completed", "Completed"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="active",
                        max_length=12,
                    ),
                ),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=models.deletion.PROTECT,
                        related_name="order_reservations",
                        to="simulated_trading.simulatedaccountmodel",
                    ),
                ),
            ],
            options={
                "base_manager_name": "objects",
                "db_table": "simulated_order_reservation",
                "ordering": ["account_id", "idempotency_key"],
                "verbose_name": "模拟订单资源预留",
                "verbose_name_plural": "模拟订单资源预留",
                "indexes": [
                    models.Index(
                        fields=["account", "status"],
                        name="simord_account_state_idx",
                    ),
                    models.Index(
                        fields=["account", "security_id", "status"],
                        name="simord_asset_state_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("account", "idempotency_key"),
                        name="simord_account_key_uq",
                    ),
                    models.CheckConstraint(
                        condition=(
                            Q(side="buy", fee_budget__isnull=False)
                            | Q(side="sell", fee_budget__isnull=True)
                        ),
                        name="simord_side_budget_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            Q(status="active", cancelled_at__isnull=True)
                            | Q(status="completed", cancelled_at__isnull=True)
                            | Q(
                                status="cancelled",
                                cancelled_at__isnull=False,
                                cancelled_at__gte=models.F("reserved_at"),
                            )
                        ),
                        name="simord_status_clock_ck",
                    ),
                    models.CheckConstraint(
                        condition=Q(quantity__gt=0)
                        & Q(limit_price__gt=0)
                        & Q(notional__gt=0)
                        & Q(fee_estimate__gte=0)
                        & Q(cash_reserved__gte=0)
                        & Q(shares_reserved__gte=0)
                        & Q(filled_quantity__gte=0)
                        & Q(cash_consumed__gte=0)
                        & Q(shares_consumed__gte=0)
                        & Q(cash_released__gte=0)
                        & Q(shares_released__gte=0),
                        name="simord_amounts_nonnegative_ck",
                    ),
                    models.CheckConstraint(
                        condition=Q(filled_quantity__lte=models.F("quantity"))
                        & Q(
                            cash_consumed__lte=(
                                models.F("cash_reserved") - models.F("cash_released")
                            )
                        )
                        & Q(
                            shares_consumed__lte=(
                                models.F("shares_reserved") - models.F("shares_released")
                            )
                        ),
                        name="simord_amounts_conserved_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            Q(
                                side="buy",
                                shares_reserved=0,
                                shares_consumed=0,
                                shares_released=0,
                                fee_budget__isnull=False,
                                fee_budget__gte=models.F("fee_estimate"),
                                cash_reserved=models.F("notional") + models.F("fee_budget"),
                            )
                            | Q(
                                side="sell",
                                shares_reserved=models.F("quantity"),
                                shares_consumed=models.F("filled_quantity"),
                                fee_budget__isnull=True,
                            )
                        ),
                        name="simord_side_resources_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            Q(
                                status="active",
                                cancelled_at__isnull=True,
                                filled_quantity__lt=models.F("quantity"),
                                cash_released=0,
                                shares_released=0,
                            )
                            & (
                                Q(
                                    side="buy",
                                    cash_consumed__lt=models.F("cash_reserved"),
                                )
                                | Q(
                                    side="sell",
                                    shares_consumed__lt=models.F("shares_reserved"),
                                )
                            )
                        )
                        | Q(
                            status="completed",
                            cancelled_at__isnull=True,
                            filled_quantity=models.F("quantity"),
                            cash_consumed=(models.F("cash_reserved") - models.F("cash_released")),
                            shares_consumed=(
                                models.F("shares_reserved") - models.F("shares_released")
                            ),
                        )
                        | Q(
                            status="cancelled",
                            cancelled_at__isnull=False,
                            filled_quantity__lt=models.F("quantity"),
                            cash_consumed=(models.F("cash_reserved") - models.F("cash_released")),
                            shares_consumed=(
                                models.F("shares_reserved") - models.F("shares_released")
                            ),
                        ),
                        name="simord_state_conservation_ck",
                    ),
                ],
            },
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_to_drop_order_reservations,
        ),
    ]
