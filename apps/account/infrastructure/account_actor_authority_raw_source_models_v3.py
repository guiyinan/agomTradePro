"""Append-only schema guards for the three Account raw authority ledgers v3."""

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
_ACTIVE_RAW_AUTHORITY_V3_UOW: ContextVar[object | None] = ContextVar(
    "active_account_raw_authority_v3_uow", default=None
)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_RAW_AUTHORITY_V3_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_account_raw_authority_v3_claim", default=None
)


@contextmanager
def _activate_account_actor_authority_raw_source_v3_uow(token: object) -> Iterator[None]:
    """Activate the private raw-authority schema unit of work."""

    if _ACTIVE_RAW_AUTHORITY_V3_UOW.get() is not None:
        raise ValidationError("raw authority UOW cannot be nested")
    reset = _ACTIVE_RAW_AUTHORITY_V3_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_RAW_AUTHORITY_V3_UOW.reset(reset)


@contextmanager
def _claim_account_actor_authority_raw_source_v3_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact anchor or ledger insert inside the private unit of work."""

    if _ACTIVE_RAW_AUTHORITY_V3_UOW.get() is not token:
        raise ValidationError("raw authority insert requires its private UOW")
    if _ACTIVE_RAW_AUTHORITY_V3_CLAIM.get() is not None:
        raise ValidationError("raw authority insert claims cannot be nested")
    reset = _ACTIVE_RAW_AUTHORITY_V3_CLAIM.set(
        _InsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_RAW_AUTHORITY_V3_CLAIM.reset(reset)


class _RawAuthorityQuerySet(AppendOnlyQuerySet[_ModelT]):
    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("raw authority ledgers require exact repository appends")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("raw authority ledgers cannot be updated")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("raw authority ledgers cannot be deleted")


class _RawAuthorityManager(AppendOnlyManager[_ModelT]):
    def get_queryset(self) -> _RawAuthorityQuerySet[_ModelT]:
        return _RawAuthorityQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("raw authority ledgers require exact repository appends")


class _GuardedRawAuthorityModel(models.Model):
    objects = _RawAuthorityManager()

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def _require_claim(self) -> None:
        claim = _ACTIVE_RAW_AUTHORITY_V3_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_RAW_AUTHORITY_V3_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("raw authority insert requires an exact private claim")

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("raw authority ledgers are append-only")
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
            raise ValidationError("raw authority ledgers are append-only")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("raw authority ledgers cannot be deleted")


class _RawAuthorityAnchor(_GuardedRawAuthorityModel):
    source_id = models.CharField(max_length=192, unique=True)
    root_claim_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField()

    class Meta(_GuardedRawAuthorityModel.Meta):
        abstract = True


class _RawAuthorityLedger(_GuardedRawAuthorityModel):
    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=96)
    schema = models.CharField(max_length=96)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    must_not_execute = models.BooleanField()
    execution_allowed = models.BooleanField()
    source_id = models.CharField(max_length=192)
    source_version = models.CharField(max_length=192)
    observed_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    root_claim_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    supersedes_content_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    identity_hash = models.CharField(max_length=64, unique=True)
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

    class Meta(_GuardedRawAuthorityModel.Meta):
        abstract = True


class AccountAuthenticationContextSourceV3AnchorModel(_RawAuthorityAnchor):
    """Serialize one authentication-context raw-source chain."""

    class Meta(_RawAuthorityAnchor.Meta):
        app_label = "account"
        db_table = "account_auth_context_source_v3_anchor"


class AccountAuthenticationContextSourceV3Model(_RawAuthorityLedger):
    """Store one complete authentication-context Domain source payload."""

    anchor = models.ForeignKey(
        AccountAuthenticationContextSourceV3AnchorModel,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    predecessor = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="successor"
    )
    principal_id = models.CharField(max_length=192)
    user_id = models.PositiveBigIntegerField()
    actor_id = models.CharField(max_length=192)
    is_authenticated = models.BooleanField()
    authority_state = models.CharField(max_length=16)
    authenticated_at = models.DateTimeField()
    principal_seal = models.CharField(max_length=64)

    class Meta(_RawAuthorityLedger.Meta):
        app_label = "account"
        db_table = "account_auth_context_source_v3_ledger"
        indexes = [models.Index(fields=("source_id", "recorded_at"), name="acct_auth3_chain_ix")]
        constraints = [
            models.UniqueConstraint(
                fields=("source_id", "source_version"), name="acct_auth3_source_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="account_authentication_context_source_v3",
                    schema="account.authentication_context_source.v3",
                    permission="attestation_only",
                    status="inactive",
                    must_not_execute=True,
                    execution_allowed=False,
                    recorded_by_role="account_actor_authority_raw_recorder",
                    recorded_by_kind="service",
                    recorded_by_is_automated=True,
                ),
                name="acct_auth3_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(authority_state="authenticated", is_authenticated=True)
                    | models.Q(authority_state="revoked", is_authenticated=False)
                ),
                name="acct_auth3_state_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(authenticated_at__lte=models.F("observed_at")),
                name="acct_auth3_auth_clock_ck",
            ),
            models.CheckConstraint(condition=models.Q(user_id__gt=0), name="acct_auth3_user_ck"),
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
                name="acct_auth3_root_xor_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(observed_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                    & models.Q(persisted_at=models.F("recorded_at"))
                ),
                name="acct_auth3_clock_ck",
            ),
        ]


class AccountUserAuthoritySourceV3AnchorModel(_RawAuthorityAnchor):
    """Serialize one Django-user raw-authority chain."""

    class Meta(_RawAuthorityAnchor.Meta):
        app_label = "account"
        db_table = "account_user_authority_source_v3_anchor"


class AccountUserAuthoritySourceV3Model(_RawAuthorityLedger):
    """Store one complete Django-user authority Domain source payload."""

    anchor = models.ForeignKey(
        AccountUserAuthoritySourceV3AnchorModel, on_delete=models.PROTECT, related_name="versions"
    )
    predecessor = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="successor"
    )
    user_id = models.PositiveBigIntegerField()
    actor_id = models.CharField(max_length=192)
    is_active = models.BooleanField()
    is_staff = models.BooleanField()
    is_superuser = models.BooleanField()
    authority_state = models.CharField(max_length=16)
    user_seal = models.CharField(max_length=64)

    class Meta(_RawAuthorityLedger.Meta):
        app_label = "account"
        db_table = "account_user_authority_source_v3_ledger"
        indexes = [models.Index(fields=("source_id", "recorded_at"), name="acct_user3_chain_ix")]
        constraints = [
            models.UniqueConstraint(
                fields=("source_id", "source_version"), name="acct_user3_source_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="account_user_authority_source_v3",
                    schema="account.user_authority_source.v3",
                    permission="attestation_only",
                    status="inactive",
                    must_not_execute=True,
                    execution_allowed=False,
                    recorded_by_role="account_actor_authority_raw_recorder",
                    recorded_by_kind="service",
                    recorded_by_is_automated=True,
                ),
                name="acct_user3_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(authority_state="current", is_active=True)
                    | models.Q(authority_state="deactivated", is_active=False)
                ),
                name="acct_user3_state_ck",
            ),
            models.CheckConstraint(condition=models.Q(user_id__gt=0), name="acct_user3_user_ck"),
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
                name="acct_user3_root_xor_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(observed_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                    & models.Q(persisted_at=models.F("recorded_at"))
                ),
                name="acct_user3_clock_ck",
            ),
        ]


class AccountRbacAuthoritySourceV3AnchorModel(_RawAuthorityAnchor):
    """Serialize one Account-profile RBAC raw-authority chain."""

    class Meta(_RawAuthorityAnchor.Meta):
        app_label = "account"
        db_table = "account_rbac_authority_source_v3_anchor"


class AccountRbacAuthoritySourceV3Model(_RawAuthorityLedger):
    """Store one complete Account RBAC authority Domain source payload."""

    anchor = models.ForeignKey(
        AccountRbacAuthoritySourceV3AnchorModel, on_delete=models.PROTECT, related_name="versions"
    )
    predecessor = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="successor"
    )
    user_id = models.PositiveBigIntegerField()
    actor_id = models.CharField(max_length=192)
    rbac_role = models.CharField(max_length=32)
    authority_state = models.CharField(max_length=16)
    rbac_seal = models.CharField(max_length=64)

    class Meta(_RawAuthorityLedger.Meta):
        app_label = "account"
        db_table = "account_rbac_authority_source_v3_ledger"
        indexes = [models.Index(fields=("source_id", "recorded_at"), name="acct_rbac3_chain_ix")]
        constraints = [
            models.UniqueConstraint(
                fields=("source_id", "source_version"), name="acct_rbac3_source_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="account_rbac_authority_source_v3",
                    schema="account.rbac_authority_source.v3",
                    permission="attestation_only",
                    status="inactive",
                    must_not_execute=True,
                    execution_allowed=False,
                    recorded_by_role="account_actor_authority_raw_recorder",
                    recorded_by_kind="service",
                    recorded_by_is_automated=True,
                ),
                name="acct_rbac3_fixed_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(authority_state__in=("current", "revoked")),
                name="acct_rbac3_state_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    rbac_role__in=(
                        "admin",
                        "owner",
                        "analyst",
                        "investment_manager",
                        "trader",
                        "risk",
                        "read_only",
                    )
                ),
                name="acct_rbac3_role_ck",
            ),
            models.CheckConstraint(condition=models.Q(user_id__gt=0), name="acct_rbac3_user_ck"),
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
                name="acct_rbac3_root_xor_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(observed_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                    & models.Q(persisted_at=models.F("recorded_at"))
                ),
                name="acct_rbac3_clock_ck",
            ),
        ]


def _reject_delete(
    sender: type[models.Model], instance: models.Model, using: str, origin: object, **kwargs: object
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("raw authority ledgers cannot be deleted")


_CONCRETE_MODELS = (
    AccountAuthenticationContextSourceV3AnchorModel,
    AccountAuthenticationContextSourceV3Model,
    AccountUserAuthoritySourceV3AnchorModel,
    AccountUserAuthoritySourceV3Model,
    AccountRbacAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3Model,
)
for _model in _CONCRETE_MODELS:
    pre_delete.connect(
        _reject_delete, sender=_model, dispatch_uid=f"reject_{_model.__name__}_delete", weak=False
    )


__all__ = [
    "AccountAuthenticationContextSourceV3AnchorModel",
    "AccountAuthenticationContextSourceV3Model",
    "AccountRbacAuthoritySourceV3AnchorModel",
    "AccountRbacAuthoritySourceV3Model",
    "AccountUserAuthoritySourceV3AnchorModel",
    "AccountUserAuthoritySourceV3Model",
]
