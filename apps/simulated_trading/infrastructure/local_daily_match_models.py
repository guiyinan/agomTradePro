"""Append-only persistence for qualified daily-interval match decisions."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Any, NoReturn

from django.core.exceptions import ValidationError
from django.db import models, router
from django.db.models import Q

from .order_reservation_models import SimulatedOrderReservationModel
from .simulated_account_trade_models import SimulatedAccountModel


class LocalDailyMatchQuerySet(models.QuerySet["LocalDailyMatchModel"]):
    """Reject ordinary mutation paths that could rewrite or erase match history."""

    def update(self, **kwargs: Any) -> int:
        """Preserve the original policy/source decision after insertion."""

        del kwargs
        raise ValidationError("本地日线撮合记录不可通过 QuerySet.update 修改")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        """Block Django's lower-level update path as well as the public method."""

        del values
        raise ValidationError("本地日线撮合记录不可通过 QuerySet.update 修改")

    def bulk_create(
        self,
        objs: Iterable[LocalDailyMatchModel],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[LocalDailyMatchModel]:
        """Require decisions to pass the repository's account-lock boundary."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("本地日线撮合记录不可通过 bulk_create 绕过存储校验")

    def bulk_update(
        self,
        objs: Iterable[LocalDailyMatchModel],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        """Retain all source and policy evidence exactly as first written."""

        del objs, fields, batch_size
        raise ValidationError("本地日线撮合记录不可通过 bulk_update 修改")

    def delete(self) -> tuple[int, dict[str, int]]:
        """Retain matched, no-match and unconsumed decision history permanently."""

        raise ValidationError("本地日线撮合记录不可通过 QuerySet.delete 删除")

    def _raw_delete(self, using: str | None) -> int:
        """Prevent QuerySet internals from bypassing the append-only delete guard."""

        del using
        raise ValidationError("本地日线撮合记录不可通过原始批量删除移除")


LocalDailyMatchManager = models.Manager.from_queryset(LocalDailyMatchQuerySet)


class LocalDailyMatchModel(models.Model):
    """One immutable account operation and its exact daily match decision."""

    OUTCOME_MATCHED = "matched"
    OUTCOME_NO_MATCH = "no_match"
    OUTCOME_CHOICES = [
        (OUTCOME_MATCHED, "Matched"),
        (OUTCOME_NO_MATCH, "No match"),
    ]

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.PROTECT,
        related_name="local_daily_match_decisions",
    )
    reservation = models.ForeignKey(
        SimulatedOrderReservationModel,
        on_delete=models.PROTECT,
        related_name="local_daily_match_decisions",
    )
    operation_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    qmt_binding_id = models.CharField(max_length=512)
    session_date = models.DateField()
    security_id = models.CharField(max_length=64)
    asset_code = models.CharField(max_length=20)
    observation_id = models.CharField(max_length=96)
    outcome = models.CharField(max_length=16, choices=OUTCOME_CHOICES)
    reason_code = models.CharField(max_length=128)
    source_namespace = models.CharField(max_length=128)
    source_version = models.CharField(max_length=128)
    event_id = models.CharField(max_length=128)
    qualified_input_payload = models.JSONField()
    qualified_input_hash = models.CharField(max_length=64)
    observation_source_hash = models.CharField(max_length=64)
    decision_payload = models.JSONField()
    event_payload = models.TextField(null=True, blank=True)
    recorded_at = models.DateTimeField()
    record_digest = models.CharField(max_length=64)

    objects = LocalDailyMatchManager()

    class Meta:
        base_manager_name = "objects"
        db_table = "simulated_local_daily_match"
        verbose_name = "本地日线撮合决定"
        verbose_name_plural = "本地日线撮合决定"
        ordering = ["account_id", "session_date", "security_id", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=("account", "operation_key"),
                name="ldmatch_account_op_uq",
            ),
            models.UniqueConstraint(
                fields=("reservation", "observation_id"),
                name="ldmatch_res_observation_uq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        outcome="matched",
                        event_payload__isnull=False,
                    )
                    | Q(
                        outcome="no_match",
                        event_payload__isnull=True,
                    )
                ),
                name="ldmatch_outcome_event_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(request_hash__regex=r"^[0-9a-f]{64}$")
                    & Q(qualified_input_hash__regex=r"^[0-9a-f]{64}$")
                    & Q(observation_source_hash__regex=r"^[0-9a-f]{64}$")
                    & Q(record_digest__regex=r"^[0-9a-f]{64}$")
                ),
                name="ldmatch_hashes_sha256_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(account__isnull=False)
                    & Q(reservation__isnull=False)
                    & Q(operation_key__gt="")
                    & Q(qmt_binding_id__gt="")
                    & Q(security_id__gt="")
                    & Q(asset_code__gt="")
                    & Q(observation_id__gt="")
                    & Q(reason_code__gt="")
                    & Q(source_namespace__gt="")
                    & Q(source_version__gt="")
                    & Q(event_id__gt="")
                ),
                name="ldmatch_identity_nonempty_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("account", "security_id", "session_date", "outcome"),
                name="ldmatch_capacity_idx",
            ),
            models.Index(
                fields=("reservation", "outcome"),
                name="ldmatch_order_pending_idx",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Insert once; updates and caller-supplied primary keys are prohibited."""

        if self.pk is not None:
            using = kwargs.get("using")
            if using is None:
                using = router.db_for_write(type(self), instance=self)
            exists = type(self)._base_manager.using(using).filter(pk=self.pk).exists()
            if exists:
                raise ValidationError("本地日线撮合记录不可通过实例 save 修改")
            raise ValidationError("本地日线撮合记录不可使用预置主键插入")
        super().save(*args, **kwargs)

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Keep source qualification and account match history immutable."""

        del using, keep_parents
        raise ValidationError("本地日线撮合记录不可删除")

    def __str__(self) -> str:
        """Return the stable account operation label without source contents."""

        return f"{self.account_id}:{self.operation_key} ({self.outcome})"


__all__ = ("LocalDailyMatchModel",)
