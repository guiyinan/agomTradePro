"""Append-only storage model for Broker account identity snapshots."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_BROKER_ACCOUNT_IDENTITY_UOW: ContextVar[object | None] = ContextVar(
    "active_broker_account_identity_uow", default=None
)


@dataclass(frozen=True)
class _BrokerAccountIdentityInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_BROKER_ACCOUNT_IDENTITY_CLAIM: ContextVar[_BrokerAccountIdentityInsertClaim | None] = (
    ContextVar("active_broker_account_identity_claim", default=None)
)


@contextmanager
def _activate_broker_account_identity_uow(token: object) -> Iterator[None]:
    """Activate only this ledger's private unit-of-work token."""

    reset = _ACTIVE_BROKER_ACCOUNT_IDENTITY_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_BROKER_ACCOUNT_IDENTITY_UOW.reset(reset)


@contextmanager
def _claim_broker_account_identity_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact repository-controlled snapshot insert."""

    if _ACTIVE_BROKER_ACCOUNT_IDENTITY_UOW.get() is not token:
        raise ValidationError("Broker account identity insert requires its private UOW.")
    reset = _ACTIVE_BROKER_ACCOUNT_IDENTITY_CLAIM.set(
        _BrokerAccountIdentityInsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_BROKER_ACCOUNT_IDENTITY_CLAIM.reset(reset)


class BrokerAccountIdentityQuerySet(AppendOnlyQuerySet[_ModelT]):
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
        raise ValidationError("Broker account identity snapshots require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Broker account identity snapshots cannot be updated.")

    def _raw_delete(self, using: str) -> NoReturn:
        raise ValidationError("Broker account identity snapshots cannot be deleted.")


class BrokerAccountIdentityManager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> BrokerAccountIdentityQuerySet[_ModelT]:
        return BrokerAccountIdentityQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Broker account identity snapshots require exact repository appends.")


class BrokerAccountIdentitySnapshotModel(models.Model):
    """One immutable actor-bound inactive Broker account identity snapshot."""

    objects: BrokerAccountIdentityManager[models.Model] = BrokerAccountIdentityManager()

    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    authority_scope = models.CharField(max_length=32)
    permission = models.CharField(max_length=16)
    snapshot_id = models.CharField(max_length=192)
    snapshot_version = models.CharField(max_length=192)
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    broker_account_namespace = models.CharField(max_length=192)
    broker_account_id = models.PositiveBigIntegerField()
    owner_user_id = models.PositiveBigIntegerField()
    account_source_owner = models.CharField(max_length=32)
    account_source_artifact_type = models.CharField(max_length=64)
    account_source_id = models.CharField(max_length=192)
    account_source_version = models.CharField(max_length=192)
    account_source_content_hash = models.CharField(max_length=64)
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    account_source_owner_user_id = models.PositiveBigIntegerField()
    account_type = models.CharField(max_length=16)
    is_active = models.BooleanField()
    account_source_recorded_at = models.DateTimeField()
    account_source_valid_until = models.DateTimeField()
    binding_revision = models.PositiveBigIntegerField()
    binding_owner_user_id = models.PositiveBigIntegerField()
    binding_content_hash = models.CharField(max_length=64)
    agent_id = models.CharField(max_length=192)
    agent_version = models.CharField(max_length=192)
    agent_owner_user_id = models.PositiveBigIntegerField()
    agent_content_hash = models.CharField(max_length=64)
    qmt_digest_algorithm = models.CharField(max_length=32)
    qmt_digest_key_id = models.CharField(max_length=192)
    qmt_digest = models.CharField(max_length=64)
    broker_account_category = models.CharField(max_length=192)
    issued_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    ttl_valid_until = models.DateTimeField()
    valid_until = models.DateTimeField(db_index=True)
    supersedes_snapshot_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    root_claim_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    actor_id = models.CharField(max_length=192)
    actor_user_id = models.PositiveBigIntegerField()
    actor_kind = models.CharField(max_length=16)
    actor_is_staff = models.BooleanField()
    canonical_payload = models.JSONField()
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta:
        app_label = "broker_execution"
        db_table = "broker_execution_account_identity_snapshot"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=(
                    "broker_account_namespace",
                    "broker_account_id",
                    "recorded_at",
                ),
                name="broker_acct_identity_chain_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("snapshot_id", "snapshot_version"),
                name="broker_acct_identity_id_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="broker_execution",
                    artifact_type="broker_account_identity_snapshot",
                    schema="broker-account-identity-snapshot.v1",
                    authority_scope="identity_evidence_only",
                    permission="inactive",
                    account_source_owner="account",
                    account_source_artifact_type="account_identity_snapshot",
                    account_type="real",
                    is_active=True,
                    actor_kind="human",
                    actor_is_staff=True,
                ),
                name="broker_acct_identity_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        persisted_at=models.F("recorded_at"),
                        issued_at__lte=models.F("recorded_at"),
                        recorded_at__lt=models.F("valid_until"),
                        valid_until__lte=models.F("ttl_valid_until"),
                    )
                    & models.Q(valid_until__lte=models.F("account_source_valid_until"))
                ),
                name="broker_acct_identity_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        supersedes_snapshot_hash__isnull=True,
                        root_claim_hash__isnull=False,
                    )
                    | models.Q(
                        supersedes_snapshot_hash__isnull=False,
                        root_claim_hash__isnull=True,
                    )
                ),
                name="broker_acct_identity_link_ck",
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
            raise ValidationError("Broker account identity snapshots are append-only.")
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
            raise ValidationError("Broker account identity snapshots are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_BROKER_ACCOUNT_IDENTITY_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_BROKER_ACCOUNT_IDENTITY_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError(
                "Broker account identity snapshot requires an exact insert claim."
            )

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Broker account identity snapshots cannot be deleted.")


def _reject_broker_account_identity_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject collector deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Broker account identity snapshots cannot be deleted.")


pre_delete.connect(
    _reject_broker_account_identity_delete,
    sender=BrokerAccountIdentitySnapshotModel,
    dispatch_uid="reject_broker_account_identity_snapshot_delete",
    weak=False,
)


__all__ = ["BrokerAccountIdentitySnapshotModel"]
