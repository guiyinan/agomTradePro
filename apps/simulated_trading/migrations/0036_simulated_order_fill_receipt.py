"""Store immutable local simulated fill receipts and retain their history."""

from __future__ import annotations

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps
from django.db.models import Q

_FILL_BINDING_SCHEMA = "simulated-order-fill-binding.v4"
_EVENT_KIND_FILL = "fill"
_EVENT_KIND_FINAL_FILL = "final_fill"
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"


def refuse_to_drop_simulated_order_fills(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Keep any persisted fill receipt or V4 trade binding during reversal."""

    receipt_model = apps.get_model(
        "simulated_trading",
        "SimulatedOrderFillReceiptModel",
    )
    trade_model = apps.get_model("simulated_trading", "SimulatedTradeModel")
    connection = schema_editor.connection
    if connection.vendor == "postgresql":
        if not connection.in_atomic_block:
            raise IrreversibleError(
                "Cannot inspect simulated order fills outside a PostgreSQL transaction."
            )
        quoted_trade_table = schema_editor.quote_name(trade_model._meta.db_table)
        quoted_receipt_table = schema_editor.quote_name(receipt_model._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(
                f"LOCK TABLE {quoted_trade_table}, {quoted_receipt_table} "
                "IN ACCESS EXCLUSIVE MODE"
            )
    alias = connection.alias
    if (
        receipt_model._base_manager.using(alias).exists()
        or trade_model._base_manager.using(alias).filter(settlement_plan_binding_version=4).exists()
    ):
        raise IrreversibleError(
            "Cannot drop simulated order fill history while receipt or V4 trade rows exist."
        )


class Migration(migrations.Migration):
    """Add append-only receipt storage without backfilling earlier trades."""

    atomic = True

    dependencies = [("simulated_trading", "0035_simulated_order_reservation")]

    operations = [
        migrations.CreateModel(
            name="SimulatedOrderFillReceiptModel",
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
                ("fill_sequence", models.PositiveIntegerField()),
                ("source_namespace", models.CharField(max_length=128)),
                ("source_version", models.CharField(max_length=128)),
                ("source_event_id", models.CharField(max_length=128)),
                (
                    "event_kind",
                    models.CharField(
                        choices=[("fill", "Fill"), ("final_fill", "Final fill")],
                        max_length=16,
                    ),
                ),
                ("source_event_payload", models.JSONField()),
                ("source_event_payload_hash", models.CharField(max_length=64)),
                ("source_event_snapshot_hash", models.CharField(max_length=64)),
                ("economic_request_hash", models.CharField(max_length=64)),
                ("economics_snapshot_hash", models.CharField(max_length=64)),
                ("plan_snapshot_hash", models.CharField(max_length=64)),
                ("economics_payload", models.JSONField()),
                ("receipt_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "reservation",
                    models.ForeignKey(
                        on_delete=models.deletion.PROTECT,
                        related_name="fill_receipts",
                        to="simulated_trading.simulatedorderreservationmodel",
                    ),
                ),
                (
                    "trade",
                    models.OneToOneField(
                        on_delete=models.deletion.PROTECT,
                        related_name="fill_receipt",
                        to="simulated_trading.simulatedtrademodel",
                    ),
                ),
            ],
            options={
                "verbose_name": "模拟订单成交回执",
                "verbose_name_plural": "模拟订单成交回执",
                "db_table": "simulated_order_fill_receipt",
                "ordering": ["reservation_id", "fill_sequence"],
                "base_manager_name": "objects",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("reservation", "source_namespace", "source_event_id"),
                        name="simfill_res_source_event_uq",
                    ),
                    models.UniqueConstraint(
                        fields=("reservation", "fill_sequence"),
                        name="simfill_res_sequence_uq",
                    ),
                    models.CheckConstraint(
                        condition=Q(fill_sequence__gt=0),
                        name="simfill_sequence_positive_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            Q(source_namespace__gt="")
                            & Q(source_version__gt="")
                            & Q(source_event_id__gt="")
                        ),
                        name="simfill_locator_nonempty_ck",
                    ),
                    models.CheckConstraint(
                        condition=Q(event_kind__in=(_EVENT_KIND_FILL, _EVENT_KIND_FINAL_FILL)),
                        name="simfill_kind_known_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            Q(source_event_payload_hash__regex=r"^[0-9a-f]{64}$")
                            & Q(source_event_snapshot_hash__regex=r"^[0-9a-f]{64}$")
                            & Q(economic_request_hash__regex=r"^[0-9a-f]{64}$")
                            & Q(economics_snapshot_hash__regex=r"^[0-9a-f]{64}$")
                            & Q(plan_snapshot_hash__regex=r"^[0-9a-f]{64}$")
                            & Q(receipt_hash__regex=r"^[0-9a-f]{64}$")
                        ),
                        name="simfill_hashes_sha256_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            Q(source_event_payload__has_key="source_namespace")
                            & Q(source_event_payload__has_key="source_version")
                            & Q(source_event_payload__has_key="source_event_id")
                            & Q(source_event_payload__has_key="event_payload_hash")
                            & Q(source_event_payload__has_key="source_snapshot_id")
                            & Q(source_event_payload__has_key="source_snapshot_hash")
                            & Q(source_event_payload__has_key="reservation_id")
                            & Q(source_event_payload__has_key="account_id")
                            & Q(source_event_payload__has_key="user_id")
                            & Q(source_event_payload__has_key="order_idempotency_key")
                            & Q(source_event_payload__has_key="intent_payload_hash")
                            & Q(source_event_payload__has_key="reservation_request_hash")
                            & Q(source_event_payload__has_key="plan_snapshot_hash")
                            & Q(source_event_payload__has_key="security_id")
                            & Q(source_event_payload__has_key="asset_code")
                            & Q(source_event_payload__has_key="side")
                            & Q(source_event_payload__has_key="event_kind")
                            & Q(source_event_payload__has_key="quantity")
                            & Q(source_event_payload__has_key="price")
                            & Q(source_event_payload__has_key="occurred_at")
                            & Q(source_event_payload__has_key="source_observed_at")
                            & Q(source_event_payload__has_key="source_available_at")
                            & Q(source_event_payload__has_key="recorded_at")
                        ),
                        name="simfill_source_payload_shape_ck",
                    ),
                    models.CheckConstraint(
                        condition=(
                            Q(economics_payload__has_key="schema")
                            & Q(economics_payload__has_key="fill_event_id")
                            & Q(economics_payload__has_key="reservation_identity")
                            & Q(economics_payload__has_key="user_id")
                            & Q(economics_payload__has_key="intent_payload_hash")
                            & Q(economics_payload__has_key="fee_policy_hash")
                            & Q(economics_payload__has_key="side")
                            & Q(economics_payload__has_key="asset_code")
                            & Q(economics_payload__has_key="asset_type")
                            & Q(economics_payload__has_key="market")
                            & Q(economics_payload__has_key="board")
                            & Q(economics_payload__has_key="limit_price")
                            & Q(economics_payload__has_key="fill_occurred_at")
                            & Q(economics_payload__has_key="close_order")
                            & Q(economics_payload__has_key="quantity")
                            & Q(economics_payload__has_key="price")
                            & Q(economics_payload__has_key="gross_amount")
                            & Q(economics_payload__has_key="prior")
                            & Q(economics_payload__has_key="cumulative_state")
                            & Q(economics_payload__has_key="incremental_fees")
                            & Q(economics_payload__has_key="payload_hash")
                        ),
                        name="simfill_economics_payload_shape_ck",
                    ),
                ],
            },
        ),
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
                )
                | (
                    Q(
                        settlement_plan_binding_version=4,
                        settlement_plan_binding_payload__schema=_FILL_BINDING_SCHEMA,
                        idempotency_key__isnull=False,
                        request_payload_hash__isnull=False,
                        settlement_plan_binding_payload__isnull=False,
                        settlement_plan_binding_hash__isnull=False,
                        settlement_exchange__isnull=False,
                        settlement_plan_binding_payload__reservation_id__gt=0,
                        settlement_plan_binding_payload__fill_sequence__gt=0,
                        settlement_plan_binding_payload__side__in=("buy", "sell"),
                        idempotency_key__gt="",
                        request_payload_hash__regex=_SHA256_HEX_PATTERN,
                        settlement_plan_binding_hash__regex=_SHA256_HEX_PATTERN,
                        settlement_exchange__gt="",
                        settlement_plan_binding_payload__intent_payload_hash__regex=(
                            _SHA256_HEX_PATTERN
                        ),
                        settlement_plan_binding_payload__reservation_request_hash__regex=(
                            _SHA256_HEX_PATTERN
                        ),
                        settlement_plan_binding_payload__plan_snapshot_hash__regex=(
                            _SHA256_HEX_PATTERN
                        ),
                        settlement_plan_binding_payload__fee_policy_hash__regex=(
                            _SHA256_HEX_PATTERN
                        ),
                        settlement_plan_binding_payload__source_event_payload_hash__regex=(
                            _SHA256_HEX_PATTERN
                        ),
                        settlement_plan_binding_payload__source_event_snapshot_hash__regex=(
                            _SHA256_HEX_PATTERN
                        ),
                        settlement_plan_binding_payload__economic_request_hash__regex=(
                            _SHA256_HEX_PATTERN
                        ),
                        settlement_plan_binding_payload__economics_snapshot_hash__regex=(
                            _SHA256_HEX_PATTERN
                        ),
                        settlement_plan_binding_payload__receipt_hash__regex=(_SHA256_HEX_PATTERN),
                    )
                    & Q(settlement_plan_binding_payload__has_key="schema")
                    & Q(settlement_plan_binding_payload__has_key="reservation_id")
                    & Q(settlement_plan_binding_payload__has_key="intent_payload_hash")
                    & Q(settlement_plan_binding_payload__has_key="reservation_request_hash")
                    & Q(settlement_plan_binding_payload__has_key="plan_snapshot_hash")
                    & Q(settlement_plan_binding_payload__has_key="fee_policy_hash")
                    & Q(settlement_plan_binding_payload__has_key="source_namespace")
                    & Q(settlement_plan_binding_payload__has_key="source_version")
                    & Q(settlement_plan_binding_payload__has_key="source_event_id")
                    & Q(settlement_plan_binding_payload__has_key="fill_sequence")
                    & Q(settlement_plan_binding_payload__has_key="side")
                    & Q(settlement_plan_binding_payload__has_key="source_event_payload_hash")
                    & Q(settlement_plan_binding_payload__has_key="source_event_snapshot_hash")
                    & Q(settlement_plan_binding_payload__has_key="economic_request_hash")
                    & Q(settlement_plan_binding_payload__has_key="economics_snapshot_hash")
                    & Q(settlement_plan_binding_payload__has_key="receipt_hash")
                    & ~Q(settlement_plan_binding_payload__schema=None)
                    & ~Q(settlement_plan_binding_payload__schema="")
                    & ~Q(settlement_plan_binding_payload__source_namespace=None)
                    & ~Q(settlement_plan_binding_payload__source_namespace="")
                    & ~Q(settlement_plan_binding_payload__source_version=None)
                    & ~Q(settlement_plan_binding_payload__source_version="")
                    & ~Q(settlement_plan_binding_payload__source_event_id=None)
                    & ~Q(settlement_plan_binding_payload__source_event_id="")
                    & ~Q(settlement_plan_binding_payload__reservation_id=None)
                    & ~Q(settlement_plan_binding_payload__reservation_id="")
                    & ~Q(settlement_plan_binding_payload__fill_sequence=None)
                    & ~Q(settlement_plan_binding_payload__fill_sequence="")
                    & ~Q(settlement_plan_binding_payload__side=None)
                    & ~Q(settlement_plan_binding_payload__side="")
                    & ~Q(settlement_plan_binding_payload__intent_payload_hash=None)
                    & ~Q(settlement_plan_binding_payload__intent_payload_hash="")
                    & ~Q(settlement_plan_binding_payload__reservation_request_hash=None)
                    & ~Q(settlement_plan_binding_payload__reservation_request_hash="")
                    & ~Q(settlement_plan_binding_payload__plan_snapshot_hash=None)
                    & ~Q(settlement_plan_binding_payload__plan_snapshot_hash="")
                    & ~Q(settlement_plan_binding_payload__fee_policy_hash=None)
                    & ~Q(settlement_plan_binding_payload__fee_policy_hash="")
                    & ~Q(settlement_plan_binding_payload__source_event_payload_hash=None)
                    & ~Q(settlement_plan_binding_payload__source_event_payload_hash="")
                    & ~Q(settlement_plan_binding_payload__source_event_snapshot_hash=None)
                    & ~Q(settlement_plan_binding_payload__source_event_snapshot_hash="")
                    & ~Q(settlement_plan_binding_payload__economic_request_hash=None)
                    & ~Q(settlement_plan_binding_payload__economic_request_hash="")
                    & ~Q(settlement_plan_binding_payload__economics_snapshot_hash=None)
                    & ~Q(settlement_plan_binding_payload__economics_snapshot_hash="")
                    & ~Q(settlement_plan_binding_payload__receipt_hash=None)
                    & ~Q(settlement_plan_binding_payload__receipt_hash="")
                ),
                name="sim_trade_plan_binding_pair_ck",
            ),
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_to_drop_simulated_order_fills,
        ),
    ]
