"""Append-only storage model for Broker Plan-to-Order bindings."""

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
_ACTIVE_PLAN_ORDER_BINDING_UOW: ContextVar[object | None] = ContextVar(
    "active_plan_order_binding_uow", default=None
)


@dataclass(frozen=True)
class _PlanOrderBindingInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_PLAN_ORDER_BINDING_CLAIM: ContextVar[_PlanOrderBindingInsertClaim | None] = ContextVar(
    "active_plan_order_binding_claim", default=None
)


@contextmanager
def _activate_plan_order_binding_uow(token: object) -> Iterator[None]:
    """Activate only this ledger's private UOW token."""

    reset = _ACTIVE_PLAN_ORDER_BINDING_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_PLAN_ORDER_BINDING_UOW.reset(reset)


@contextmanager
def _claim_plan_order_binding_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact repository-controlled binding insert."""

    if _ACTIVE_PLAN_ORDER_BINDING_UOW.get() is not token:
        raise ValidationError("Plan-to-Order binding insert requires its private UOW.")
    reset = _ACTIVE_PLAN_ORDER_BINDING_CLAIM.set(
        _PlanOrderBindingInsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_PLAN_ORDER_BINDING_CLAIM.reset(reset)


class PlanOrderBindingQuerySet(AppendOnlyQuerySet[_ModelT]):
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
        raise ValidationError("Plan-to-Order bindings require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Plan-to-Order bindings cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("Plan-to-Order bindings cannot be deleted.")


class PlanOrderBindingManager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> PlanOrderBindingQuerySet[_ModelT]:
        return PlanOrderBindingQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Plan-to-Order bindings require exact repository appends.")


class BrokerPlanOrderBindingModel(models.Model):
    """One immutable inactive exact Plan-to-Order binding seal."""

    objects: PlanOrderBindingManager[Self] = PlanOrderBindingManager()

    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    permission = models.CharField(max_length=16)
    blocker_codes = models.JSONField()
    binding_id = models.CharField(max_length=192)
    binding_version = models.CharField(max_length=64)
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    portfolio_plan_owner = models.CharField(max_length=32)
    portfolio_plan_artifact_type = models.CharField(max_length=64)
    portfolio_plan_id = models.CharField(max_length=192)
    portfolio_plan_version = models.PositiveBigIntegerField()
    portfolio_plan_content_hash = models.CharField(max_length=64)
    portfolio_plan_valid_until = models.DateTimeField()
    portfolio_account_id = models.CharField(max_length=192)
    portfolio_receipt_owner = models.CharField(max_length=32)
    portfolio_receipt_capability = models.CharField(max_length=64)
    portfolio_receipt_id = models.CharField(max_length=192)
    portfolio_receipt_version = models.CharField(max_length=192)
    portfolio_receipt_content_hash = models.CharField(max_length=64)
    portfolio_receipt_valid_until = models.DateTimeField()
    portfolio_subject_id = models.CharField(max_length=192)
    portfolio_subject_version = models.CharField(max_length=192)
    portfolio_subject_content_hash = models.CharField(max_length=64)
    plan_order_ordinal = models.PositiveBigIntegerField()
    plan_order_payload_json = models.TextField()
    plan_order_content_hash = models.CharField(max_length=64)
    broker_account_id = models.PositiveBigIntegerField()
    order_artifact_owner = models.CharField(max_length=32)
    order_artifact_type = models.CharField(max_length=64)
    order_artifact_id = models.UUIDField()
    order_artifact_version = models.CharField(max_length=192)
    order_artifact_identity_hash = models.CharField(max_length=64)
    order_artifact_content_hash = models.CharField(max_length=64)
    order_artifact_valid_until = models.DateTimeField()
    order_approval_digest = models.CharField(max_length=64)
    order_version = models.PositiveBigIntegerField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    supersedes_binding_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    root_claim_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    canonical_payload = models.JSONField()
    canonical_row_byte_hash = models.CharField(max_length=64)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_plan_order_binding"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=(
                    "portfolio_plan_id",
                    "portfolio_plan_version",
                    "plan_order_ordinal",
                    "order_artifact_id",
                    "recorded_at",
                ),
                name="broker_plan_order_chain_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("binding_id", "binding_version"),
                name="broker_plan_order_id_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="broker_execution",
                    artifact_type="plan_order_binding",
                    schema="broker-plan-order-binding.v1",
                    binding_version="broker-plan-order-binding.v1",
                    permission="inactive",
                    portfolio_plan_owner="portfolio",
                    portfolio_plan_artifact_type="transition_plan_definition",
                    portfolio_receipt_owner="portfolio",
                    portfolio_receipt_capability="transition_plan_inactive_approval",
                    order_artifact_owner="broker_execution",
                    order_artifact_type="live_order_approval_snapshot",
                ),
                name="broker_plan_order_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        persisted_at=models.F("recorded_at"),
                        recorded_at__lt=models.F("valid_until"),
                        valid_until__lte=models.F("portfolio_plan_valid_until"),
                    )
                    & models.Q(valid_until__lte=models.F("portfolio_receipt_valid_until"))
                    & models.Q(valid_until__lte=models.F("order_artifact_valid_until"))
                ),
                name="broker_plan_order_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        supersedes_binding_hash__isnull=True,
                        root_claim_hash__isnull=False,
                    )
                    | models.Q(
                        supersedes_binding_hash__isnull=False,
                        root_claim_hash__isnull=True,
                    )
                ),
                name="broker_plan_order_link_ck",
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
            raise ValidationError("Plan-to-Order bindings are append-only.")
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
            raise ValidationError("Plan-to-Order bindings are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_PLAN_ORDER_BINDING_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_PLAN_ORDER_BINDING_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Plan-to-Order binding requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Plan-to-Order bindings cannot be deleted.")


def _reject_plan_order_binding_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("Plan-to-Order bindings cannot be deleted.")


pre_delete.connect(
    _reject_plan_order_binding_delete,
    sender=BrokerPlanOrderBindingModel,
    dispatch_uid="reject_broker_plan_order_binding_delete",
    weak=False,
)


__all__ = ["BrokerPlanOrderBindingModel"]
