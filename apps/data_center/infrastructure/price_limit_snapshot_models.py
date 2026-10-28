"""Append-only ORM model for exact source-bound price-limit facts."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Any, NoReturn, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F

_PRICE_LIMIT_MODEL = TypeVar("_PRICE_LIMIT_MODEL", bound=models.Model)


class _PriceLimitSnapshotQuerySet(models.QuerySet[_PRICE_LIMIT_MODEL]):
    """Read-capable queryset that rejects mutation and bulk-insert shortcuts."""

    def update(self, **kwargs: object) -> NoReturn:
        """Reject updates that would invalidate the source and row seals."""

        del kwargs
        raise ValidationError("Price-limit snapshot facts are append-only.")

    def delete(self) -> NoReturn:
        """Reject query-wide removal of price-limit source history."""

        raise ValidationError("Price-limit snapshot facts are append-only.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        """Reject Django's internal raw delete shortcut."""

        del using
        raise ValidationError("Price-limit snapshot facts are append-only.")

    def bulk_update(
        self,
        objs: Iterable[_PRICE_LIMIT_MODEL],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> NoReturn:
        """Reject bulk mutation that bypasses repository readback checks."""

        del objs, fields, batch_size
        raise ValidationError("Price-limit snapshot facts are append-only.")

    def bulk_create(
        self,
        objs: Iterable[_PRICE_LIMIT_MODEL],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Require row-wise repository checks instead of bulk persistence."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("Price-limit snapshot facts require repository persistence.")


class _PriceLimitSnapshotManager(models.Manager[_PRICE_LIMIT_MODEL]):
    """Expose exact reads and row-wise inserts, but no mutation shortcuts."""

    def get_queryset(self) -> _PriceLimitSnapshotQuerySet[_PRICE_LIMIT_MODEL]:
        """Return the read-only queryset used by this append-only model."""

        return _PriceLimitSnapshotQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_PRICE_LIMIT_MODEL],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject bulk inserts that could bypass source-body verification."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("Price-limit snapshot facts require repository persistence.")

    def bulk_update(
        self,
        objs: Iterable[_PRICE_LIMIT_MODEL],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> NoReturn:
        """Reject manager-level bulk updates of sealed facts."""

        del objs, fields, batch_size
        raise ValidationError("Price-limit snapshot facts are append-only.")


class PriceLimitSnapshotFactModel(models.Model):
    """One exact Tushare limit response, linked to its immutable RawPayload."""

    snapshot_id = models.UUIDField(primary_key=True, editable=False)
    raw_payload = models.OneToOneField(
        "data_center.RawPayloadModel",
        on_delete=models.PROTECT,
        related_name="price_limit_snapshot_fact",
    )
    raw_payload_hash = models.CharField(max_length=128, unique=True, db_index=True)
    asset_code = models.CharField(max_length=20, db_index=True)
    effective_trade_date = models.DateField(db_index=True)
    provider_id = models.PositiveBigIntegerField(db_index=True)
    provider_name = models.CharField(max_length=100, db_index=True)
    lower_limit_price = models.CharField(max_length=512)
    upper_limit_price = models.CharField(max_length=512)
    raw_reference = models.JSONField()
    content_hash = models.CharField(max_length=71, unique=True)
    response_completed_at = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField(db_index=True)
    record_digest = models.CharField(max_length=71, unique=True)

    objects = _PriceLimitSnapshotManager["PriceLimitSnapshotFactModel"]()

    class Meta:
        db_table = "data_center_price_limit_snapshot_fact"
        base_manager_name = "objects"
        permissions = [("publish_price_limit", "Can publish reference price limits")]
        indexes = [
            models.Index(
                fields=[
                    "asset_code",
                    "effective_trade_date",
                    "provider_id",
                    "provider_name",
                    "recorded_at",
                ],
                name="dc_plimit_scope_record_idx",
            ),
        ]
        ordering = ["-recorded_at", "snapshot_id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(provider_id__gt=0),
                name="dc_plimit_provider_pos",
            ),
            models.CheckConstraint(
                condition=models.Q(recorded_at__gte=F("response_completed_at")),
                name="dc_plimit_record_after_response",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Allow only a new row whose raw hash matches its protected source."""

        if args:
            raise ValidationError("Price-limit snapshot facts require keyword-only inserts.")
        if kwargs.pop("force_update", False) or kwargs.pop("update_fields", None) is not None:
            raise ValidationError("Price-limit snapshot facts are append-only.")
        if not self._state.adding:
            raise ValidationError("Price-limit snapshot facts are append-only.")
        if self.snapshot_id and type(self)._base_manager.filter(pk=self.snapshot_id).exists():
            raise ValidationError("Price-limit snapshot facts are append-only.")
        if self.raw_payload_hash != self.raw_payload.payload_hash:
            raise ValidationError("Price-limit snapshot raw payload identity differs.")
        kwargs.pop("force_insert", None)
        kwargs["force_insert"] = True
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Preserve exact limit source facts and their first-recorded time."""

        raise ValidationError("Price-limit snapshot facts are append-only.")


__all__ = ["PriceLimitSnapshotFactModel"]
