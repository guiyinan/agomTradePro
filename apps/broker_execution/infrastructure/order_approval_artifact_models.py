"""Append-only storage model for Broker order approval artifacts."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, Self, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_ORDER_APPROVAL_ARTIFACT_UOW: ContextVar[object | None] = ContextVar(
    "active_broker_order_approval_artifact_uow", default=None
)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_ORDER_APPROVAL_ARTIFACT_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_broker_order_approval_artifact_claim", default=None
)


@contextmanager
def _activate_order_approval_artifact_uow(token: object) -> Iterator[None]:
    """Activate this ledger's private unit-of-work token."""

    reset = _ACTIVE_ORDER_APPROVAL_ARTIFACT_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_ORDER_APPROVAL_ARTIFACT_UOW.reset(reset)


@contextmanager
def _claim_order_approval_artifact_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact repository-controlled insert."""

    if _ACTIVE_ORDER_APPROVAL_ARTIFACT_UOW.get() is not token:
        raise ValidationError("Order approval artifact insert requires its private UOW.")
    reset = _ACTIVE_ORDER_APPROVAL_ARTIFACT_CLAIM.set(
        _InsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_ORDER_APPROVAL_ARTIFACT_CLAIM.reset(reset)


class OrderApprovalArtifactQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject bulk insertion, mutation, and raw deletion shortcuts."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Order approval artifacts require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Order approval artifacts cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("Order approval artifacts cannot be deleted.")


class OrderApprovalArtifactManager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> OrderApprovalArtifactQuerySet[_ModelT]:
        return OrderApprovalArtifactQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Order approval artifacts require exact repository appends.")


class BrokerOrderApprovalArtifactModel(models.Model):
    """One immutable Broker-owned order approval artifact first winner."""

    objects: OrderApprovalArtifactManager[Self] = OrderApprovalArtifactManager()

    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    artifact_id = models.UUIDField()
    artifact_version = models.CharField(max_length=128)
    client_order_id = models.UUIDField()
    account_id = models.PositiveBigIntegerField()
    order_version = models.PositiveIntegerField()
    approval_digest = models.CharField(max_length=64)
    approved_actor_id = models.CharField(max_length=192)
    approved_actor_user_id = models.PositiveBigIntegerField()
    approved_actor_role = models.CharField(max_length=192)
    approved_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_order_approval_artifact"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("client_order_id", "order_version", "recorded_at"),
                name="broker_ord_ap_art_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("artifact_id", "artifact_version"),
                name="broker_ord_ap_art_id_uq",
            ),
            models.UniqueConstraint(
                fields=("client_order_id", "order_version"),
                name="broker_ord_ap_art_order_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    artifact_type="live_order_approval_snapshot",
                    owner="broker_execution",
                    schema="broker-live-order-approval-artifact.v1",
                ),
                name="broker_ord_ap_art_owner_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    approved_at__lte=models.F("recorded_at"),
                    persisted_at=models.F("recorded_at"),
                    recorded_at__lt=models.F("valid_until"),
                ),
                name="broker_ord_ap_art_clock_ck",
            ),
        ]

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Permit only one exact repository-claimed insert."""

        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("Order approval artifacts are append-only.")
        self._require_claim()
        super().save(force_insert=force_insert, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Reject raw fixture and update bypasses."""

        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("Order approval artifacts are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_ORDER_APPROVAL_ARTIFACT_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_ORDER_APPROVAL_ARTIFACT_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Order approval artifact requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Order approval artifacts cannot be deleted.")


def _reject_order_approval_artifact_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject collector deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Order approval artifacts cannot be deleted.")


pre_delete.connect(
    _reject_order_approval_artifact_delete,
    sender=BrokerOrderApprovalArtifactModel,
    dispatch_uid="reject_broker_execution_order_approval_artifact_delete",
    weak=False,
)


__all__ = ["BrokerOrderApprovalArtifactModel"]
