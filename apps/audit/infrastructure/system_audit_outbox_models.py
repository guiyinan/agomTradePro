"""Schema-only transactional outbox storage for system audit events.

The outbox deliberately has no dispatcher or repository in this batch.  Its
event identity and payload are immutable after insertion; only bounded claim
state may be changed by the future dispatcher.  Keeping that distinction in
the ORM model prevents a retry worker from silently rewriting the event it is
supposed to deliver.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete

_UOW: ContextVar[object | None] = ContextVar("system_audit_outbox_uow", default=None)
_CLAIM: ContextVar["_InsertClaim | None"] = ContextVar(
    "system_audit_outbox_insert_claim", default=None
)


@dataclass(frozen=True, slots=True)
class _InsertClaim:
    """Private capability for one exact outbox row insert."""

    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


@contextmanager
def _activate_system_audit_outbox_uow(token: object) -> Iterator[None]:
    """Activate the repository-owned non-nestable outbox UOW."""

    if _UOW.get() is not None:
        raise ValidationError("system audit outbox UOWs may not be nested")
    reset = _UOW.set(token)
    try:
        yield
    finally:
        _UOW.reset(reset)


@contextmanager
def _claim_system_audit_outbox_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Allow one exact new outbox row inside the active private UOW."""

    if _UOW.get() is not token:
        raise ValidationError("system audit outbox insert requires a private UOW")
    if _CLAIM.get() is not None:
        raise ValidationError("system audit outbox insert claims may not be nested")
    reset = _CLAIM.set(
        _InsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _CLAIM.reset(reset)

_IMMUTABLE_FIELDS = frozenset(
    {
        "outbox_id",
        "event_id",
        "idempotency_key",
        "payload",
        "payload_hash",
        "created_at",
    }
)


def _reject_immutable_fields(fields: Iterable[str]) -> None:
    changed = _IMMUTABLE_FIELDS.intersection(fields)
    if changed:
        names = ", ".join(sorted(changed))
        raise ValidationError(f"system audit outbox payload is immutable: {names}")


class SystemAuditOutboxQuerySet(models.QuerySet["SystemAuditOutboxModel"]):
    """Permit claim-state updates but reject payload and deletion shortcuts."""

    def update(self, **kwargs: object) -> int:
        _reject_immutable_fields(kwargs)
        return super().update(**kwargs)

    def bulk_update(
        self,
        objs: Iterable[SystemAuditOutboxModel],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        field_names = tuple(fields)
        _reject_immutable_fields(field_names)
        return super().bulk_update(objs, field_names, batch_size=batch_size)

    def delete(self) -> NoReturn:
        raise ValidationError("system audit outbox rows cannot be deleted")

    def _raw_delete(self, using: str | None) -> NoReturn:
        del using
        raise ValidationError("system audit outbox rows cannot be deleted")


class SystemAuditOutboxManager(models.Manager["SystemAuditOutboxModel"]):
    """Expose claim-safe querysets while retaining insert support."""

    def get_queryset(self) -> SystemAuditOutboxQuerySet:
        return SystemAuditOutboxQuerySet(self.model, using=self._db)

    def bulk_update(
        self,
        objs: Iterable[SystemAuditOutboxModel],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        field_names = tuple(fields)
        _reject_immutable_fields(field_names)
        return super().bulk_update(objs, field_names, batch_size=batch_size)


class SystemAuditOutboxModel(models.Model):
    """One immutable event payload awaiting controlled dispatch.

    ``status``, attempt counters and claim timestamps are intentionally
    mutable.  The event identity, idempotency key, payload, payload hash and
    creation clock are not.
    """

    STATUS_PENDING = "pending"
    STATUS_CLAIMED = "claimed"
    STATUS_DELIVERED = "delivered"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_PENDING, "pending"),
        (STATUS_CLAIMED, "claimed"),
        (STATUS_DELIVERED, "delivered"),
        (STATUS_FAILED, "failed"),
    )

    outbox_id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    event_id = models.CharField(max_length=128, unique=True)
    idempotency_key = models.CharField(max_length=256, unique=True)
    payload = models.JSONField(encoder=DjangoJSONEncoder)
    payload_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(db_index=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    claimed_by = models.CharField(max_length=128, null=True, blank=True)
    claim_token = models.CharField(max_length=128, null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=128, null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    objects = SystemAuditOutboxManager()

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Reject any attempted rewrite of immutable outbox columns."""

        if self._state.adding:
            self._require_insert_claim()
            super().save(force_insert=force_insert, using=using)
            return
        if update_fields is not None:
            _reject_immutable_fields(update_fields)
        else:
            self._assert_immutable_snapshot()
        super().save(
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Apply the same payload guard to Django's lower-level save path."""

        if self._state.adding:
            if raw or force_update or update_fields is not None:
                raise ValidationError("system audit outbox inserts are append-only")
            self._require_insert_claim()
        else:
            if update_fields is not None:
                _reject_immutable_fields(update_fields)
            else:
                self._assert_immutable_snapshot()
        super().save_base(
            raw=raw,
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def _require_insert_claim(self) -> None:
        """Reject direct ORM inserts that bypass repository enqueue."""

        claim = _CLAIM.get()
        if (
            claim is None
            or claim.token is not _UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("system audit outbox insert requires an exact private claim")

    def _assert_immutable_snapshot(self) -> None:
        if self.pk is None:
            raise ValidationError("system audit outbox identity is immutable")
        stored = type(self)._base_manager.get(pk=self.pk)
        for field_name in _IMMUTABLE_FIELDS - {"outbox_id"}:
            if getattr(stored, field_name) != getattr(self, field_name):
                raise ValidationError(f"system audit outbox field is immutable: {field_name}")

    def delete(self, *args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise ValidationError("system audit outbox rows cannot be deleted")

    class Meta:
        app_label = "audit"
        db_table = "audit_system_outbox"
        ordering = ["available_at", "created_at"]
        default_manager_name = "objects"
        base_manager_name = "objects"
        indexes = [
            models.Index(fields=["status", "available_at"], name="audit_outbox_claim_idx"),
            models.Index(fields=["claimed_by", "claimed_at"], name="audit_outbox_owner_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("pending", "claimed", "delivered", "failed")),
                name="audit_outbox_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_count__gte=0),
                name="audit_outbox_attempt_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(claimed_at__isnull=True, claimed_by__isnull=True)
                    | models.Q(claimed_at__isnull=False, claimed_by__isnull=False)
                ),
                name="audit_outbox_claim_pair",
            ),
            models.CheckConstraint(
                condition=models.Q(updated_at__gte=models.F("created_at")),
                name="audit_outbox_clock_order",
            ),
        ]


def _reject_system_audit_outbox_delete(
    sender: type[models.Model], instance: models.Model, using: str, origin: object, **kwargs: object
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("system audit outbox rows cannot be deleted")


pre_delete.connect(
    _reject_system_audit_outbox_delete,
    sender=SystemAuditOutboxModel,
    dispatch_uid="audit_system_outbox_immutable_payload_delete",
    weak=False,
)


__all__ = [
    "SystemAuditOutboxModel",
    "SystemAuditOutboxManager",
    "SystemAuditOutboxQuerySet",
    "_UOW",
    "_activate_system_audit_outbox_uow",
    "_claim_system_audit_outbox_insert",
]
