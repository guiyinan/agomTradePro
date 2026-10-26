"""Immutable local fee-evidence artifacts and explicit qualification policy."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Collection, Iterable
from typing import Any, Generic, TypeVar, cast

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.db.models import Q
from django.db.models.functions import Length
from django.db.models.lookups import Exact

from apps.simulated_trading.application.fee_correction_evidence import MAX_UPLOAD_BYTES

from .simulated_account_trade_models import SimulatedAccountModel, SimulatedTradeModel

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_CURRENCY_PATTERN = r"^[A-Z]{3}$"
_ASSURANCE_OPERATOR_ATTESTED_UPLOAD = "operator_attested_upload"
_ASSURANCE_CHOICES = [
    (_ASSURANCE_OPERATOR_ATTESTED_UPLOAD, "Operator-attested upload (not issuer-authenticated)"),
]

_ModelT = TypeVar("_ModelT", bound=models.Model)


class AppendOnlyFeeEvidenceQuerySet(models.QuerySet[_ModelT], Generic[_ModelT]):
    """Deny ORM bulk mutation paths for source bytes and their bindings."""

    def update(self, **kwargs: Any) -> int:
        """Keep evidence and binding rows immutable after insertion."""

        del kwargs
        raise ValidationError("费用更正来源证据不可通过 QuerySet.update 修改")

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[_ModelT]:
        """Require normal model insertion checks for evidence records."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("费用更正来源证据不可通过 bulk_create 绕过存储校验")

    def bulk_update(
        self,
        objs: Iterable[_ModelT],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        """Reject mutation of evidence through QuerySet.bulk_update."""

        del objs, fields, batch_size
        raise ValidationError("费用更正来源证据不可通过 bulk_update 修改")

    def delete(self) -> tuple[int, dict[str, int]]:
        """Retain uploaded bytes and exact target bindings permanently."""

        raise ValidationError("费用更正来源证据不可通过 QuerySet.delete 删除")


class AppendOnlyFeeEvidenceManager(models.Manager[_ModelT], Generic[_ModelT]):
    """Manager for append-only fee evidence rows."""

    use_in_migrations = False

    def get_queryset(self) -> AppendOnlyFeeEvidenceQuerySet[_ModelT]:
        """Return the immutable queryset implementation."""

        return AppendOnlyFeeEvidenceQuerySet(self.model, using=self._db)


class FeeCorrectionEvidencePolicyQuerySet(models.QuerySet["FeeCorrectionEvidencePolicyModel"]):
    """Require qualification policy changes to increment the stored version."""

    def update(self, **kwargs: Any) -> int:
        """Require policy updates to pass its version-incrementing model save."""

        del kwargs
        raise ValidationError("费用更正资格策略必须通过版本化模型保存")

    def bulk_create(
        self,
        objs: Iterable[FeeCorrectionEvidencePolicyModel],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[FeeCorrectionEvidencePolicyModel]:
        """Require normal model insertion checks for qualification policies."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("费用更正资格策略不可通过 bulk_create 绕过存储校验")

    def bulk_update(
        self,
        objs: Iterable[FeeCorrectionEvidencePolicyModel],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        """Reject policy updates that would bypass version changes."""

        del objs, fields, batch_size
        raise ValidationError("费用更正资格策略不可通过 bulk_update 修改")

    def delete(self) -> tuple[int, dict[str, int]]:
        """Retain qualification records referenced by evidence bindings."""

        raise ValidationError("费用更正资格策略不可删除")


class FeeCorrectionEvidencePolicyManager(models.Manager["FeeCorrectionEvidencePolicyModel"]):
    """Manager that routes policy mutations through the versioned queryset."""

    use_in_migrations = False

    def get_queryset(self) -> FeeCorrectionEvidencePolicyQuerySet:
        """Return the policy queryset with direct bulk writes disabled."""

        return FeeCorrectionEvidencePolicyQuerySet(self.model, using=self._db)


class FeeCorrectionEvidencePolicyModel(models.Model):
    """Per-account qualification policy; all assurance classes default denied."""

    account = models.OneToOneField(
        SimulatedAccountModel,
        on_delete=models.PROTECT,
        related_name="fee_correction_evidence_policy",
    )
    enabled = models.BooleanField(default=False)
    allow_operator_attested_upload = models.BooleanField(default=False)
    ledger_currency = models.CharField(max_length=3, blank=True, default="")
    version = models.PositiveIntegerField(default=1)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="updated_fee_correction_evidence_policies",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects: FeeCorrectionEvidencePolicyManager = FeeCorrectionEvidencePolicyManager()

    class Meta:
        db_table = "sim_fee_correction_evidence_policy"
        base_manager_name = "objects"
        verbose_name = "模拟费用更正证据资格策略"
        verbose_name_plural = "模拟费用更正证据资格策略"
        constraints = [
            models.CheckConstraint(
                condition=Q(version__gt=0),
                name="sim_fee_ev_policy_version_ck",
            ),
            models.CheckConstraint(
                condition=Q(enabled=False) | Q(updated_by__isnull=False),
                name="sim_fee_ev_policy_actor_ck",
            ),
            models.CheckConstraint(
                condition=Q(enabled=False) | Q(ledger_currency__regex=_CURRENCY_PATTERN),
                name="sim_fee_ev_policy_currency_ck",
            ),
            models.CheckConstraint(
                condition=Q(valid_from__isnull=True)
                | Q(valid_until__isnull=True)
                | Q(valid_until__gt=models.F("valid_from")),
                name="sim_fee_ev_policy_window_ck",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Increment policy version atomically whenever qualification changes."""

        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        if self.pk is None:
            if self.version != 1:
                raise ValidationError("费用更正资格策略必须从版本 1 创建")
            kwargs["using"] = using
            super().save(*args, **kwargs)
            return
        update_fields = kwargs.get("update_fields")
        with transaction.atomic(using=using):
            current = (
                type(self)._base_manager.using(using).select_for_update().filter(pk=self.pk).first()
            )
            if current is None:
                raise ValidationError("费用更正资格策略不存在")
            policy_fields = (
                "account_id",
                "enabled",
                "allow_operator_attested_upload",
                "ledger_currency",
                "valid_from",
                "valid_until",
                "updated_by_id",
            )
            changed_fields = [
                field
                for field in policy_fields
                if getattr(current, field) != getattr(self, field)
                and (update_fields is None or field in update_fields)
            ]
            if changed_fields:
                self.version = current.version + 1
                if update_fields is not None:
                    kwargs["update_fields"] = tuple(
                        dict.fromkeys((*update_fields, *changed_fields, "version", "updated_at"))
                    )
            else:
                self.version = current.version
            kwargs["using"] = using
            super().save(*args, **kwargs)

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Retain policy versions referenced by persisted evidence bindings."""

        del using, keep_parents
        raise ValidationError("费用更正资格策略不可删除")

    def __str__(self) -> str:
        """Return a non-sensitive account/version label."""

        return f"account={self.account_id} version={self.version}"


class FeeCorrectionEvidenceArtifactModel(models.Model):
    """One immutable upload with original bytes and exact parsed-row metadata."""

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.PROTECT,
        related_name="fee_correction_evidence_artifacts",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_fee_correction_evidence",
    )
    original_filename = models.CharField(max_length=255)
    assurance_class = models.CharField(
        max_length=40,
        choices=_ASSURANCE_CHOICES,
        default=_ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
    )
    schema_version = models.CharField(max_length=40)
    raw_bytes = models.BinaryField()
    content_sha256 = models.CharField(max_length=64)
    payload_sha256 = models.CharField(max_length=64)
    raw_row_json = models.JSONField()
    parsed_metadata_json = models.JSONField()
    uploaded_at = models.DateTimeField()

    objects: AppendOnlyFeeEvidenceManager[FeeCorrectionEvidenceArtifactModel] = cast(
        "AppendOnlyFeeEvidenceManager[FeeCorrectionEvidenceArtifactModel]",
        AppendOnlyFeeEvidenceManager(),
    )

    class Meta:
        db_table = "sim_fee_correction_evidence_artifact"
        base_manager_name = "objects"
        verbose_name = "模拟费用更正证据材料"
        verbose_name_plural = "模拟费用更正证据材料"
        indexes = [models.Index(fields=("account", "uploaded_at"), name="sim_fee_ev_art_acct_ix")]
        constraints = [
            models.CheckConstraint(
                condition=Q(content_sha256__regex=_SHA256_PATTERN)
                & Q(payload_sha256__regex=_SHA256_PATTERN),
                name="sim_fee_ev_art_hash_ck",
            ),
            models.CheckConstraint(
                condition=Q(schema_version="operator-fee-evidence.v2")
                & Q(assurance_class=_ASSURANCE_OPERATOR_ATTESTED_UPLOAD),
                name="sim_fee_ev_art_class_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(Exact(Length("content_sha256"), models.Value(64)))
                    & Q(Exact(Length("payload_sha256"), models.Value(64)))
                ),
                name="sim_fee_ev_art_hash_length_ck",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Allow one normal insertion and reject updates to stored source bytes."""

        if self.pk is not None:
            using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
            if type(self)._base_manager.using(using).filter(pk=self.pk).exists():
                raise ValidationError("费用更正原始上传材料不可修改")
            raise ValidationError("费用更正证据不可使用预置主键插入")
        raw_value = self.raw_bytes
        if not isinstance(raw_value, (bytes, bytearray, memoryview)):
            raise ValidationError("费用更正上传材料必须是原始字节")
        raw_bytes = bytes(raw_value)
        if not raw_bytes or len(raw_bytes) > MAX_UPLOAD_BYTES:
            raise ValidationError("费用更正上传材料为空或超过本地大小上限")
        if hashlib.sha256(raw_bytes).hexdigest() != self.content_sha256:
            raise ValidationError("费用更正上传摘要必须由服务端字节重新计算")
        super().save(*args, **kwargs)

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Keep the source bytes that support a correction proof."""

        del using, keep_parents
        raise ValidationError("费用更正原始上传材料不可删除")

    def __str__(self) -> str:
        """Return a local evidence label without exposing the uploaded filename."""

        return f"fee-evidence-artifact={self.pk}"


class FeeCorrectionEvidenceBindingModel(models.Model):
    """Immutable operator attestation binding one artifact to one exact Trade."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.PROTECT,
        related_name="fee_correction_evidence_bindings",
    )
    trade = models.ForeignKey(
        SimulatedTradeModel,
        on_delete=models.PROTECT,
        related_name="fee_correction_evidence_bindings",
    )
    artifact = models.ForeignKey(
        FeeCorrectionEvidenceArtifactModel,
        on_delete=models.PROTECT,
        related_name="trade_bindings",
    )
    policy = models.ForeignKey(
        FeeCorrectionEvidencePolicyModel,
        on_delete=models.PROTECT,
        related_name="evidence_bindings",
    )
    idempotency_key = models.CharField(max_length=128)
    attested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="attested_fee_correction_bindings",
    )
    attestation_version = models.CharField(max_length=40)
    attestation_acknowledged = models.BooleanField(default=False)
    assurance_class = models.CharField(
        max_length=40,
        choices=_ASSURANCE_CHOICES,
        default=_ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
    )
    expected_revision = models.PositiveIntegerField()
    expected_predecessor_id = models.PositiveBigIntegerField(null=True, blank=True)
    content_sha256 = models.CharField(max_length=64)
    payload_sha256 = models.CharField(max_length=64)
    trade_snapshot_sha256 = models.CharField(max_length=64)
    policy_version = models.PositiveIntegerField()
    policy_sha256 = models.CharField(max_length=64)
    policy_snapshot_json = models.JSONField()
    created_at = models.DateTimeField()

    objects: AppendOnlyFeeEvidenceManager[FeeCorrectionEvidenceBindingModel] = cast(
        "AppendOnlyFeeEvidenceManager[FeeCorrectionEvidenceBindingModel]",
        AppendOnlyFeeEvidenceManager(),
    )

    class Meta:
        db_table = "sim_fee_correction_evidence_binding"
        base_manager_name = "objects"
        verbose_name = "模拟费用更正证据绑定"
        verbose_name_plural = "模拟费用更正证据绑定"
        indexes = [
            models.Index(
                fields=("account", "trade", "created_at"), name="sim_fee_ev_bind_trade_ix"
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("account", "idempotency_key"),
                name="sim_fee_ev_bind_idemp_uq",
            ),
            models.CheckConstraint(
                condition=Q(content_sha256__regex=_SHA256_PATTERN)
                & Q(payload_sha256__regex=_SHA256_PATTERN)
                & Q(trade_snapshot_sha256__regex=_SHA256_PATTERN)
                & Q(policy_sha256__regex=_SHA256_PATTERN),
                name="sim_fee_ev_bind_hash_ck",
            ),
            models.CheckConstraint(
                condition=Q(attestation_acknowledged=True)
                & Q(attestation_version="operator-fee-attestation.v1")
                & Q(assurance_class=_ASSURANCE_OPERATOR_ATTESTED_UPLOAD),
                name="sim_fee_ev_bind_class_ck",
            ),
            models.CheckConstraint(
                condition=Q(expected_revision=0, expected_predecessor_id__isnull=True)
                | Q(expected_revision__gt=0, expected_predecessor_id__isnull=False),
                name="sim_fee_ev_bind_revision_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(Exact(Length("trade_snapshot_sha256"), models.Value(64)))
                    & Q(Exact(Length("content_sha256"), models.Value(64)))
                    & Q(Exact(Length("payload_sha256"), models.Value(64)))
                    & Q(Exact(Length("policy_sha256"), models.Value(64)))
                ),
                name="sim_fee_ev_bind_hash_length_ck",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Allow one normal insertion and reject changes to the attestation."""

        if self.pk is not None:
            using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
            if type(self)._base_manager.using(using).filter(pk=self.pk).exists():
                raise ValidationError("费用更正证据绑定不可修改")
            raise ValidationError("费用更正证据绑定不可使用预置主键插入")
        super().save(*args, **kwargs)

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Keep the operator's attestation and exact Trade binding for audit."""

        del using, keep_parents
        raise ValidationError("费用更正证据绑定不可删除")

    def __str__(self) -> str:
        """Return the stable local binding locator."""

        return str(self.public_id)


__all__ = [
    "AppendOnlyFeeEvidenceManager",
    "FeeCorrectionEvidenceArtifactModel",
    "FeeCorrectionEvidenceBindingModel",
    "FeeCorrectionEvidencePolicyManager",
    "FeeCorrectionEvidencePolicyModel",
]
