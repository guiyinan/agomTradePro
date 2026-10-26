"""Append-only fee-correction events kept separate from Trade and fill receipts."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, router
from django.db.models import Q
from django.db.models.functions import Length
from django.db.models.lookups import Exact

from .simulated_account_trade_models import SimulatedAccountModel, SimulatedTradeModel

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


def _is_sha256(value: object) -> bool:
    """Return whether one value is an exact lowercase SHA-256 digest."""

    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


class SimulatedFeeCorrectionEventQuerySet(models.QuerySet["SimulatedFeeCorrectionEventModel"]):
    """Reject ordinary bulk mutation of source-qualified correction events."""

    def update(self, **kwargs: Any) -> int:
        """Correction history is immutable after insertion."""

        del kwargs
        raise ValidationError("模拟费用更正事件不可通过 QuerySet.update 修改")

    def bulk_create(
        self,
        objs: Iterable[SimulatedFeeCorrectionEventModel],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[SimulatedFeeCorrectionEventModel]:
        """Require event insertion to pass its dedicated atomic repository."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("模拟费用更正事件不可通过 bulk_create 绕过存储校验")

    def bulk_update(
        self,
        objs: Iterable[SimulatedFeeCorrectionEventModel],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        """Reject bulk replacement of prior source, actor, or accounting facts."""

        del objs, fields, batch_size
        raise ValidationError("模拟费用更正事件不可通过 bulk_update 修改")

    def delete(self) -> tuple[int, dict[str, int]]:
        """Keep correction history and its idempotency chain permanently."""

        raise ValidationError("模拟费用更正事件不可通过 QuerySet.delete 删除")


SimulatedFeeCorrectionEventManager = models.Manager.from_queryset(
    SimulatedFeeCorrectionEventQuerySet
)


class SimulatedFeeCorrectionEventModel(models.Model):
    """Immutable evidence, revision, and cash-delta event for one simulated Trade."""

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.PROTECT,
        related_name="fee_correction_events",
    )
    trade = models.ForeignKey(
        SimulatedTradeModel,
        on_delete=models.PROTECT,
        related_name="fee_correction_events",
    )
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="simulated_fee_correction_events",
    )
    revision = models.PositiveIntegerField()
    account_revision = models.PositiveBigIntegerField()
    account_predecessor_hash = models.CharField(max_length=64)
    account_prefix_hash = models.CharField(max_length=64)
    previous_event = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="successor_events",
    )
    idempotency_key = models.CharField(max_length=128)
    request_payload_hash = models.CharField(max_length=64)
    trade_snapshot_hash = models.CharField(max_length=64)
    receipt_snapshot_hash = models.CharField(max_length=64, null=True, blank=True)

    source_namespace = models.CharField(max_length=128)
    source_record_id = models.CharField(max_length=192)
    verifier_identity = models.CharField(max_length=128)
    source_evidence_hash = models.CharField(max_length=64)
    source_payload_hash = models.CharField(max_length=64)
    source_observed_at = models.DateTimeField()
    evidence_verified_at = models.DateTimeField()

    authority_identity = models.CharField(max_length=128)
    authority_record_id = models.CharField(max_length=192)
    authority_hash = models.CharField(max_length=64)
    authority_snapshot_json = models.JSONField(null=True, blank=True)
    authority_snapshot_sha256 = models.CharField(max_length=64, null=True, blank=True)

    previous_commission = models.DecimalField(max_digits=10, decimal_places=2)
    previous_transfer_fee = models.DecimalField(max_digits=10, decimal_places=2)
    previous_stamp_duty = models.DecimalField(max_digits=10, decimal_places=2)
    revised_commission = models.DecimalField(max_digits=10, decimal_places=2)
    revised_transfer_fee = models.DecimalField(max_digits=10, decimal_places=2)
    revised_stamp_duty = models.DecimalField(max_digits=10, decimal_places=2)
    original_slippage = models.DecimalField(max_digits=10, decimal_places=2)
    commission_delta = models.DecimalField(max_digits=15, decimal_places=2)
    transfer_fee_delta = models.DecimalField(max_digits=15, decimal_places=2)
    stamp_duty_delta = models.DecimalField(max_digits=15, decimal_places=2)
    total_fee_delta = models.DecimalField(max_digits=15, decimal_places=2)
    cash_delta = models.DecimalField(max_digits=15, decimal_places=2)

    posted_at = models.DateTimeField()
    posting_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = SimulatedFeeCorrectionEventManager()

    class Meta:
        base_manager_name = "objects"
        db_table = "simulated_fee_correction_event"
        ordering = ["trade_id", "revision"]
        indexes = [
            models.Index(fields=("account", "posting_date"), name="sim_fee_corr_acct_date_idx")
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("account", "idempotency_key"),
                name="sim_fee_corr_account_key_uq",
            ),
            models.UniqueConstraint(
                fields=("trade", "revision"),
                name="sim_fee_corr_trade_rev_uq",
            ),
            models.UniqueConstraint(
                fields=("account", "account_revision"),
                name="sim_fee_corr_acct_rev_uq",
            ),
            models.CheckConstraint(
                condition=Q(account_revision__gt=0),
                name="sim_fee_corr_acct_rev_positive_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(account_predecessor_hash__regex=_SHA256_PATTERN)
                    & Q(account_prefix_hash__regex=_SHA256_PATTERN)
                    & Q(
                        Exact(Length("account_predecessor_hash"), models.Value(64)),
                        Exact(Length("account_prefix_hash"), models.Value(64)),
                    )
                ),
                name="sim_fee_corr_account_prefix_hashes_ck",
            ),
            models.UniqueConstraint(
                fields=("previous_event",),
                condition=Q(previous_event__isnull=False),
                name="sim_fee_corr_successor_uq",
            ),
            models.CheckConstraint(
                condition=Q(revision__gt=0),
                name="sim_fee_corr_revision_positive_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(revision=1, previous_event__isnull=True)
                    | Q(revision__gt=1, previous_event__isnull=False)
                ),
                name="sim_fee_corr_predecessor_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(idempotency_key__gt="")
                    & Q(source_namespace__gt="")
                    & Q(source_record_id__gt="")
                    & Q(verifier_identity__gt="")
                    & Q(authority_identity__gt="")
                    & Q(authority_record_id__gt="")
                ),
                name="sim_fee_corr_tokens_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(request_payload_hash__regex=_SHA256_PATTERN)
                    & Q(trade_snapshot_hash__regex=_SHA256_PATTERN)
                    & Q(source_evidence_hash__regex=_SHA256_PATTERN)
                    & Q(source_payload_hash__regex=_SHA256_PATTERN)
                    & Q(authority_hash__regex=_SHA256_PATTERN)
                    & (
                        Q(receipt_snapshot_hash__isnull=True)
                        | Q(receipt_snapshot_hash__regex=_SHA256_PATTERN)
                    )
                ),
                name="sim_fee_corr_hashes_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        Exact(Length("request_payload_hash"), models.Value(64)),
                        Exact(Length("trade_snapshot_hash"), models.Value(64)),
                        Exact(Length("source_evidence_hash"), models.Value(64)),
                        Exact(Length("source_payload_hash"), models.Value(64)),
                        Exact(Length("authority_hash"), models.Value(64)),
                    )
                    & (
                        Q(receipt_snapshot_hash__isnull=True)
                        | Q(Exact(Length("receipt_snapshot_hash"), models.Value(64)))
                    )
                ),
                name="sim_fee_corr_hash_lengths_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(authority_snapshot_json__isnull=True, authority_snapshot_sha256__isnull=True)
                    | Q(
                        authority_snapshot_json__isnull=False,
                        authority_snapshot_sha256__regex=_SHA256_PATTERN,
                    )
                    & Q(Exact(Length("authority_snapshot_sha256"), models.Value(64)))
                ),
                name="sim_fee_corr_auth_snapshot_pair_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(source_observed_at__lte=models.F("evidence_verified_at"))
                    & Q(evidence_verified_at__lte=models.F("posted_at"))
                ),
                name="sim_fee_corr_clock_order_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(previous_commission__gte=0)
                    & Q(previous_transfer_fee__gte=0)
                    & Q(previous_stamp_duty__gte=0)
                    & Q(revised_commission__gte=0)
                    & Q(revised_transfer_fee__gte=0)
                    & Q(revised_stamp_duty__gte=0)
                    & Q(original_slippage__gte=0)
                ),
                name="sim_fee_corr_amounts_nonnegative_ck",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Insert exactly once; correction events cannot be updated in place."""

        if (
            type(self.authority_snapshot_json) is not dict
            or type(self.authority_snapshot_sha256) is not str
            or len(self.authority_snapshot_sha256) != 64
            or any(
                character not in "0123456789abcdef" for character in self.authority_snapshot_sha256
            )
        ):
            raise ValidationError("新模拟费用更正事件必须带完整权限快照")
        if (
            type(self.account_revision) is not int
            or self.account_revision <= 0
            or not _is_sha256(self.account_predecessor_hash)
            or not _is_sha256(self.account_prefix_hash)
        ):
            raise ValidationError("新模拟费用更正事件必须带正账户内序号")

        if self.pk is not None:
            using = kwargs.get("using")
            if using is None:
                using = router.db_for_write(type(self), instance=self)
            if type(self)._base_manager.using(using).filter(pk=self.pk).exists():
                raise ValidationError("模拟费用更正事件不可通过实例 save 修改")
            raise ValidationError("模拟费用更正事件不可使用预置主键插入")
        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        if (
            not SimulatedTradeModel._base_manager.using(database)
            .filter(
                pk=self.trade_id,
                account_id=self.account_id,
            )
            .exists()
        ):
            raise ValidationError("费用更正事件必须与 Trade 属于同一账户")
        super().save(*args, **kwargs)

    def delete(
        self, using: str | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Refuse deletion of source evidence, accounting history, and replay keys."""

        del using, keep_parents
        raise ValidationError("模拟费用更正事件不可删除")

    def __str__(self) -> str:
        """Return the stable trade/revision event label."""

        return f"{self.trade_id}:fee-correction:{self.revision}"


__all__ = ["SimulatedFeeCorrectionEventModel"]
