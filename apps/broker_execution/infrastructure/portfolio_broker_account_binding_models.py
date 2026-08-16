"""Append-only model for Broker/Portfolio account namespace bindings."""

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
_ACTIVE_PORTFOLIO_BROKER_BINDING_UOW: ContextVar[object | None] = ContextVar(
    "active_portfolio_broker_binding_uow", default=None
)


@dataclass(frozen=True)
class _BindingInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_PORTFOLIO_BROKER_BINDING_CLAIM: ContextVar[_BindingInsertClaim | None] = ContextVar(
    "active_portfolio_broker_binding_claim", default=None
)


@contextmanager
def _activate_portfolio_broker_binding_uow(token: object) -> Iterator[None]:
    """Activate only this ledger's private UOW token."""

    reset = _ACTIVE_PORTFOLIO_BROKER_BINDING_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_PORTFOLIO_BROKER_BINDING_UOW.reset(reset)


@contextmanager
def _claim_portfolio_broker_binding_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact repository-controlled binding insert."""

    if _ACTIVE_PORTFOLIO_BROKER_BINDING_UOW.get() is not token:
        raise ValidationError("Portfolio/Broker binding insert requires its private UOW.")
    reset = _ACTIVE_PORTFOLIO_BROKER_BINDING_CLAIM.set(
        _BindingInsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_PORTFOLIO_BROKER_BINDING_CLAIM.reset(reset)


class PortfolioBrokerBindingQuerySet(AppendOnlyQuerySet[_ModelT]):
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
        raise ValidationError("Portfolio/Broker bindings require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Portfolio/Broker bindings cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("Portfolio/Broker bindings cannot be deleted.")


class PortfolioBrokerBindingManager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> PortfolioBrokerBindingQuerySet[_ModelT]:
        return PortfolioBrokerBindingQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Portfolio/Broker bindings require exact repository appends.")


class BrokerPortfolioAccountBindingModel(models.Model):
    """One immutable inactive cross-namespace binding assertion."""

    objects: PortfolioBrokerBindingManager[Self] = PortfolioBrokerBindingManager()

    owner = models.CharField(max_length=32)
    binding_id = models.CharField(max_length=192)
    binding_version = models.CharField(max_length=64)
    permission = models.CharField(max_length=16)
    blocker_codes = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    broker_account_namespace = models.CharField(max_length=192)
    broker_account_id = models.PositiveBigIntegerField()
    portfolio_account_namespace = models.CharField(max_length=192)
    portfolio_account_id = models.CharField(max_length=192)
    owner_user_id = models.PositiveBigIntegerField()
    account_type = models.CharField(max_length=16)
    source_accounts_active = models.BooleanField()
    broker_source_owner = models.CharField(max_length=32)
    broker_source_artifact_type = models.CharField(max_length=64)
    broker_source_id = models.CharField(max_length=192)
    broker_source_version = models.CharField(max_length=192)
    broker_source_content_hash = models.CharField(max_length=64)
    portfolio_source_owner = models.CharField(max_length=32)
    portfolio_source_artifact_type = models.CharField(max_length=64)
    portfolio_source_id = models.CharField(max_length=192)
    portfolio_source_version = models.CharField(max_length=192)
    portfolio_source_content_hash = models.CharField(max_length=64)
    actor_id = models.CharField(max_length=192)
    actor_user_id = models.PositiveBigIntegerField()
    actor_role = models.CharField(max_length=192)
    actor_kind = models.CharField(max_length=16)
    actor_is_staff = models.BooleanField()
    issued_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    supersedes_binding_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    root_claim_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    canonical_payload = models.JSONField()
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_portfolio_account_binding"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=(
                    "broker_account_namespace",
                    "broker_account_id",
                    "recorded_at",
                ),
                name="broker_portfolio_bind_chain_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("binding_id", "binding_version"),
                name="broker_portfolio_bind_id_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="broker_execution",
                    binding_version="broker-portfolio-account-namespace-binding.v1",
                    permission="inactive",
                    account_type="real",
                    source_accounts_active=True,
                    broker_source_owner="broker_execution",
                    broker_source_artifact_type="broker_account_identity_snapshot",
                    portfolio_source_owner="account",
                    portfolio_source_artifact_type="account_identity_snapshot",
                    actor_kind="human",
                    actor_is_staff=True,
                ),
                name="broker_portfolio_bind_fixed_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    persisted_at=models.F("recorded_at"),
                    issued_at__lte=models.F("recorded_at"),
                    recorded_at__lt=models.F("valid_until"),
                ),
                name="broker_portfolio_bind_clock_ck",
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
                name="broker_portfolio_bind_link_ck",
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
            raise ValidationError("Portfolio/Broker bindings are append-only.")
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
            raise ValidationError("Portfolio/Broker bindings are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_PORTFOLIO_BROKER_BINDING_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_PORTFOLIO_BROKER_BINDING_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Portfolio/Broker binding requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Portfolio/Broker bindings cannot be deleted.")


def _reject_portfolio_broker_binding_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("Portfolio/Broker bindings cannot be deleted.")


pre_delete.connect(
    _reject_portfolio_broker_binding_delete,
    sender=BrokerPortfolioAccountBindingModel,
    dispatch_uid="reject_broker_portfolio_account_binding_delete",
    weak=False,
)


__all__ = ["BrokerPortfolioAccountBindingModel"]
