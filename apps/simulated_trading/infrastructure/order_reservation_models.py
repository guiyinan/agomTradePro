"""Durable local holds for simulated orders, separate from executed trades."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models, router
from django.db.models import Q

from .order_reservation_sqlite_precision import OrderReservationPrecisionCheck
from .simulated_account_trade_models import SimulatedAccountModel


class SimulatedOrderReservationQuerySet(models.QuerySet["SimulatedOrderReservationModel"]):
    """Deny bulk paths that bypass the account-locking reservation repository."""

    def update(self, **kwargs: Any) -> int:
        """Require resource state changes to use the repository transition."""

        raise ValidationError("模拟订单预留不可通过通用 QuerySet.update 修改")

    def bulk_create(
        self,
        objs: Iterable[SimulatedOrderReservationModel],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[SimulatedOrderReservationModel]:
        """Require new holds to pass the locked source and fee checks."""

        raise ValidationError("模拟订单预留不可通过 bulk_create 绕过资源核对")

    def bulk_update(
        self,
        objs: Iterable[SimulatedOrderReservationModel],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        """Require resource state changes to use the repository transition."""

        raise ValidationError("模拟订单预留不可通过 bulk_update 修改")

    def delete(self) -> tuple[int, dict[str, int]]:
        """Retain reservation identity and resource history permanently."""

        raise ValidationError("模拟订单预留不可通过 QuerySet.delete 删除")

    def _cancel_locked(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        reservation_id: int,
        filled_quantity: Decimal,
        cash_consumed: Decimal,
        shares_consumed: Decimal,
        cash_released: Decimal,
        shares_released: Decimal,
        cancelled_at: datetime,
        updated_at: datetime,
    ) -> int:
        """Apply one repository-computed cancellation after caller-held locks."""

        query = self.filter(
            pk=reservation_id,
            account_id=account_id,
            owner_user_id=owner_user_id,
            account__user_id=owner_user_id,
            status=SimulatedOrderReservationModel.STATUS_ACTIVE,
        )
        return models.QuerySet.update(
            query,
            status=SimulatedOrderReservationModel.STATUS_CANCELLED,
            filled_quantity=filled_quantity,
            cash_consumed=cash_consumed,
            shares_consumed=shares_consumed,
            cash_released=cash_released,
            shares_released=shares_released,
            cancelled_at=cancelled_at,
            updated_at=updated_at,
        )


SimulatedOrderReservationManager = models.Manager.from_queryset(SimulatedOrderReservationQuerySet)


class SimulatedOrderReservationModel(models.Model):
    """One immutable order request and its conserved, currently held resources."""

    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.PROTECT,
        related_name="order_reservations",
    )
    owner_user_id = models.PositiveBigIntegerField()
    idempotency_key = models.CharField(max_length=128)
    intent_payload_hash = models.CharField(max_length=64)
    reservation_request_hash = models.CharField(max_length=64)
    security_id = models.CharField(max_length=64)
    asset_code = models.CharField(max_length=20)
    asset_name = models.CharField(max_length=100)
    side = models.CharField(max_length=8, choices=[("buy", "Buy"), ("sell", "Sell")])
    asset_type = models.CharField(max_length=20)
    market = models.CharField(max_length=20)
    board = models.CharField(max_length=20)
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    limit_price = models.DecimalField(max_digits=10, decimal_places=4)
    notional = models.DecimalField(max_digits=15, decimal_places=2)
    fee_estimate = models.DecimalField(max_digits=15, decimal_places=2)
    fee_budget = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    commission_estimate = models.DecimalField(max_digits=15, decimal_places=2)
    transfer_fee_estimate = models.DecimalField(max_digits=15, decimal_places=2)
    stamp_duty_estimate = models.DecimalField(max_digits=15, decimal_places=2)
    slippage_estimate = models.DecimalField(max_digits=15, decimal_places=2)
    cash_reserved = models.DecimalField(max_digits=15, decimal_places=2)
    shares_reserved = models.DecimalField(max_digits=20, decimal_places=6)
    filled_quantity = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    cash_consumed = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    shares_consumed = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    cash_released = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    shares_released = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    fee_policy_id = models.CharField(max_length=192)
    fee_policy_version = models.PositiveIntegerField()
    fee_config_id = models.PositiveBigIntegerField()
    fee_policy_hash = models.CharField(max_length=64)
    plan_snapshot_version = models.PositiveSmallIntegerField(default=1)
    plan_snapshot = models.JSONField()
    plan_snapshot_hash = models.CharField(max_length=64)
    source_book_cash = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
    )
    source_sellable_quantity = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        null=True,
        blank=True,
    )
    source_snapshot_at = models.DateTimeField()
    market_session = models.DateField()
    settlement_lag_sessions = models.PositiveSmallIntegerField()
    settlement_release_date = models.DateField(null=True, blank=True)
    reserved_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SimulatedOrderReservationManager()

    class Meta:
        base_manager_name = "objects"
        db_table = "simulated_order_reservation"
        verbose_name = "模拟订单资源预留"
        verbose_name_plural = "模拟订单资源预留"
        ordering = ["account_id", "idempotency_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "idempotency_key"],
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
                condition=OrderReservationPrecisionCheck("amounts_conserved"),
                name="simord_amounts_conserved_ck",
            ),
            models.CheckConstraint(
                condition=OrderReservationPrecisionCheck("side_resources"),
                name="simord_side_resources_ck",
            ),
            models.CheckConstraint(
                condition=OrderReservationPrecisionCheck("state_conservation"),
                name="simord_state_conservation_ck",
            ),
            models.CheckConstraint(
                condition=OrderReservationPrecisionCheck("sqlite_envelope"),
                name="simord_sqlite_decimal_envelope_ck",
            ),
        ]
        indexes = [
            models.Index(fields=["account", "status"], name="simord_account_state_idx"),
            models.Index(
                fields=["account", "security_id", "status"], name="simord_asset_state_idx"
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Allow inserts only; repository transitions own existing reservation rows."""

        if self.pk is not None:
            using = kwargs.get("using")
            if using is None:
                using = router.db_for_write(type(self), instance=self)
            exists = type(self)._base_manager.using(using).filter(pk=self.pk).exists()
            if not exists:
                raise ValidationError("已删除的模拟订单预留不可用旧实例重新创建")
            raise ValidationError("已接受的模拟订单不可通过实例 save 修改")
        super().save(*args, **kwargs)

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Retain order keys and resource audit after cancellation or completion."""

        raise ValidationError("模拟订单预留不可删除，幂等身份和资源审计必须保留")

    def __str__(self) -> str:
        """Return a non-sensitive local reservation label."""

        return f"{self.account_id}:{self.idempotency_key} ({self.status})"
