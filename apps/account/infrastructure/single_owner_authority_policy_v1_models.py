"""Append-only Django ledger rows for single-owner policy snapshots.

The model is deliberately an immutable storage boundary.  Repository code must
claim an exact row inside its private unit of work before an insert can reach
the ORM.  Reads remain available through the normal manager, while direct ORM
mutation paths are rejected so the repository is the only writer of the
policy chain.
"""

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
_POLICY_UOW: ContextVar[object | None] = ContextVar(
    "single_owner_authority_policy_v1_uow", default=None
)


@dataclass(frozen=True)
class _InsertClaim:
    """Exact values a repository is authorized to insert once."""

    token: object
    model_type: type[models.Model]
    values: tuple[tuple[str, object], ...]


_POLICY_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "single_owner_authority_policy_v1_claim", default=None
)


@contextmanager
def _activate_single_owner_authority_policy_v1_uow(token: object) -> Iterator[None]:
    """Mark one repository transaction as the private policy insert UOW."""

    reset = _POLICY_UOW.set(token)
    try:
        yield
    finally:
        _POLICY_UOW.reset(reset)


@contextmanager
def _claim_single_owner_authority_policy_v1_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Permit exactly one matching model insert while the private UOW is active."""

    if _POLICY_UOW.get() is not token:
        raise ValidationError("single-owner policy insert requires private UOW")
    reset = _POLICY_CLAIM.set(
        _InsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _POLICY_CLAIM.reset(reset)


class SingleOwnerAuthorityPolicyV1QuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject bulk and private mutation paths for policy rows."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject inserts that bypass the repository's exact append claim."""

        raise ValidationError("single-owner policy requires exact appends")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("single-owner policy is append-only")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("single-owner policy is append-only")


class SingleOwnerAuthorityPolicyV1Manager(AppendOnlyManager[_ModelT]):
    """Expose policy rows through an append-only query interface."""

    def get_queryset(self) -> SingleOwnerAuthorityPolicyV1QuerySet[_ModelT]:
        """Return the guarded policy queryset for this manager alias."""

        return SingleOwnerAuthorityPolicyV1QuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject manager-level bulk inserts outside the append contract."""

        raise ValidationError("single-owner policy requires exact appends")


class SingleOwnerAuthorityPolicyV1Model(models.Model):
    """One immutable policy root or one immutable policy successor row."""

    objects: SingleOwnerAuthorityPolicyV1Manager[Self] = SingleOwnerAuthorityPolicyV1Manager()

    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    tenant_id = models.CharField(max_length=192)
    owner_id = models.CharField(max_length=192)
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    owner_user_id = models.PositiveBigIntegerField()
    authorization_content_hash = models.CharField(max_length=64)
    observed_at = models.DateTimeField(db_index=True)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=16)
    schema = models.CharField(max_length=64)
    artifact_type = models.CharField(max_length=64)
    mode = models.CharField(max_length=32)
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    canonical_payload = models.JSONField()
    expected_previous_content_hash = models.CharField(max_length=64, null=True, blank=True)
    predecessor = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="successor",
    )
    record_seal = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta:
        app_label = "account"
        db_table = "account_single_owner_authority_policy_v1"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("policy_id", "observed_at"),
                name="acct_sop_v1_policy_time_ix",
            ),
            models.Index(
                fields=("policy_id", "policy_version"),
                name="acct_sop_v1_policy_ver_ix",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("policy_id", "policy_version"),
                name="acct_sop_v1_policy_ver_uq",
            ),
            models.UniqueConstraint(
                fields=("policy_id",),
                condition=models.Q(predecessor__isnull=True),
                name="acct_sop_v1_policy_root_uq",
            ),
            models.UniqueConstraint(
                fields=("expected_previous_content_hash",),
                name="acct_sop_v1_policy_pred_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("active", "revoked")),
                name="acct_sop_v1_status_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(schema="account.single_owner_authority_policy.v1")
                    & models.Q(artifact_type="single_owner_authority_policy_v1")
                    & models.Q(mode="single_owner")
                ),
                name="acct_sop_v1_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(valid_from__lte=models.F("observed_at"))
                    & models.Q(observed_at__lt=models.F("valid_until"))
                    & models.Q(persisted_at__gte=models.F("observed_at"))
                ),
                name="acct_sop_v1_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(expected_previous_content_hash__isnull=True)
                        & models.Q(predecessor__isnull=True)
                    )
                    | (
                        models.Q(expected_previous_content_hash__isnull=False)
                        & models.Q(predecessor__isnull=False)
                    )
                ),
                name="acct_sop_v1_chain_ck",
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
        """Allow only an exact repository-authorized insert."""

        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("single-owner policy is append-only")
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
        """Guard Django's lower-level save path as well as normal save."""

        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("single-owner policy is append-only")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject deletion of an immutable policy row."""

        raise ValidationError("single-owner policy is append-only")

    def _require_claim(self) -> None:
        claim = _POLICY_CLAIM.get()
        if (
            claim is None
            or claim.token is not _POLICY_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != value for name, value in claim.values)
        ):
            raise ValidationError("single-owner policy requires exact insert claim")


def _reject_single_owner_policy_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> NoReturn:
    """Reject signal-driven deletes, including cascades from unrelated code."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("single-owner policy is append-only")


pre_delete.connect(
    _reject_single_owner_policy_delete,
    sender=SingleOwnerAuthorityPolicyV1Model,
    dispatch_uid="SingleOwnerAuthorityPolicyV1Model_append_only",
)


__all__ = ["SingleOwnerAuthorityPolicyV1Model"]
