"""Append-only storage model for Account raw identity source records."""

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
_ACTIVE_RAW_SOURCE_UOW: ContextVar[object | None] = ContextVar(
    "active_account_identity_raw_source_uow", default=None
)


@dataclass(frozen=True)
class _RawSourceInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_RAW_SOURCE_CLAIM: ContextVar[_RawSourceInsertClaim | None] = ContextVar(
    "active_account_identity_raw_source_claim", default=None
)


@contextmanager
def _activate_account_identity_raw_source_uow(token: object) -> Iterator[None]:
    """Activate only this ledger's private unit-of-work token."""

    reset = _ACTIVE_RAW_SOURCE_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_RAW_SOURCE_UOW.reset(reset)


@contextmanager
def _claim_account_identity_raw_source_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Claim one exact repository-controlled raw-source insert."""

    if _ACTIVE_RAW_SOURCE_UOW.get() is not token:
        raise ValidationError("Account raw source insert requires its private UOW.")
    reset = _ACTIVE_RAW_SOURCE_CLAIM.set(
        _RawSourceInsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_RAW_SOURCE_CLAIM.reset(reset)


class AccountIdentityRawSourceQuerySet(AppendOnlyQuerySet[_ModelT]):
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
        raise ValidationError("Account raw sources require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Account raw sources cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("Account raw sources cannot be deleted.")


class AccountIdentityRawSourceManager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> AccountIdentityRawSourceQuerySet[_ModelT]:
        return AccountIdentityRawSourceQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Account raw sources require exact repository appends.")


class AccountIdentityRawSourceModel(models.Model):
    """One immutable actor-bound Account raw identity source ledger record."""

    objects: AccountIdentityRawSourceManager[Self] = AccountIdentityRawSourceManager()

    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    source_id = models.CharField(max_length=192)
    source_version = models.CharField(max_length=192)
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    underlying_unified_account_namespace = models.CharField(max_length=192)
    underlying_unified_account_id = models.PositiveBigIntegerField()
    owner_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    assignment_state = models.CharField(max_length=32)
    assignment_evidence_owner = models.CharField(max_length=32, null=True, blank=True)
    assignment_evidence_artifact_type = models.CharField(max_length=64, null=True, blank=True)
    assignment_evidence_id = models.CharField(max_length=192, null=True, blank=True)
    assignment_evidence_version = models.CharField(max_length=192, null=True, blank=True)
    assignment_evidence_content_hash = models.CharField(max_length=64, null=True, blank=True)
    row_source_owner = models.CharField(max_length=32)
    row_source_artifact_type = models.CharField(max_length=64)
    row_source_id = models.CharField(max_length=192)
    row_source_version = models.CharField(max_length=192)
    row_source_content_hash = models.CharField(max_length=64)
    observed_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    row_source_valid_until = models.DateTimeField()
    ttl_valid_until = models.DateTimeField()
    valid_until = models.DateTimeField(db_index=True)
    account_type = models.CharField(max_length=16)
    is_active = models.BooleanField()
    supersedes_content_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    root_claim_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    blocker_codes = models.JSONField()
    captured_actor_id = models.CharField(max_length=192)
    captured_actor_user_id = models.PositiveBigIntegerField()
    captured_actor_role = models.CharField(max_length=192)
    captured_actor_kind = models.CharField(max_length=16)
    captured_actor_is_staff = models.BooleanField()
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    actor_binding_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta:
        app_label = "account"
        db_table = "account_identity_raw_source_ledger"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("account_namespace", "account_id", "recorded_at"),
                name="acct_raw_src_chain_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("source_id", "source_version"),
                name="acct_raw_src_identity_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="account_identity_raw_source",
                    schema="account-identity-raw-source.v1",
                    permission="source_evidence_only",
                    status="inactive",
                    account_type="real",
                    captured_actor_kind="human",
                    captured_actor_is_staff=True,
                ),
                name="acct_raw_src_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        observed_at__lte=models.F("recorded_at"),
                        recorded_at__lt=models.F("valid_until"),
                        valid_until__lte=models.F("row_source_valid_until"),
                        persisted_at=models.F("recorded_at"),
                    )
                    & models.Q(valid_until__lte=models.F("ttl_valid_until"))
                ),
                name="acct_raw_src_clock_ck",
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
                name="acct_raw_src_link_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        assignment_state="authoritative",
                        owner_user_id__isnull=False,
                        assignment_evidence_owner="account",
                        assignment_evidence_artifact_type="account_owner_assignment_evidence",
                        assignment_evidence_id__isnull=False,
                        assignment_evidence_version__isnull=False,
                        assignment_evidence_content_hash__isnull=False,
                    )
                    | models.Q(
                        assignment_state="legacy_default",
                        owner_user_id__isnull=True,
                        assignment_evidence_owner="account",
                        assignment_evidence_artifact_type="account_owner_assignment_evidence",
                        assignment_evidence_id__isnull=False,
                        assignment_evidence_version__isnull=False,
                        assignment_evidence_content_hash__isnull=False,
                    )
                    | models.Q(
                        assignment_state="unknown",
                        owner_user_id__isnull=True,
                        assignment_evidence_owner__isnull=True,
                        assignment_evidence_artifact_type__isnull=True,
                        assignment_evidence_id__isnull=True,
                        assignment_evidence_version__isnull=True,
                        assignment_evidence_content_hash__isnull=True,
                    )
                ),
                name="acct_raw_src_assign_ck",
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
            raise ValidationError("Account raw sources are append-only.")
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
            raise ValidationError("Account raw sources are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_RAW_SOURCE_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_RAW_SOURCE_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Account raw source requires an exact insert claim.")

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Account raw sources cannot be deleted.")


def _reject_account_identity_raw_source_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject collector deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Account raw sources cannot be deleted.")


pre_delete.connect(
    _reject_account_identity_raw_source_delete,
    sender=AccountIdentityRawSourceModel,
    dispatch_uid="reject_account_identity_raw_source_delete",
    weak=False,
)


__all__ = ["AccountIdentityRawSourceModel"]
