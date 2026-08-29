"""Durable append-only delivery receipts for canonical system-audit events."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn, Protocol

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, models, transaction
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete
from django.utils import timezone

from apps.audit.application.system_audit_composition import (
    CanonicalSystemAuditPublisherPreflight,
    CanonicalSystemAuditPublishReceipt,
    SystemAuditPublisherContractViolation,
)
from apps.audit.domain.system_audit_event import SystemAuditEvent

_INSERT: ContextVar[object | None] = ContextVar("audit_receipt_insert", default=None)


class SystemAuditDeliveryReceiptClock(Protocol):
    """Authoritative aware server clock."""

    def now(self) -> datetime:
        """Return the current aware timestamp."""


class DjangoSystemAuditDeliveryReceiptClock:
    """Django timezone-backed receipt clock."""

    def now(self) -> datetime:
        """Return Django's aware server time."""

        return timezone.now()


@dataclass(frozen=True, slots=True)
class _InsertPermit:
    model: type[models.Model]
    values: tuple[object, ...]


class _ReceiptQuerySet(models.QuerySet["SystemAuditDeliveryReceiptModel"]):
    """Reject every queryset mutation shortcut for immutable receipts."""

    def update(self, **kwargs: object) -> NoReturn:
        """Reject direct queryset updates."""

        del kwargs
        raise ValidationError("system audit delivery receipts are append-only")

    def delete(self) -> NoReturn:
        """Reject queryset deletes."""

        raise ValidationError("system audit delivery receipts are append-only")

    def _raw_delete(self, using: str | None) -> NoReturn:
        """Reject Django's internal raw queryset delete path."""

        del using
        raise ValidationError("system audit delivery receipts are append-only")

    def bulk_update(self, *args: object, **kwargs: object) -> NoReturn:
        """Reject queryset bulk updates."""

        del args, kwargs
        raise ValidationError("system audit delivery receipts are append-only")


class _ReceiptManager(models.Manager["SystemAuditDeliveryReceiptModel"]):
    """Expose only the guarded receipt queryset."""

    def get_queryset(self) -> _ReceiptQuerySet:
        """Return the append-only queryset implementation."""

        return _ReceiptQuerySet(self.model, using=self._db)

    def bulk_create(self, *args: object, **kwargs: object) -> NoReturn:
        """Reject manager bulk inserts that bypass the private permit."""

        del args, kwargs
        raise ValidationError("system audit delivery receipts are append-only")

    def bulk_update(self, *args: object, **kwargs: object) -> NoReturn:
        """Reject manager bulk updates."""

        del args, kwargs
        raise ValidationError("system audit delivery receipts are append-only")


class SystemAuditDeliveryReceiptModel(models.Model):
    """Immutable durable proof for one canonical event delivery."""

    event_id = models.CharField(max_length=128)
    event_version = models.CharField(max_length=64)
    identity_hash = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64)
    stream_id = models.CharField(max_length=256)
    sequence_no = models.PositiveBigIntegerField()
    predecessor_hash = models.CharField(max_length=64, null=True, blank=True)
    idempotency_key = models.CharField(max_length=256)
    canonical_payload = models.JSONField(encoder=DjangoJSONEncoder)
    sink_id = models.CharField(max_length=128)
    delivery_id = models.CharField(max_length=256)
    published_at = models.DateTimeField()

    objects = _ReceiptManager()

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Allow only an exact repository-owned first insert."""

        if (
            not self._state.adding
            or self.pk is not None
            or force_update
            or update_fields is not None
        ):
            raise ValidationError("system audit delivery receipts are append-only")
        permit = _INSERT.get()
        if (
            not isinstance(permit, _InsertPermit)
            or permit.model is not type(self)
            or permit.values != self._persisted_values()
        ):
            raise ValidationError("receipt insert requires an exact private permit")
        super().save(force_insert=force_insert, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Reject direct low-level ORM writes unless privately permitted."""

        if (
            raw
            or not self._state.adding
            or self.pk is not None
            or force_update
            or update_fields is not None
        ):
            raise ValidationError("system audit delivery receipts are append-only")
        permit = _INSERT.get()
        if (
            not isinstance(permit, _InsertPermit)
            or permit.model is not type(self)
            or permit.values != self._persisted_values()
        ):
            raise ValidationError("receipt insert requires an exact private permit")
        super().save_base(
            raw=raw, force_insert=force_insert, using=using, update_fields=update_fields
        )

    def delete(self, *args: object, **kwargs: object) -> NoReturn:
        """Reject instance deletion."""

        del args, kwargs
        raise ValidationError("system audit delivery receipts are append-only")

    def _persisted_values(self) -> tuple[object, ...]:
        """Return every persisted value in schema order."""

        return tuple(getattr(self, field) for field in _RECEIPT_FIELDS)

    class Meta:
        app_label = "audit"
        db_table = "audit_system_delivery_receipt"
        default_manager_name = "objects"
        base_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["event_id", "event_version"], name="audit_receipt_event_unique"
            ),
            models.UniqueConstraint(
                fields=["idempotency_key"], name="audit_receipt_idempotency_unique"
            ),
            models.UniqueConstraint(fields=["delivery_id"], name="audit_receipt_delivery_unique"),
        ]
        indexes = [
            models.Index(fields=["sink_id", "published_at"], name="audit_receipt_sink_time_idx")
        ]


class DjangoSystemAuditDeliveryReceiptPublisher:
    """Persist exact canonical delivery receipts with first-winner replay."""

    SINK_ID = "audit-system-delivery-receipt-v1"

    def __init__(
        self, *, clock: SystemAuditDeliveryReceiptClock | None = None, using: str = "default"
    ) -> None:
        if (
            type(using) is not str
            or not using
            or using.strip() != using
            or len(using) > 64
            or any(character.isspace() for character in using)
        ):
            raise ValueError("database alias must be a bounded non-empty string")
        self._clock = clock or DjangoSystemAuditDeliveryReceiptClock()
        self._using = using

    @property
    def database_alias(self) -> str:
        """Return the configured database alias."""

        return self._using

    def preflight(self) -> CanonicalSystemAuditPublisherPreflight:
        """Attest the single durable receipt sink."""

        return CanonicalSystemAuditPublisherPreflight(sink_id=self.SINK_ID, sink_kind="durable")

    def publish(self, event: SystemAuditEvent) -> CanonicalSystemAuditPublishReceipt:
        """Validate, durably append, and exactly replay one event receipt."""

        if not isinstance(event, SystemAuditEvent):
            raise SystemAuditPublisherContractViolation("publisher event type was substituted")
        try:
            event.validate_hashes()
        except (TypeError, ValueError) as exc:
            raise SystemAuditPublisherContractViolation(
                "publisher received an invalid canonical event"
            ) from exc
        published_at = self._clock.now()
        if published_at.tzinfo is None or published_at.utcoffset() is None:
            raise SystemAuditPublisherContractViolation("publisher clock is naive")
        if published_at < event.recorded_at:
            raise SystemAuditPublisherContractViolation("publisher clock precedes event clock")
        delivery_id = self._delivery_id(event)
        values = {
            "event_id": event.event_id,
            "event_version": event.event_version,
            "identity_hash": event.identity_hash,
            "content_hash": event.content_hash,
            "stream_id": event.stream_id,
            "sequence_no": event.sequence_no,
            "predecessor_hash": event.predecessor_hash,
            "idempotency_key": event.idempotency_key,
            "canonical_payload": event.to_payload(),
            "sink_id": self.SINK_ID,
            "delivery_id": delivery_id,
            "published_at": published_at,
        }
        row = self._find_existing(event, lock=False)
        if row is not None:
            self._validate_row(row, event, delivery_id)
            return self._receipt(row)
        try:
            with transaction.atomic(using=self._using):
                row = self._find_existing(event, lock=True)
                if row is None:
                    row = SystemAuditDeliveryReceiptModel(**values)
                    token = _INSERT.set(_InsertPermit(type(row), row._persisted_values()))
                    try:
                        row.save(force_insert=True, using=self._using)
                    finally:
                        _INSERT.reset(token)
                self._validate_row(row, event, delivery_id)
        except IntegrityError:
            with transaction.atomic(using=self._using):
                row = self._find_existing(event, lock=True)
                if row is None:
                    raise SystemAuditPublisherContractViolation(
                        "receipt identity conflict"
                    ) from None
                self._validate_row(row, event, delivery_id)
        return self._receipt(row)

    @staticmethod
    def _delivery_id(event: SystemAuditEvent) -> str:
        raw = f"{event.event_id}\0{event.event_version}\0{event.idempotency_key}".encode()
        return "audit-delivery:" + hashlib.sha256(raw).hexdigest()

    def _validate_row(
        self, row: SystemAuditDeliveryReceiptModel, event: SystemAuditEvent, delivery_id: str
    ) -> None:
        receipt = self._receipt(row)
        receipt.validate_for(event, expected_sink_id=self.SINK_ID)
        if receipt.delivery_id != delivery_id:
            raise SystemAuditPublisherContractViolation("receipt delivery identity conflict")

    def _find_existing(
        self,
        event: SystemAuditEvent,
        *,
        lock: bool,
    ) -> SystemAuditDeliveryReceiptModel | None:
        """Find a winner sharing event, idempotency, or delivery identity."""

        queryset = SystemAuditDeliveryReceiptModel.objects.using(self._using)
        if lock:
            queryset = queryset.select_for_update()
        matches = tuple(
            queryset.filter(
                models.Q(event_id=event.event_id, event_version=event.event_version)
                | models.Q(idempotency_key=event.idempotency_key)
                | models.Q(delivery_id=self._delivery_id(event))
            )
        )
        if len(matches) > 1:
            raise SystemAuditPublisherContractViolation(
                "receipt identities resolve to different winners"
            )
        return matches[0] if matches else None

    @staticmethod
    def _receipt(row: SystemAuditDeliveryReceiptModel) -> CanonicalSystemAuditPublishReceipt:
        return CanonicalSystemAuditPublishReceipt(
            event_id=row.event_id,
            event_version=row.event_version,
            identity_hash=row.identity_hash,
            content_hash=row.content_hash,
            stream_id=row.stream_id,
            sequence_no=row.sequence_no,
            predecessor_hash=row.predecessor_hash,
            idempotency_key=row.idempotency_key,
            canonical_payload=row.canonical_payload,
            sink_id=row.sink_id,
            delivery_id=row.delivery_id,
            published_at=row.published_at,
        )


__all__ = ["DjangoSystemAuditDeliveryReceiptPublisher", "SystemAuditDeliveryReceiptModel"]


_RECEIPT_FIELDS = (
    "event_id",
    "event_version",
    "identity_hash",
    "content_hash",
    "stream_id",
    "sequence_no",
    "predecessor_hash",
    "idempotency_key",
    "canonical_payload",
    "sink_id",
    "delivery_id",
    "published_at",
)


def _reject_receipt_delete(sender: type[models.Model], **kwargs: object) -> NoReturn:
    """Reject signal-level receipt deletion."""

    raise ValidationError("system audit delivery receipts are append-only")


pre_delete.connect(
    _reject_receipt_delete,
    sender=SystemAuditDeliveryReceiptModel,
    dispatch_uid="audit_system_delivery_receipt_append_only_delete",
)
