"""Unregistered ORM candidate for C2 rule, policy and Owner lifecycle rows.

These models are intentionally kept outside the live ``models.py`` export and
have no migration. Their local apply/revoke rows are ordinary Data Center
configuration evidence, not SystemAudit events or publication outbox receipts.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import NoReturn, Self, TypeVar
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

from apps.data_center.infrastructure.statutory_source_models import (
    StatutorySourceDocumentCaptureModel,
)
from shared.infrastructure.django_append_only import AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)


class _GovernanceAppendOnlyQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject queryset-level shortcuts that bypass the append repositories."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Iterable[str] | None = None,
        unique_fields: Iterable[str] | None = None,
    ) -> NoReturn:
        """Require every insert to pass typed C2 repository validation."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("C2 governance rows require their typed append repository.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        """Block Django's private queryset deletion path."""

        del using
        raise ValidationError("C2 governance rows are append-only.")


class _GovernanceAppendOnlyManager(models.Manager[_ModelT]):
    """Expose only append-safe queryset operations for the two C2 tables."""

    def get_queryset(self) -> _GovernanceAppendOnlyQuerySet[_ModelT]:
        """Return append-guarded reads bound to this manager's database."""

        return _GovernanceAppendOnlyQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Iterable[str] | None = None,
        unique_fields: Iterable[str] | None = None,
    ) -> NoReturn:
        """Reject manager-level bulk insertion outside the typed repository."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("C2 governance rows require their typed append repository.")


class _FinancialAvailabilityAppendOnlyModel(models.Model):
    """Protect model-level writes while database triggers remain the final guard."""

    objects: _GovernanceAppendOnlyManager[Self] = _GovernanceAppendOnlyManager()

    class Meta:
        abstract = True

    def save(
        self,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Allow new rows only; the typed repository is the sole insert path."""

        del force_insert
        if force_update or update_fields is not None or not self._state.adding:
            raise ValidationError("C2 governance rows are append-only.")
        super().save(force_insert=True, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Reject raw fixtures and lower-level updates to C2 evidence rows."""

        del force_insert
        if raw or force_update or update_fields is not None or not self._state.adding:
            raise ValidationError("C2 governance rows require a typed append.")
        super().save_base(
            raw=False,
            force_insert=True,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def delete(self, using: str | None = None, keep_parents: bool = False) -> NoReturn:
        """Keep every C2 configuration and lifecycle event for historical reads."""

        del using, keep_parents
        raise ValidationError("C2 governance rows are append-only.")


class FinancialAvailabilityGovernanceRecordModel(_FinancialAvailabilityAppendOnlyModel):
    """One immutable explicit opening-rule or disclosure-policy version."""

    OPENING_RULE = "opening_rule"
    DISCLOSURE_POLICY = "disclosure_policy"
    KIND_CHOICES = (
        (OPENING_RULE, "Exchange session opening rule"),
        (DISCLOSURE_POLICY, "Financial disclosure availability policy"),
    )

    row_id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    record_id = models.CharField(max_length=200)
    record_version = models.CharField(max_length=200)
    exchange = models.CharField(max_length=32)
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    payload = models.JSONField()
    content_sha256 = models.CharField(max_length=64)
    recorded_at = models.DateTimeField()
    source_capture = models.ForeignKey(
        StatutorySourceDocumentCaptureModel,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="financial_availability_governance_records",
    )
    source_capture_id: UUID | None

    class Meta:
        app_label = "data_center"
        db_table = "data_center_financial_availability_governance_record"
        ordering = ("record_id", "record_version")
        constraints = [
            models.UniqueConstraint(
                fields=("record_id", "record_version"),
                name="dc_fin_avail_record_version_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(kind="opening_rule", source_capture__isnull=False)
                    | models.Q(kind="disclosure_policy", source_capture__isnull=True)
                ),
                name="dc_fin_avail_record_source_shape_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(content_sha256__regex=r"^[0-9a-f]{64}$"),
                name="dc_fin_avail_record_hash_ck",
            ),
        ]
        permissions = [
            (
                "manage_financial_availability_governance",
                "Can manage financial availability governance",
            ),
        ]

    def __str__(self) -> str:
        """Show only the exact immutable configuration key."""

        return f"{self.record_id}:{self.record_version}"


class FinancialAvailabilityOwnerEventModel(_FinancialAvailabilityAppendOnlyModel):
    """One authenticated Django User apply/revoke event for an exact record."""

    APPLY = "apply"
    REVOKE = "revoke"
    ACTION_CHOICES = ((APPLY, "Apply"), (REVOKE, "Revoke"))

    event_id = models.UUIDField(primary_key=True, editable=False)
    governance_record = models.ForeignKey(
        FinancialAvailabilityGovernanceRecordModel,
        on_delete=models.PROTECT,
        related_name="owner_events",
    )
    action = models.CharField(max_length=16, choices=ACTION_CHOICES)
    event_sha256 = models.CharField(max_length=64)
    record_content_sha256 = models.CharField(max_length=64)
    resulting_content_sha256 = models.CharField(max_length=64)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="financial_availability_owner_events",
    )
    permission = models.ForeignKey(
        Permission,
        on_delete=models.PROTECT,
        related_name="financial_availability_owner_events",
    )
    permission_app_label = models.CharField(max_length=100)
    permission_codename = models.CharField(max_length=100)
    permission_verified_at = models.DateTimeField()
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField()
    reason = models.CharField(max_length=1000)
    predecessor_apply_event = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revoke_event",
    )
    predecessor_apply_event_sha256 = models.CharField(max_length=64, null=True, blank=True)
    governance_record_id: UUID
    actor_id: int
    permission_id: int
    predecessor_apply_event_id: UUID | None

    class Meta:
        app_label = "data_center"
        db_table = "data_center_financial_availability_owner_event"
        ordering = ("governance_record_id", "recorded_at", "event_id")
        constraints = [
            models.UniqueConstraint(
                fields=("governance_record", "action"),
                name="dc_fin_avail_record_action_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        action="apply",
                        predecessor_apply_event__isnull=True,
                        predecessor_apply_event_sha256__isnull=True,
                    )
                    | models.Q(
                        action="revoke",
                        predecessor_apply_event__isnull=False,
                        predecessor_apply_event_sha256__isnull=False,
                    )
                ),
                name="dc_fin_avail_event_predecessor_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    permission_app_label="data_center",
                    permission_codename="manage_financial_availability_governance",
                ),
                name="dc_fin_avail_event_permission_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    event_sha256__regex=r"^[0-9a-f]{64}$",
                    record_content_sha256__regex=r"^[0-9a-f]{64}$",
                    resulting_content_sha256__regex=r"^[0-9a-f]{64}$",
                ),
                name="dc_fin_avail_event_hashes_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(occurred_at__gte=models.F("permission_verified_at")),
                name="dc_fin_avail_event_verified_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(recorded_at__gte=models.F("occurred_at")),
                name="dc_fin_avail_event_record_clock_ck",
            ),
        ]

    def __str__(self) -> str:
        """Show only the local immutable event identity."""

        return str(self.event_id)


__all__ = [
    "FinancialAvailabilityGovernanceRecordModel",
    "FinancialAvailabilityOwnerEventModel",
]
