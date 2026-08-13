"""Append-only storage model for Account identity snapshot records."""

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
_ACTIVE_ACCOUNT_IDENTITY_SNAPSHOT_UOW: ContextVar[object | None] = ContextVar(
    "active_account_identity_snapshot_uow",
    default=None,
)


@dataclass(frozen=True)
class _AccountIdentitySnapshotInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_ACCOUNT_IDENTITY_SNAPSHOT_CLAIM: ContextVar[_AccountIdentitySnapshotInsertClaim | None] = (
    ContextVar("active_account_identity_snapshot_claim", default=None)
)


@contextmanager
def _activate_account_identity_snapshot_uow(token: object) -> Iterator[None]:
    """Activate only this ledger's private unit-of-work token."""

    reset = _ACTIVE_ACCOUNT_IDENTITY_SNAPSHOT_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_ACCOUNT_IDENTITY_SNAPSHOT_UOW.reset(reset)


@contextmanager
def _claim_account_identity_snapshot_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Claim one exact repository-controlled identity record insert."""

    if _ACTIVE_ACCOUNT_IDENTITY_SNAPSHOT_UOW.get() is not token:
        raise ValidationError("Account identity insert requires its private UOW.")
    reset = _ACTIVE_ACCOUNT_IDENTITY_SNAPSHOT_CLAIM.set(
        _AccountIdentitySnapshotInsertClaim(
            token,
            model_type,
            tuple(sorted(expected_values.items())),
        )
    )
    try:
        yield
    finally:
        _ACTIVE_ACCOUNT_IDENTITY_SNAPSHOT_CLAIM.reset(reset)


class AccountIdentitySnapshotQuerySet(AppendOnlyQuerySet[_ModelT]):
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
        raise ValidationError("Account identity snapshots require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Account identity snapshots cannot be updated.")

    def _raw_delete(self, using: str) -> NoReturn:
        raise ValidationError("Account identity snapshots cannot be deleted.")


class AccountIdentitySnapshotManager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> AccountIdentitySnapshotQuerySet[_ModelT]:
        return AccountIdentitySnapshotQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Account identity snapshots require exact repository appends.")


class AccountIdentitySnapshotModel(models.Model):
    """One immutable actor-bound Account identity snapshot ledger record."""

    objects: AccountIdentitySnapshotManager[models.Model] = AccountIdentitySnapshotManager()

    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    source_id = models.CharField(max_length=192)
    source_version = models.CharField(max_length=192)
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    underlying_unified_account_namespace = models.CharField(max_length=192)
    underlying_unified_account_id = models.PositiveBigIntegerField()
    owner_user_id = models.PositiveBigIntegerField()
    account_type = models.CharField(max_length=16)
    is_active = models.BooleanField()
    provenance_kind = models.CharField(max_length=32)
    legacy_default_user_assignment = models.BooleanField()
    underlying_source_id = models.CharField(max_length=192)
    underlying_source_version = models.CharField(max_length=192)
    underlying_source_content_hash = models.CharField(max_length=64)
    underlying_source_recorded_at = models.DateTimeField()
    underlying_source_valid_until = models.DateTimeField()
    ttl_valid_until = models.DateTimeField()
    issued_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    reclaim_receipt_owner = models.CharField(max_length=32, null=True, blank=True)
    reclaim_receipt_artifact_type = models.CharField(max_length=64, null=True, blank=True)
    reclaim_receipt_id = models.CharField(max_length=192, null=True, blank=True)
    reclaim_receipt_version = models.CharField(max_length=192, null=True, blank=True)
    reclaim_receipt_content_hash = models.CharField(max_length=64, null=True, blank=True)
    supersedes_content_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    root_claim_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    blocker_codes = models.JSONField()
    issued_actor_id = models.CharField(max_length=192)
    issued_actor_user_id = models.PositiveBigIntegerField()
    issued_actor_role = models.CharField(max_length=192)
    issued_actor_kind = models.CharField(max_length=16)
    issued_actor_is_staff = models.BooleanField()
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    actor_binding_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta:
        app_label = "account"
        db_table = "account_identity_snapshot_ledger"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("account_namespace", "account_id", "recorded_at"),
                name="account_id_snap_chain_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("source_id", "source_version"),
                name="account_id_snap_identity_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="account_identity_snapshot",
                    schema="account-identity-snapshot.v1",
                    permission="identity_evidence_only",
                    status="inactive",
                    account_type="real",
                    is_active=True,
                    issued_actor_kind="human",
                    issued_actor_is_staff=True,
                ),
                name="account_id_snap_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        underlying_source_recorded_at__lte=models.F("issued_at"),
                        issued_at__lte=models.F("recorded_at"),
                        recorded_at__lt=models.F("valid_until"),
                        valid_until__lte=models.F("underlying_source_valid_until"),
                        persisted_at=models.F("recorded_at"),
                    )
                    & models.Q(valid_until__lte=models.F("ttl_valid_until"))
                ),
                name="account_id_snap_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        supersedes_content_hash__isnull=True,
                        root_claim_hash__isnull=False,
                    )
                    | models.Q(
                        supersedes_content_hash__isnull=False,
                        root_claim_hash__isnull=True,
                    )
                ),
                name="account_id_snap_link_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        provenance_kind="authoritative",
                        legacy_default_user_assignment=False,
                        reclaim_receipt_owner__isnull=True,
                        reclaim_receipt_artifact_type__isnull=True,
                        reclaim_receipt_id__isnull=True,
                        reclaim_receipt_version__isnull=True,
                        reclaim_receipt_content_hash__isnull=True,
                    )
                    | models.Q(
                        provenance_kind="manual_reclaim",
                        legacy_default_user_assignment=True,
                        reclaim_receipt_owner="account",
                        reclaim_receipt_artifact_type="account_owner_reclaim_receipt",
                        reclaim_receipt_id__isnull=False,
                        reclaim_receipt_version__isnull=False,
                        reclaim_receipt_content_hash__isnull=False,
                    )
                ),
                name="account_id_snap_prov_ck",
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
            raise ValidationError("Account identity snapshots are append-only.")
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
            raise ValidationError("Account identity snapshots are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_ACCOUNT_IDENTITY_SNAPSHOT_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_ACCOUNT_IDENTITY_SNAPSHOT_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Account identity snapshot requires an exact insert claim.")

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Account identity snapshots cannot be deleted.")


def _reject_account_identity_snapshot_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject collector deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Account identity snapshots cannot be deleted.")


pre_delete.connect(
    _reject_account_identity_snapshot_delete,
    sender=AccountIdentitySnapshotModel,
    dispatch_uid="reject_account_identity_snapshot_delete",
    weak=False,
)


__all__ = ["AccountIdentitySnapshotModel"]
