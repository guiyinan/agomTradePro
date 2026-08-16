"""Append-only storage models for Broker pre-Risk execution scopes."""

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
_ACTIVE_PRE_RISK_SCOPE_UOW: ContextVar[object | None] = ContextVar(
    "active_broker_pre_risk_scope_uow", default=None
)


@dataclass(frozen=True)
class _PreRiskScopeInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_PRE_RISK_SCOPE_CLAIM: ContextVar[_PreRiskScopeInsertClaim | None] = ContextVar(
    "active_broker_pre_risk_scope_claim", default=None
)


@contextmanager
def _activate_pre_risk_scope_uow(token: object) -> Iterator[None]:
    """Activate only this ledger's private unit-of-work token."""

    reset = _ACTIVE_PRE_RISK_SCOPE_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_PRE_RISK_SCOPE_UOW.reset(reset)


@contextmanager
def _claim_pre_risk_scope_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact repository-controlled pre-Risk scope insert."""

    if _ACTIVE_PRE_RISK_SCOPE_UOW.get() is not token:
        raise ValidationError("Pre-Risk scope insert requires its private UOW.")
    reset = _ACTIVE_PRE_RISK_SCOPE_CLAIM.set(
        _PreRiskScopeInsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_PRE_RISK_SCOPE_CLAIM.reset(reset)


class PreRiskScopeQuerySet(AppendOnlyQuerySet[_ModelT]):
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
        raise ValidationError("Pre-Risk scopes require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Pre-Risk scopes cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("Pre-Risk scopes cannot be deleted.")


class PreRiskScopeManager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> PreRiskScopeQuerySet[_ModelT]:
        return PreRiskScopeQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Pre-Risk scopes require exact repository appends.")


class BrokerPreRiskExecutionScopeModel(models.Model):
    """One immutable inactive pre-Risk scope in a single logical order chain."""

    objects: PreRiskScopeManager[Self] = PreRiskScopeManager()

    owner = models.CharField(max_length=32)
    scope_id = models.CharField(max_length=192)
    scope_version = models.CharField(max_length=64)
    permission = models.CharField(max_length=16)
    broker_account_id = models.PositiveBigIntegerField()
    portfolio_account_id = models.CharField(max_length=192)
    plan_id = models.CharField(max_length=192)
    plan_version = models.PositiveIntegerField()
    plan_content_hash = models.CharField(max_length=64)
    portfolio_receipt_id = models.CharField(max_length=192)
    portfolio_receipt_version = models.CharField(max_length=192)
    portfolio_receipt_content_hash = models.CharField(max_length=64)
    order_artifact_id = models.UUIDField()
    order_artifact_version = models.CharField(max_length=192)
    order_artifact_content_hash = models.CharField(max_length=64)
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    supersedes_scope_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    root_claim_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_pre_risk_scope"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("broker_account_id", "order_artifact_id", "recorded_at"),
                name="broker_pre_risk_chain_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("scope_id", "scope_version"),
                name="broker_pre_risk_id_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="broker_execution",
                    permission="inactive",
                    scope_version="broker-pre-risk-execution-scope.v1",
                ),
                name="broker_pre_risk_fixed_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    persisted_at=models.F("recorded_at"),
                    recorded_at__lt=models.F("valid_until"),
                ),
                name="broker_pre_risk_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        supersedes_scope_hash__isnull=True,
                        root_claim_hash__isnull=False,
                    )
                    | models.Q(
                        supersedes_scope_hash__isnull=False,
                        root_claim_hash__isnull=True,
                    )
                ),
                name="broker_pre_risk_link_ck",
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
            raise ValidationError("Pre-Risk scopes are append-only.")
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
            raise ValidationError("Pre-Risk scopes are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_PRE_RISK_SCOPE_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_PRE_RISK_SCOPE_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Pre-Risk scope requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Pre-Risk scopes cannot be deleted.")


def _reject_pre_risk_scope_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject collector deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Pre-Risk scopes cannot be deleted.")


pre_delete.connect(
    _reject_pre_risk_scope_delete,
    sender=BrokerPreRiskExecutionScopeModel,
    dispatch_uid="reject_broker_execution_pre_risk_scope_delete",
    weak=False,
)


__all__ = ["BrokerPreRiskExecutionScopeModel"]
