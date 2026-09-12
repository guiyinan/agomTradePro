"""Append-only PostgreSQL rows for the owner/tenant authority v2 ledgers.

The two ledgers are intentionally separate.  A root decision is immutable and
keeps durable foreign keys to its complete Evidence v4, policy, and approval
source parents.  A revocation is a second immutable event linked to exactly
one root.  Repositories must claim every insert inside their private,
same-alias unit of work; direct ORM mutation remains unavailable.
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
_OWNER_V2_UOW: ContextVar[object | None] = ContextVar("owner_tenant_authority_v2_uow", default=None)


@dataclass(frozen=True)
class _InsertClaim:
    """Describe one exact model insert authorized by a repository."""

    token: object
    using: str
    model_type: type[models.Model]
    values: tuple[tuple[str, object], ...]


_OWNER_V2_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "owner_tenant_authority_v2_insert_claim", default=None
)


@contextmanager
def _activate_owner_tenant_authority_v2_uow(token: object) -> Iterator[None]:
    """Activate one private owner-authority unit of work for guarded inserts."""

    reset = _OWNER_V2_UOW.set(token)
    try:
        yield
    finally:
        _OWNER_V2_UOW.reset(reset)


@contextmanager
def _claim_owner_tenant_authority_v2_insert(
    *, token: object, using: str, model_type: type[models.Model], values: Mapping[str, object]
) -> Iterator[None]:
    """Permit one exact insert while the repository UOW and database alias match."""

    if _OWNER_V2_UOW.get() is not token:
        raise ValidationError("owner tenant authority v2 insert requires private UOW")
    reset = _OWNER_V2_CLAIM.set(
        _InsertClaim(token, using, model_type, tuple(sorted(values.items())))
    )
    try:
        yield
    finally:
        _OWNER_V2_CLAIM.reset(reset)


class OwnerTenantAuthorityV2QuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject bulk and queryset mutations that bypass the repository."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject bulk inserts without an exact per-row repository claim."""

        raise ValidationError("owner tenant authority v2 requires exact appends")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        """Reject updates to immutable owner-authority rows."""

        raise ValidationError("owner tenant authority v2 is append-only")

    def _raw_delete(self, using: str | None) -> NoReturn:
        """Reject queryset deletion of immutable owner-authority rows."""

        raise ValidationError("owner tenant authority v2 is append-only")


class OwnerTenantAuthorityV2Manager(AppendOnlyManager[_ModelT]):
    """Expose guarded owner-authority querysets on their selected alias."""

    def get_queryset(self) -> OwnerTenantAuthorityV2QuerySet[_ModelT]:
        """Return the append-only queryset bound to this manager alias."""

        return OwnerTenantAuthorityV2QuerySet(self.model, using=self._db)

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

        raise ValidationError("owner tenant authority v2 requires exact appends")


class _OwnerTenantAuthorityV2Model(models.Model):
    """Shared immutable fields and save/delete guards for both ledgers."""

    objects: OwnerTenantAuthorityV2Manager[Self] = OwnerTenantAuthorityV2Manager()

    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=96)
    schema = models.CharField(max_length=96)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    canonical_payload = models.JSONField()
    record_seal = models.CharField(max_length=64, unique=True)
    ledger_seal = models.CharField(max_length=64, unique=True)

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Allow only a repository-claimed insert on the selected alias."""

        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("owner tenant authority v2 is append-only")
        self._require_claim(using)
        super().save(force_insert=force_insert, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Guard Django's lower-level save path with the same insert claim."""

        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("owner tenant authority v2 is append-only")
        self._require_claim(using)
        super().save_base(force_insert=force_insert, using=using)

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Reject deletion of immutable owner-authority evidence."""

        raise ValidationError("owner tenant authority v2 is append-only")

    def _require_claim(self, using: str | None) -> None:
        """Verify the exact model, alias, and scalar values claimed for insertion."""

        claim = _OWNER_V2_CLAIM.get()
        if (
            claim is None
            or claim.token is not _OWNER_V2_UOW.get()
            or claim.using != using
            or claim.model_type is not type(self)
            or any(getattr(self, name) != value for name, value in claim.values)
        ):
            raise ValidationError("owner tenant authority v2 requires an exact insert claim")


class OwnerTenantAuthorityV2Model(_OwnerTenantAuthorityV2Model):
    """Immutable active root decision over one complete assignment graph."""

    authority_id = models.CharField(max_length=192)
    authority_version = models.CharField(max_length=192)
    assignment = models.OneToOneField(
        "account.AccountOwnerAssignmentEvidenceV4Model",
        on_delete=models.PROTECT,
        related_name="owner_tenant_authority_v2_root",
    )
    assignment_evidence_id = models.CharField(max_length=192)
    assignment_evidence_version = models.CharField(max_length=192)
    assignment_evidence_content_hash = models.CharField(max_length=64, unique=True)
    policy = models.ForeignKey(
        "account.SingleOwnerAuthorityPolicyV1Model",
        on_delete=models.PROTECT,
        related_name="owner_tenant_authority_v2_roots",
    )
    policy_identifier = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    policy_content_hash = models.CharField(max_length=64)
    tenant_id = models.CharField(max_length=192)
    owner_id = models.CharField(max_length=192)
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    actor_id = models.CharField(max_length=192)
    actor_user_id = models.PositiveBigIntegerField()
    actor_source = models.ForeignKey(
        "account.AccountOwnerAssignmentActorAuthoritySourceV3Model",
        on_delete=models.PROTECT,
        related_name="owner_tenant_authority_v2_approvals",
    )
    approved_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    persisted_at = models.DateTimeField()

    class Meta(_OwnerTenantAuthorityV2Model.Meta):
        app_label = "account"
        db_table = "account_owner_tenant_authority_v2_ledger"
        indexes = [
            models.Index(
                fields=("authority_id", "recorded_at"),
                name="acct_otav2_authority_time_ix",
            ),
            models.Index(
                fields=("assignment_evidence_content_hash", "recorded_at"),
                name="acct_otav2_assignment_time_ix",
            ),
        ]
        constraints = [
            models.UniqueConstraint(fields=("authority_id",), name="acct_otav2_authority_id_uq"),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="owner_tenant_authority_v2",
                    schema="account.owner_tenant_authority.v2",
                    permission="evidence_read",
                    status="active",
                ),
                name="acct_otav2_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(approved_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                    & models.Q(persisted_at=models.F("recorded_at"))
                ),
                name="acct_otav2_clock_ck",
            ),
        ]


class OwnerTenantAuthorityV2RevocationModel(_OwnerTenantAuthorityV2Model):
    """Immutable explicit revocation event linked to one authority root."""

    authority = models.OneToOneField(
        OwnerTenantAuthorityV2Model,
        on_delete=models.PROTECT,
        related_name="owner_tenant_authority_v2_revocation",
    )
    actor_source = models.ForeignKey(
        "account.AccountOwnerAssignmentActorAuthoritySourceV3Model",
        on_delete=models.PROTECT,
        related_name="owner_tenant_authority_v2_revocations",
    )
    authority_content_hash = models.CharField(max_length=64, unique=True)
    policy_content_hash = models.CharField(max_length=64)
    revoked_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    persisted_at = models.DateTimeField()
    reason = models.CharField(max_length=192)

    class Meta(_OwnerTenantAuthorityV2Model.Meta):
        app_label = "account"
        db_table = "account_owner_tenant_authority_v2_revocation_ledger"
        indexes = [
            models.Index(
                fields=("authority_content_hash", "recorded_at"),
                name="acct_otav2_revoke_time_ix",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="owner_tenant_authority_v2_revocation",
                    schema="account.owner_tenant_authority.v2.revocation",
                    permission="evidence_read",
                    status="revoked",
                ),
                name="acct_otav2_revoke_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(revoked_at__lte=models.F("recorded_at"))
                    & models.Q(persisted_at=models.F("recorded_at"))
                ),
                name="acct_otav2_revoke_clock_ck",
            ),
        ]


def _reject_owner_tenant_authority_v2_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> NoReturn:
    """Reject signal-driven deletion, including cascades from unrelated code."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("owner tenant authority v2 is append-only")


for _model in (OwnerTenantAuthorityV2Model, OwnerTenantAuthorityV2RevocationModel):
    pre_delete.connect(
        _reject_owner_tenant_authority_v2_delete,
        sender=_model,
        dispatch_uid=f"{_model.__name__}_append_only",
        weak=False,
    )


__all__ = ["OwnerTenantAuthorityV2Model", "OwnerTenantAuthorityV2RevocationModel"]
