"""Append-only persistence for exact simulated order fill receipts."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models, router
from django.db.models import Q

from .order_reservation_models import SimulatedOrderReservationModel
from .simulated_account_trade_models import SimulatedTradeModel

_EVENT_KIND_FILL = "fill"
_EVENT_KIND_FINAL_FILL = "final_fill"


class SimulatedOrderFillReceiptQuerySet(models.QuerySet["SimulatedOrderFillReceiptModel"]):
    """Reject ordinary bulk mutation paths for immutable source receipts."""

    def update(self, **kwargs: Any) -> int:
        """Keep stored source and economic seals unchanged after insertion."""

        del kwargs
        raise ValidationError("模拟成交回执不能通过 QuerySet.update 修改")

    def bulk_create(
        self,
        objs: Iterable[SimulatedOrderFillReceiptModel],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[SimulatedOrderFillReceiptModel]:
        """Require receipt insertion to pass the model's append-only boundary."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("模拟成交回执不能通过 bulk_create 绕过存储校验")

    def bulk_update(
        self,
        objs: Iterable[SimulatedOrderFillReceiptModel],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        """Reject mutation of existing receipt rows through bulk_update."""

        del objs, fields, batch_size
        raise ValidationError("模拟成交回执不能通过 bulk_update 修改")

    def delete(self) -> tuple[int, dict[str, int]]:
        """Retain source evidence and its stable replay identity permanently."""

        raise ValidationError("模拟成交回执不能通过 QuerySet.delete 删除")


SimulatedOrderFillReceiptManager = models.Manager.from_queryset(SimulatedOrderFillReceiptQuerySet)


class SimulatedOrderFillReceiptModel(models.Model):
    """Bind one immutable source event and economics snapshot to one Trade row."""

    EVENT_KIND_FILL = _EVENT_KIND_FILL
    EVENT_KIND_FINAL_FILL = _EVENT_KIND_FINAL_FILL
    EVENT_KIND_CHOICES = [
        (EVENT_KIND_FILL, "Fill"),
        (EVENT_KIND_FINAL_FILL, "Final fill"),
    ]

    reservation = models.ForeignKey(
        SimulatedOrderReservationModel,
        on_delete=models.PROTECT,
        related_name="fill_receipts",
    )
    trade = models.OneToOneField(
        SimulatedTradeModel,
        on_delete=models.PROTECT,
        related_name="fill_receipt",
    )
    fill_sequence = models.PositiveIntegerField()
    source_namespace = models.CharField(max_length=128)
    source_version = models.CharField(max_length=128)
    source_event_id = models.CharField(max_length=128)
    event_kind = models.CharField(max_length=16, choices=EVENT_KIND_CHOICES)
    source_event_payload = models.JSONField()
    # This is the source adapter's original event/evidence digest, not a hash
    # of the typed payload JSON persisted in source_event_payload.
    source_event_payload_hash = models.CharField(max_length=64)
    # This is the local canonical digest of the complete typed source payload.
    source_event_snapshot_hash = models.CharField(max_length=64)
    economic_request_hash = models.CharField(max_length=64)
    economics_snapshot_hash = models.CharField(max_length=64)
    plan_snapshot_hash = models.CharField(max_length=64)
    economics_payload = models.JSONField()
    # The receipt seal binds the stable locator and the source/economics seals;
    # it deliberately does not depend on this row's or Trade's generated PK.
    receipt_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    receipt_version = models.PositiveSmallIntegerField(default=1)
    initial_position_mark_evidence = models.JSONField(null=True, blank=True)

    objects = SimulatedOrderFillReceiptManager()

    class Meta:
        base_manager_name = "objects"
        db_table = "simulated_order_fill_receipt"
        verbose_name = "模拟订单成交回执"
        verbose_name_plural = "模拟订单成交回执"
        ordering = ["reservation_id", "fill_sequence"]
        constraints = [
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
            models.CheckConstraint(
                condition=(
                    Q(receipt_version=1, initial_position_mark_evidence__isnull=True)
                    | Q(receipt_version=2, initial_position_mark_evidence__isnull=False)
                ),
                name="simfill_version_mark_pair_ck",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Insert a receipt exactly once; only a dedicated writer may create it."""

        if self.pk is not None:
            using = kwargs.get("using")
            if using is None:
                using = router.db_for_write(type(self), instance=self)
            exists = type(self)._base_manager.using(using).filter(pk=self.pk).exists()
            if exists:
                raise ValidationError("模拟成交回执不可通过实例 save 修改")
            raise ValidationError("模拟成交回执不可使用预置主键插入")
        super().save(*args, **kwargs)

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Keep source events and their replay identity after application."""

        del using, keep_parents
        raise ValidationError("模拟成交回执不可删除")

    def __str__(self) -> str:
        """Return the receipt's stable reservation sequence label."""

        return f"{self.reservation_id}:{self.fill_sequence}"
