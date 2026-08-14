"""Append-only Django models for actor-authority source v3."""

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
_ACTIVE_AUTHORITY_V3_UOW: ContextVar[object | None] = ContextVar(
    "active_actor_authority_source_v3_uow", default=None
)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_AUTHORITY_V3_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_actor_authority_source_v3_claim", default=None
)


@contextmanager
def _activate_account_owner_assignment_actor_authority_source_v3_uow(
    token: object,
) -> Iterator[None]:
    """Activate the private authority-ledger unit of work."""

    reset = _ACTIVE_AUTHORITY_V3_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_AUTHORITY_V3_UOW.reset(reset)


@contextmanager
def _claim_account_owner_assignment_actor_authority_source_v3_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact root-lock or ledger insert."""

    if _ACTIVE_AUTHORITY_V3_UOW.get() is not token:
        raise ValidationError("actor authority insert requires its private UOW")
    reset = _ACTIVE_AUTHORITY_V3_CLAIM.set(
        _InsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_AUTHORITY_V3_CLAIM.reset(reset)


class _AuthorityQuerySet(AppendOnlyQuerySet[_ModelT]):
    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("actor authority ledgers require exact repository appends")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("actor authority ledgers cannot be updated")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("actor authority ledgers cannot be deleted")


class _AuthorityManager(AppendOnlyManager[_ModelT]):
    def get_queryset(self) -> _AuthorityQuerySet[_ModelT]:
        return _AuthorityQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("actor authority ledgers require exact repository appends")


class _GuardedModel(models.Model):
    objects = _AuthorityManager()

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def _require_claim(self) -> None:
        claim = _ACTIVE_AUTHORITY_V3_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_AUTHORITY_V3_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("actor authority insert requires an exact private claim")

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("actor authority ledgers are append-only")
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
            raise ValidationError("actor authority ledgers are append-only")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("actor authority ledgers cannot be deleted")


class AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel(_GuardedModel):
    """Candidate-independent serialization row for an empty source chain."""

    source_id = models.CharField(max_length=192, unique=True)
    root_claim_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField()

    class Meta(_GuardedModel.Meta):
        app_label = "account"
        db_table = "account_actor_authority_source_v3_root_lock"


class AccountOwnerAssignmentActorAuthoritySourceV3Model(_GuardedModel):
    """Complete immutable projection of one Domain authority-source version."""

    root_lock = models.ForeignKey(
        AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    predecessor = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="successor"
    )
    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=96)
    schema = models.CharField(max_length=96)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    must_not_execute = models.BooleanField()
    execution_allowed = models.BooleanField()
    source_id = models.CharField(max_length=192)
    source_version = models.CharField(max_length=192)
    principal_id = models.CharField(max_length=192)
    user_id = models.PositiveBigIntegerField()
    authentication_context_id = models.CharField(max_length=192)
    authentication_context_version = models.CharField(max_length=192)
    authentication_context_identity_hash = models.CharField(max_length=64)
    authentication_context_content_hash = models.CharField(max_length=64)
    user_source_id = models.CharField(max_length=192)
    user_source_version = models.CharField(max_length=192)
    user_source_content_hash = models.CharField(max_length=64)
    rbac_source_id = models.CharField(max_length=192)
    rbac_source_version = models.CharField(max_length=192)
    rbac_source_content_hash = models.CharField(max_length=64)
    actor_id = models.CharField(max_length=192)
    is_authenticated = models.BooleanField()
    is_active = models.BooleanField()
    is_staff = models.BooleanField()
    is_superuser = models.BooleanField()
    rbac_role = models.CharField(max_length=192)
    authority_state = models.CharField(max_length=16)
    principal_authenticated_at = models.DateTimeField()
    principal_valid_until = models.DateTimeField()
    source_recorded_at = models.DateTimeField()
    source_valid_until = models.DateTimeField()
    issued_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    ttl_valid_until = models.DateTimeField()
    valid_until = models.DateTimeField(db_index=True)
    root_claim_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    supersedes_content_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    identity_hash = models.CharField(max_length=64, unique=True)
    principal_seal = models.CharField(max_length=64)
    authentication_context_seal = models.CharField(max_length=64)
    user_seal = models.CharField(max_length=64)
    rbac_seal = models.CharField(max_length=64)
    facts_seal = models.CharField(max_length=64)
    clock_seal = models.CharField(max_length=64)
    chain_seal = models.CharField(max_length=64)
    fixed_authority_seal = models.CharField(max_length=64)
    record_seal = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    recorded_by_service_id = models.CharField(max_length=192)
    recorded_by_role = models.CharField(max_length=192)
    recorded_by_kind = models.CharField(max_length=16)
    recorded_by_is_automated = models.BooleanField()
    recorder_binding_seal = models.CharField(max_length=64)
    ledger_seal = models.CharField(max_length=64, unique=True)
    canonical_payload = models.JSONField()
    persisted_at = models.DateTimeField()

    class Meta(_GuardedModel.Meta):
        app_label = "account"
        db_table = "account_actor_authority_source_v3_ledger"
        indexes = [models.Index(fields=("source_id", "recorded_at"), name="acct_aav3_chain_ix")]
        constraints = [
            models.UniqueConstraint(
                fields=("source_id", "source_version"), name="acct_aav3_source_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="account_owner_assignment_actor_authority_source_v3",
                    schema="account.owner_assignment_actor_authority_source.v3",
                    permission="attestation_only",
                    status="inactive",
                    must_not_execute=True,
                    execution_allowed=False,
                    recorded_by_role="account_actor_authority_attestor",
                    recorded_by_kind="service",
                    recorded_by_is_automated=True,
                ),
                name="acct_aav3_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(authority_state__in=("current", "revoked", "deactivated"))
                    & (
                        ~models.Q(authority_state="current")
                        | models.Q(is_authenticated=True, is_active=True)
                    )
                ),
                name="acct_aav3_state_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        root_claim_hash__isnull=False,
                        supersedes_content_hash__isnull=True,
                        predecessor__isnull=True,
                    )
                    | models.Q(
                        root_claim_hash__isnull=True,
                        supersedes_content_hash__isnull=False,
                        predecessor__isnull=False,
                    )
                ),
                name="acct_aav3_root_xor_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(principal_authenticated_at__lte=models.F("source_recorded_at"))
                    & models.Q(source_recorded_at__lte=models.F("issued_at"))
                    & models.Q(issued_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                    & models.Q(valid_until__lte=models.F("principal_valid_until"))
                    & models.Q(valid_until__lte=models.F("source_valid_until"))
                    & models.Q(valid_until__lte=models.F("ttl_valid_until"))
                    & models.Q(persisted_at=models.F("recorded_at"))
                ),
                name="acct_aav3_clock_ck",
            ),
        ]


def _reject_delete(
    sender: type[models.Model], instance: models.Model, using: str, origin: object, **kwargs: object
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("actor authority ledgers cannot be deleted")


for _model in (
    AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
):
    pre_delete.connect(
        _reject_delete, sender=_model, dispatch_uid=f"reject_{_model.__name__}_delete", weak=False
    )


__all__ = [
    "AccountOwnerAssignmentActorAuthoritySourceV3Model",
    "AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel",
]
