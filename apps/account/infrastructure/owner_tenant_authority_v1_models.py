"""Append-only Django ledger for owner/tenant authority v1."""

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
_UOW: ContextVar[object | None] = ContextVar("owner_tenant_authority_v1_uow", default=None)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    values: tuple[tuple[str, object], ...]


_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "owner_tenant_authority_v1_claim", default=None
)


@contextmanager
def _activate_owner_tenant_authority_v1_uow(token: object) -> Iterator[None]:
    reset = _UOW.set(token)
    try:
        yield
    finally:
        _UOW.reset(reset)


@contextmanager
def _claim_owner_tenant_authority_v1_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    if _UOW.get() is not token:
        raise ValidationError("owner/tenant authority insert requires private UOW")
    reset = _CLAIM.set(_InsertClaim(token, model_type, tuple(sorted(expected_values.items()))))
    try:
        yield
    finally:
        _CLAIM.reset(reset)


class OwnerTenantAuthorityV1QuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject bulk and private mutation paths."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("owner/tenant authority requires exact appends")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("owner/tenant authority is append-only")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("owner/tenant authority is append-only")


class OwnerTenantAuthorityV1Manager(AppendOnlyManager[_ModelT]):
    """Expose only guarded authority querysets."""

    def get_queryset(self) -> OwnerTenantAuthorityV1QuerySet[_ModelT]:
        return OwnerTenantAuthorityV1QuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("owner/tenant authority requires exact appends")


class OwnerTenantAuthorityV1Model(models.Model):
    """One immutable authority root, renewal, or revocation row."""

    objects: OwnerTenantAuthorityV1Manager[Self] = OwnerTenantAuthorityV1Manager()
    authority_id = models.CharField(max_length=192)
    authority_version = models.CharField(max_length=192)
    tenant_id = models.CharField(max_length=192)
    owner_id = models.CharField(max_length=192)
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    actor_id = models.CharField(max_length=192)
    actor_user_id = models.PositiveBigIntegerField()
    assignment_evidence_id = models.CharField(max_length=192)
    assignment_evidence_version = models.CharField(max_length=192)
    assignment_evidence_content_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=16)
    approved_actor_id = models.CharField(max_length=192)
    approved_user_id = models.PositiveBigIntegerField()
    approved_role = models.CharField(max_length=192)
    approved_kind = models.CharField(max_length=16)
    approved_is_staff = models.BooleanField()
    approved_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    supersedes_content_hash = models.CharField(max_length=64, null=True, blank=True)
    predecessor = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="successor",
    )
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    authority_owner = models.CharField(max_length=32)
    authority_artifact_type = models.CharField(max_length=64)
    authority_schema = models.CharField(max_length=64)
    permission = models.CharField(max_length=32)
    canonical_payload = models.JSONField()
    persisted_at = models.DateTimeField()

    class Meta:
        app_label = "account"
        db_table = "account_owner_tenant_authority_v1"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("authority_id", "recorded_at"),
                name="acct_own_ten_auth_pit_ix",
            ),
            models.Index(
                fields=("actor_user_id", "account_id", "recorded_at"),
                name="acct_own_ten_actor_ix",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("authority_id", "authority_version"),
                name="acct_own_ten_auth_id_uq",
            ),
            models.UniqueConstraint(
                fields=("authority_id",),
                condition=models.Q(predecessor__isnull=True),
                name="acct_own_ten_auth_root_uq",
            ),
            models.UniqueConstraint(
                fields=("supersedes_content_hash",),
                name="acct_own_ten_auth_pred_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("active", "revoked")),
                name="acct_own_ten_auth_status_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(authority_owner="account")
                    & models.Q(authority_artifact_type="owner_tenant_authority_v1")
                    & models.Q(authority_schema="account.owner_tenant_authority.v1")
                    & models.Q(permission="evidence_read")
                    & models.Q(approved_role="owner_tenant_authority_approver")
                    & models.Q(approved_kind="human")
                    & models.Q(approved_is_staff=True)
                ),
                name="acct_own_ten_auth_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(actor_id=models.F("approved_actor_id"))
                    & ~models.Q(actor_user_id=models.F("approved_user_id"))
                ),
                name="acct_own_ten_auth_actor_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(approved_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                    & models.Q(persisted_at=models.F("recorded_at"))
                ),
                name="acct_own_ten_auth_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(supersedes_content_hash__isnull=True)
                        & models.Q(predecessor__isnull=True)
                    )
                    | (
                        models.Q(supersedes_content_hash__isnull=False)
                        & models.Q(predecessor__isnull=False)
                    )
                ),
                name="acct_own_ten_auth_chain_ck",
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
        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("owner/tenant authority is append-only")
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
        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("owner/tenant authority is append-only")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("owner/tenant authority is append-only")

    def _require_claim(self) -> None:
        claim = _CLAIM.get()
        if (
            claim is None
            or claim.token is not _UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != value for name, value in claim.values)
        ):
            raise ValidationError("owner/tenant authority requires exact insert claim")


def _reject_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("owner/tenant authority is append-only")


pre_delete.connect(
    _reject_delete,
    sender=OwnerTenantAuthorityV1Model,
    dispatch_uid="OwnerTenantAuthorityV1Model_append_only",
)


__all__ = ["OwnerTenantAuthorityV1Model"]
