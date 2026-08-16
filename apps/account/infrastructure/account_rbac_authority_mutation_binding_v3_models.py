"""Append-only schema for RBAC mutation bindings and exact Profile projections.

This module is deliberately a persistence contract only.  It does not read the
mutable Django ``User``/``AccountProfile`` rows and it does not expose a writer
or a production authorization entry point.  A future owner UOW must supply the
exact Profile version and raw RBAC source references represented here.
"""

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
_ACTIVE_RBAC_MUTATION_V3_UOW: ContextVar[object | None] = ContextVar(
    "active_account_rbac_mutation_binding_v3_uow", default=None
)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_RBAC_MUTATION_V3_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_account_rbac_mutation_binding_v3_claim", default=None
)


@contextmanager
def _activate_account_rbac_authority_mutation_binding_v3_uow(token: object) -> Iterator[None]:
    """Activate the private, non-nestable mutation-binding UOW."""

    if _ACTIVE_RBAC_MUTATION_V3_UOW.get() is not None:
        raise ValidationError("RBAC mutation binding UOW cannot be nested")
    reset = _ACTIVE_RBAC_MUTATION_V3_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_RBAC_MUTATION_V3_UOW.reset(reset)


@contextmanager
def _claim_account_rbac_authority_mutation_binding_v3_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact anchor/version/binding insert inside the private UOW."""

    if _ACTIVE_RBAC_MUTATION_V3_UOW.get() is not token:
        raise ValidationError("RBAC mutation binding insert requires its private UOW")
    if _ACTIVE_RBAC_MUTATION_V3_CLAIM.get() is not None:
        raise ValidationError("RBAC mutation binding insert claims cannot be nested")
    reset = _ACTIVE_RBAC_MUTATION_V3_CLAIM.set(
        _InsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_RBAC_MUTATION_V3_CLAIM.reset(reset)


class _RbacMutationQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject every bulk/raw mutation route for the four ledgers."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("RBAC mutation ledgers require exact private inserts")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        del values
        raise ValidationError("RBAC mutation ledgers cannot be updated")

    def _raw_delete(self, using: str | None) -> NoReturn:
        del using
        raise ValidationError("RBAC mutation ledgers cannot be deleted")


class _RbacMutationManager(AppendOnlyManager[_ModelT]):
    """Expose a guarded queryset and reject manager bulk inserts."""

    def get_queryset(self) -> _RbacMutationQuerySet[_ModelT]:
        return _RbacMutationQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("RBAC mutation ledgers require exact private inserts")


class _GuardedRbacMutationModel(models.Model):
    objects = _RbacMutationManager()

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def _require_claim(self) -> None:
        claim = _ACTIVE_RBAC_MUTATION_V3_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_RBAC_MUTATION_V3_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("RBAC mutation insert requires an exact private claim")

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("RBAC mutation ledgers are append-only")
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
            raise ValidationError("RBAC mutation ledgers are append-only")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        del using, keep_parents
        raise ValidationError("RBAC mutation ledgers cannot be deleted")


class AccountRbacAuthorityMutationEpochV3AnchorModel(_GuardedRbacMutationModel):
    """Candidate-independent owner-issued RBAC source epoch anchor."""

    epoch_id = models.CharField(max_length=192, unique=True)
    target_user_id = models.PositiveBigIntegerField()
    subject_actor_id = models.CharField(max_length=192)
    source_id = models.CharField(max_length=192, unique=True)
    epoch_sequence = models.PositiveBigIntegerField()
    opened_at = models.DateTimeField()
    previous_epoch = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="next_epoch"
    )
    previous_epoch_content_hash = models.CharField(max_length=64, null=True, blank=True)
    terminal_authority_source_content_hash = models.CharField(max_length=64, null=True, blank=True)
    terminal_mutation_binding_content_hash = models.CharField(max_length=64, null=True, blank=True)
    root_claim_hash = models.CharField(max_length=64, unique=True)
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    canonical_payload = models.JSONField()
    persisted_at = models.DateTimeField()

    class Meta(_GuardedRbacMutationModel.Meta):
        app_label = "account"
        db_table = "account_rbac_mutation_epoch_v3_anchor"
        constraints = [
            models.UniqueConstraint(
                fields=("target_user_id", "epoch_sequence"), name="acct_rbac_mut_epoch_user_seq_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(target_user_id__gt=0), name="acct_rbac_mut_epoch_user_ck"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        epoch_sequence=1,
                        previous_epoch__isnull=True,
                        previous_epoch_content_hash__isnull=True,
                        terminal_authority_source_content_hash__isnull=True,
                        terminal_mutation_binding_content_hash__isnull=True,
                    )
                    | models.Q(
                        epoch_sequence__gt=1,
                        previous_epoch__isnull=False,
                        previous_epoch_content_hash__isnull=False,
                        terminal_authority_source_content_hash__isnull=False,
                        terminal_mutation_binding_content_hash__isnull=False,
                    )
                ),
                name="acct_rbac_mut_epoch_root_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(persisted_at=models.F("opened_at")),
                name="acct_rbac_mut_epoch_clock_ck",
            ),
        ]


class AccountRbacAuthorityProfileV3AnchorModel(_GuardedRbacMutationModel):
    """Candidate-independent lock for a future exact Profile authority chain."""

    profile_id = models.CharField(max_length=192, unique=True)
    user_id = models.PositiveBigIntegerField()
    subject_actor_id = models.CharField(max_length=192)
    root_claim_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField()

    class Meta(_GuardedRbacMutationModel.Meta):
        app_label = "account"
        db_table = "account_rbac_profile_v3_anchor"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(user_id__gt=0), name="acct_rbac_prof_anchor_user_ck"
            )
        ]


class AccountRbacAuthorityProfileV3VersionModel(_GuardedRbacMutationModel):
    """Append-only exact Profile projection used by old/new mutation refs."""

    anchor = models.ForeignKey(
        AccountRbacAuthorityProfileV3AnchorModel,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    predecessor = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="successor"
    )
    profile_id = models.CharField(max_length=192)
    profile_version = models.CharField(max_length=192)
    profile_content_hash = models.CharField(max_length=64)
    user_id = models.PositiveBigIntegerField()
    subject_actor_id = models.CharField(max_length=192)
    rbac_role = models.CharField(max_length=32)
    observed_at = models.DateTimeField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    root_claim_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    supersedes_content_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    record_seal = models.CharField(max_length=64, unique=True)
    canonical_payload = models.JSONField()
    persisted_at = models.DateTimeField()

    class Meta(_GuardedRbacMutationModel.Meta):
        app_label = "account"
        db_table = "account_rbac_profile_v3_version"
        indexes = [
            models.Index(fields=("profile_id", "observed_at"), name="acct_rbac_prof_chain_ix")
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("profile_id", "profile_version"), name="acct_rbac_prof_version_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(user_id__gt=0), name="acct_rbac_prof_user_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(persisted_at=models.F("observed_at")),
                name="acct_rbac_prof_clock_ck",
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
                name="acct_rbac_prof_root_xor_ck",
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
                name="acct_rbac_prof_role_ck",
            ),
        ]


class AccountRbacAuthorityMutationBindingV3Model(_GuardedRbacMutationModel):
    """Complete immutable mutation binding with scalar projections and seals."""

    epoch = models.ForeignKey(
        AccountRbacAuthorityMutationEpochV3AnchorModel,
        on_delete=models.PROTECT,
        related_name="bindings",
    )
    authority_source = models.OneToOneField(
        "account.AccountRbacAuthoritySourceV3Model",
        on_delete=models.PROTECT,
        related_name="mutation_binding_v3",
    )
    predecessor = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="successor"
    )
    mutation_id = models.CharField(max_length=192, unique=True)
    mutation_kind = models.CharField(max_length=32)
    source_id = models.CharField(max_length=192)
    source_version = models.CharField(max_length=192)
    old_authority_state = models.CharField(max_length=16, null=True, blank=True)
    new_authority_state = models.CharField(max_length=16)
    old_rbac_role = models.CharField(max_length=32, null=True, blank=True)
    new_rbac_role = models.CharField(max_length=32)
    old_profile_id = models.CharField(max_length=192, null=True, blank=True)
    old_profile_version = models.CharField(max_length=192, null=True, blank=True)
    old_profile_content_hash = models.CharField(max_length=64, null=True, blank=True)
    old_profile_identity_hash = models.CharField(max_length=64, null=True, blank=True)
    old_profile_observed_at = models.DateTimeField(null=True, blank=True)
    old_subject_actor_id = models.CharField(max_length=192, null=True, blank=True)
    old_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    old_subject_seal = models.CharField(max_length=64, null=True, blank=True)
    profile_id = models.CharField(max_length=192)
    profile_version = models.CharField(max_length=192)
    profile_content_hash = models.CharField(max_length=64)
    profile_identity_hash = models.CharField(max_length=64)
    profile_observed_at = models.DateTimeField()
    subject_actor_id = models.CharField(max_length=192)
    user_id = models.PositiveBigIntegerField()
    subject_seal = models.CharField(max_length=64)
    operator_principal_id = models.CharField(max_length=192)
    operator_user_id = models.PositiveBigIntegerField()
    operator_actor_id = models.CharField(max_length=192)
    operator_is_authenticated = models.BooleanField()
    operator_is_active = models.BooleanField()
    operator_is_staff = models.BooleanField()
    operator_is_superuser = models.BooleanField()
    operator_rbac_role = models.CharField(max_length=32)
    operator_authentication_source_id = models.CharField(max_length=192)
    operator_authentication_source_version = models.CharField(max_length=192)
    operator_authentication_source_content_hash = models.CharField(max_length=64)
    operator_user_source_id = models.CharField(max_length=192)
    operator_user_source_version = models.CharField(max_length=192)
    operator_user_source_content_hash = models.CharField(max_length=64)
    operator_rbac_source_id = models.CharField(max_length=192)
    operator_rbac_source_version = models.CharField(max_length=192)
    operator_rbac_source_content_hash = models.CharField(max_length=64)
    operator_observed_at = models.DateTimeField()
    operator_valid_until = models.DateTimeField()
    operator_identity_hash = models.CharField(max_length=64)
    operator_authority_hash = models.CharField(max_length=64)
    issuer_service_id = models.CharField(max_length=192)
    issuer_role = models.CharField(max_length=192)
    issuer_kind = models.CharField(max_length=16)
    issuer_is_automated = models.BooleanField()
    issuer_identity_hash = models.CharField(max_length=64)
    authority_source_identity_hash = models.CharField(max_length=64)
    authority_source_content_hash = models.CharField(max_length=64)
    authority_source_record_seal = models.CharField(max_length=64)
    observed_at = models.DateTimeField()
    issued_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    binding_root_claim_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    binding_supersedes_content_hash = models.CharField(
        max_length=64, null=True, blank=True, unique=True
    )
    source_root_claim_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    source_supersedes_content_hash = models.CharField(
        max_length=64, null=True, blank=True, unique=True
    )
    identity_hash = models.CharField(max_length=64, unique=True)
    transition_seal = models.CharField(max_length=64)
    operator_seal = models.CharField(max_length=64)
    issuer_seal = models.CharField(max_length=64)
    source_binding_seal = models.CharField(max_length=64)
    clock_seal = models.CharField(max_length=64)
    binding_chain_seal = models.CharField(max_length=64)
    authority_source_chain_seal = models.CharField(max_length=64)
    fixed_authority_seal = models.CharField(max_length=64)
    record_seal = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_seal = models.CharField(max_length=64, unique=True)
    canonical_payload = models.JSONField()
    persisted_at = models.DateTimeField()
    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=96)
    schema = models.CharField(max_length=96)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    must_not_execute = models.BooleanField()
    execution_allowed = models.BooleanField()

    class Meta(_GuardedRbacMutationModel.Meta):
        app_label = "account"
        db_table = "account_rbac_mutation_binding_v3_ledger"
        indexes = [models.Index(fields=("source_id", "recorded_at"), name="acct_rbac_mut_chain_ix")]
        constraints = [
            models.UniqueConstraint(
                fields=("source_id", "source_version"), name="acct_rbac_mut_source_version_uq"
            ),
            models.CheckConstraint(condition=models.Q(user_id__gt=0), name="acct_rbac_mut_user_ck"),
            models.CheckConstraint(
                condition=models.Q(operator_user_id__gt=0), name="acct_rbac_mut_operator_user_ck"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        owner="account",
                        artifact_type="account_rbac_authority_mutation_binding_v3",
                        schema="account.rbac_authority_mutation_binding.v3",
                        permission="attestation_only",
                        status="inactive",
                        must_not_execute=True,
                        execution_allowed=False,
                    )
                ),
                name="acct_rbac_mut_fixed_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    mutation_kind__in=("bootstrap", "role_change", "revoke", "reactivate")
                ),
                name="acct_rbac_mut_kind_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(new_authority_state__in=("current", "revoked")),
                name="acct_rbac_mut_new_state_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    new_rbac_role__in=(
                        "admin",
                        "owner",
                        "analyst",
                        "investment_manager",
                        "trader",
                        "risk",
                        "read_only",
                    )
                ),
                name="acct_rbac_mut_new_role_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(old_authority_state__isnull=True)
                | models.Q(old_authority_state__in=("current", "revoked")),
                name="acct_rbac_mut_old_state_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    issuer_role="account_rbac_authority_mutation_issuer",
                    issuer_kind="service",
                    issuer_is_automated=True,
                ),
                name="acct_rbac_mut_issuer_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    operator_is_authenticated=True,
                    operator_is_active=True,
                    operator_is_staff=True,
                    operator_rbac_role="admin",
                ),
                name="acct_rbac_mut_operator_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        mutation_kind="bootstrap",
                        old_authority_state__isnull=True,
                        old_rbac_role__isnull=True,
                        old_profile_id__isnull=True,
                        binding_root_claim_hash__isnull=False,
                        binding_supersedes_content_hash__isnull=True,
                        predecessor__isnull=True,
                    )
                    | models.Q(
                        mutation_kind__in=("role_change", "revoke"),
                        old_authority_state="current",
                        old_rbac_role__isnull=False,
                        old_profile_id__isnull=False,
                        binding_root_claim_hash__isnull=True,
                        binding_supersedes_content_hash__isnull=False,
                        predecessor__isnull=False,
                    )
                    | models.Q(
                        mutation_kind="reactivate",
                        old_authority_state="revoked",
                        old_rbac_role__isnull=False,
                        old_profile_id__isnull=False,
                        binding_root_claim_hash__isnull=False,
                        binding_supersedes_content_hash__isnull=True,
                        predecessor__isnull=True,
                    )
                ),
                name="acct_rbac_mut_transition_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        source_root_claim_hash__isnull=False,
                        source_supersedes_content_hash__isnull=True,
                    )
                    | models.Q(
                        source_root_claim_hash__isnull=True,
                        source_supersedes_content_hash__isnull=False,
                    )
                ),
                name="acct_rbac_mut_source_chain_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(observed_at__lte=models.F("issued_at"))
                    & models.Q(issued_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                    & models.Q(persisted_at=models.F("recorded_at"))
                    & models.Q(operator_observed_at__lte=models.F("observed_at"))
                    & models.Q(profile_observed_at__lte=models.F("observed_at"))
                ),
                name="acct_rbac_mut_clock_ck",
            ),
        ]


def _reject_delete(
    sender: type[models.Model], instance: models.Model, using: str, origin: object, **kwargs: object
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("RBAC mutation ledgers cannot be deleted")


_CONCRETE_MODELS = (
    AccountRbacAuthorityMutationEpochV3AnchorModel,
    AccountRbacAuthorityProfileV3AnchorModel,
    AccountRbacAuthorityProfileV3VersionModel,
    AccountRbacAuthorityMutationBindingV3Model,
)
for _model in _CONCRETE_MODELS:
    pre_delete.connect(
        _reject_delete, sender=_model, dispatch_uid=f"reject_{_model.__name__}_delete", weak=False
    )


__all__ = [
    "AccountRbacAuthorityMutationBindingV3Model",
    "AccountRbacAuthorityMutationEpochV3AnchorModel",
    "AccountRbacAuthorityProfileV3AnchorModel",
    "AccountRbacAuthorityProfileV3VersionModel",
]
