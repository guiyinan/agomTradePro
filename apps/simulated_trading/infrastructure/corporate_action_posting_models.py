"""Append-only simulated account corporate-action stage ledger model."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models, router
from django.db.models import Q

from .simulated_account_trade_models import SimulatedAccountModel

_DIGEST_CHARACTERS = frozenset("0123456789abcdef")


def _is_digest(value: object) -> bool:
    """Return whether a value is a lowercase SHA-256 digest."""

    return (
        type(value) is str
        and len(value) == 64
        and all(character in _DIGEST_CHARACTERS for character in value)
    )


class CorporateActionPostingQuerySet(models.QuerySet["CorporateActionPostingModel"]):
    """Reject bulk mutation or removal of retained corporate-action ledger rows."""

    def update(self, **kwargs: Any) -> int:
        """Preserve the append-only stage history."""

        del kwargs
        raise ValidationError("模拟公司行动账本不可通过 QuerySet.update 修改")

    def bulk_create(
        self,
        objs: Iterable[CorporateActionPostingModel],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[CorporateActionPostingModel]:
        """Require ledger insertion to pass its locked repository."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("模拟公司行动账本不可通过 bulk_create 写入")

    def bulk_update(
        self,
        objs: Iterable[CorporateActionPostingModel],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        """Reject bulk replacement of historical source or accounting facts."""

        del objs, fields, batch_size
        raise ValidationError("模拟公司行动账本不可通过 bulk_update 修改")

    def delete(self) -> tuple[int, dict[str, int]]:
        """Keep ledger history and idempotency keys permanently."""

        raise ValidationError("模拟公司行动账本不可通过 QuerySet.delete 删除")


CorporateActionPostingManager = models.Manager.from_queryset(CorporateActionPostingQuerySet)


class CorporateActionPostingModel(models.Model):
    """One source-qualified corporate-action stage or correction ledger entry."""

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.PROTECT,
        related_name="corporate_action_postings",
    )
    account_revision = models.PositiveBigIntegerField()
    source_namespace = models.CharField(max_length=128)
    source_record_id = models.CharField(max_length=192)
    source_event_id = models.CharField(max_length=192)
    source_revision_id = models.CharField(max_length=192)
    asset_code = models.CharField(max_length=32)
    security_id = models.CharField(max_length=96)
    asset_name = models.CharField(max_length=128)
    action_kind = models.CharField(
        max_length=32,
        choices=(
            ("cash_dividend", "Cash dividend"),
            ("share_distribution", "Share distribution"),
            ("rights_issue", "Rights issue"),
        ),
    )
    stage = models.CharField(
        max_length=32,
        choices=(
            ("cash_entitlement", "Cash entitlement"),
            ("cash_payment", "Cash payment"),
            ("tax_withholding", "Tax withholding"),
            ("share_entitlement", "Share entitlement"),
            ("share_delivery", "Share delivery"),
            ("share_sellable_release", "Share sellable release"),
            ("rights_not_exercised", "Rights not exercised"),
        ),
    )
    entry_kind = models.CharField(
        max_length=16,
        choices=(
            ("posting", "Posting"),
            ("reversal", "Reversal"),
            ("successor", "Successor"),
            ("no_effect", "No effect"),
        ),
    )
    stage_key = models.CharField(max_length=64)
    request_payload_sha256 = models.CharField(max_length=64)
    source_payload_sha256 = models.CharField(max_length=64)
    qualification_sha256 = models.CharField(max_length=64)
    qualifier_identity = models.CharField(max_length=128)
    source_observed_at = models.DateTimeField()
    qualified_at = models.DateTimeField()
    posted_at = models.DateTimeField()
    record_date = models.DateField()
    effective_date = models.DateField()
    stage_date = models.DateField()
    payment_date = models.DateField(null=True, blank=True)
    sellable_date = models.DateField(null=True, blank=True)
    cash_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    share_amount = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    tax_treatment = models.CharField(max_length=32, null=True, blank=True)
    tax_rule_id = models.CharField(max_length=128, null=True, blank=True)
    tax_rule_sha256 = models.CharField(max_length=64, null=True, blank=True)
    tax_basis_record_id = models.CharField(max_length=192, null=True, blank=True)
    tax_basis_sha256 = models.CharField(max_length=64, null=True, blank=True)
    ownership_snapshot_id = models.CharField(max_length=192, null=True, blank=True)
    ownership_snapshot_sha256 = models.CharField(max_length=64, null=True, blank=True)
    ownership_snapshot_as_of_date = models.DateField(null=True, blank=True)
    ownership_snapshot_observed_at = models.DateTimeField(null=True, blank=True)
    eligible_quantity = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    entitlement_calculation_sha256 = models.CharField(max_length=64, null=True, blank=True)
    rights_terms_sha256 = models.CharField(max_length=64, null=True, blank=True)
    rights_election = models.CharField(max_length=24, null=True, blank=True)
    odd_lot_policy = models.CharField(max_length=40, null=True, blank=True)
    odd_lot_confirmation_sha256 = models.CharField(max_length=64, null=True, blank=True)
    supersedes_revision_id = models.CharField(max_length=192, null=True, blank=True)
    reversal_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="reversal_entries",
        null=True,
        blank=True,
    )
    cash_delta = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    cash_receivable_delta = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    share_delta = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    share_receivable_delta = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    available_share_delta = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = CorporateActionPostingManager()

    class Meta:
        base_manager_name = "objects"
        db_table = "simulated_corporate_action_posting"
        ordering = ("account_id", "account_revision")
        indexes = [
            models.Index(
                fields=("account", "source_event_id", "source_revision_id"),
                name="sim_ca_event_rev_idx",
            ),
            models.Index(fields=("account", "stage_date"), name="sim_ca_acct_date_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("account", "account_revision"),
                name="sim_ca_account_revision_uq",
            ),
            models.UniqueConstraint(
                fields=("account", "source_event_id", "source_revision_id", "stage_key"),
                name="sim_ca_event_stage_uq",
            ),
            models.CheckConstraint(
                condition=Q(account_revision__gt=0) & Q(source_revision_id__gt=""),
                name="sim_ca_revision_positive_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(stage_key__gt="")
                    & Q(source_namespace__gt="")
                    & Q(source_record_id__gt="")
                    & Q(source_event_id__gt="")
                    & Q(asset_code__gt="")
                    & Q(security_id__gt="")
                ),
                name="sim_ca_identity_nonempty_ck",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Insert one validated ledger row and reject later instance updates."""

        if self.pk is not None:
            database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
            if type(self)._base_manager.using(database).filter(pk=self.pk).exists():
                raise ValidationError("模拟公司行动账本不可通过实例 save 修改")
            raise ValidationError("模拟公司行动账本不可使用预置主键插入")
        if (
            type(self.stage_key) is not str
            or self.stage_key != f"{self.entry_kind}:{self.stage}"
            or type(self.account_revision) is not int
            or self.account_revision <= 0
            or type(self.source_revision_id) is not str
            or not self.source_revision_id
            or self.source_revision_id != self.source_revision_id.strip()
            or len(self.source_revision_id) > 192
            or any(character.isspace() for character in self.source_revision_id)
            or (
                self.supersedes_revision_id is not None
                and (
                    type(self.supersedes_revision_id) is not str
                    or not self.supersedes_revision_id
                    or self.supersedes_revision_id != self.supersedes_revision_id.strip()
                    or len(self.supersedes_revision_id) > 192
                )
            )
            or any(
                value is not None and not _is_digest(value)
                for value in (
                    self.tax_rule_sha256,
                    self.tax_basis_sha256,
                    self.ownership_snapshot_sha256,
                    self.entitlement_calculation_sha256,
                    self.rights_terms_sha256,
                    self.odd_lot_confirmation_sha256,
                )
            )
            or not all(
                _is_digest(value)
                for value in (
                    self.request_payload_sha256,
                    self.source_payload_sha256,
                    self.qualification_sha256,
                )
            )
        ):
            raise ValidationError("模拟公司行动账本缺少有效阶段身份、序号或来源摘要")
        super().save(*args, **kwargs)

    def delete(
        self, using: str | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Refuse deletion of retained source evidence and accounting entries."""

        del using, keep_parents
        raise ValidationError("模拟公司行动账本不可删除")

    def __str__(self) -> str:
        """Return the stable account/event/revision/stage identity."""

        return (
            f"{self.account_id}:{self.source_event_id}:"
            f"{self.source_revision_id}:{self.stage_key}"
        )


__all__ = ["CorporateActionPostingModel"]
