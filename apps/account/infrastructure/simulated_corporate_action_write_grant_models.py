"""Append-only ORM ledgers for simulated corporate-action write grants."""

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

from shared.infrastructure.django_append_only import AppendOnlyManager

_ModelT = TypeVar("_ModelT", bound=models.Model)
_GRANT_UOW: ContextVar[object | None] = ContextVar("simulated_action_grant_uow", default=None)


@dataclass(frozen=True)
class _InsertClaim:
    """Describe one exact grant-ledger insert authorized by a repository UOW."""

    token: object
    using: str
    model_type: type[models.Model]
    values: tuple[tuple[str, object], ...]


_GRANT_INSERT_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "simulated_action_grant_insert_claim", default=None
)


class SimulatedCorporateActionWriteGrantManager(AppendOnlyManager[_ModelT]):
    """Expose guarded querysets and deny manager-level bulk insertion."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Require repository-owned exact inserts instead of manager bulk operations."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("simulated corporate-action write grant requires exact appends")


@contextmanager
def _activate_simulated_corporate_action_write_grant_uow(token: object) -> Iterator[None]:
    """Activate one private append unit of work for this grant ledger."""

    reset = _GRANT_UOW.set(token)
    try:
        yield
    finally:
        _GRANT_UOW.reset(reset)


@contextmanager
def _claim_simulated_corporate_action_write_grant_insert(
    *, token: object, using: str, model_type: type[models.Model], values: Mapping[str, object]
) -> Iterator[None]:
    """Permit one insert only for the active repository, alias, type and field values."""

    if _GRANT_UOW.get() is not token:
        raise ValidationError("simulated corporate-action write grant insert requires private UOW")
    reset = _GRANT_INSERT_CLAIM.set(
        _InsertClaim(token, using, model_type, tuple(sorted(values.items())))
    )
    try:
        yield
    finally:
        _GRANT_INSERT_CLAIM.reset(reset)


class _SimulatedCorporateActionWriteGrantModel(models.Model):
    """Common immutable envelope and guarded insert behavior for both ledgers."""

    objects: SimulatedCorporateActionWriteGrantManager[Self] = (
        SimulatedCorporateActionWriteGrantManager()
    )

    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=96)
    schema = models.CharField(max_length=96)
    permission = models.CharField(max_length=64)
    service_actor_id = models.CharField(max_length=64)
    status = models.CharField(max_length=16)
    identity_hash = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64, unique=True)
    canonical_payload = models.JSONField()

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
        """Allow only an exact repository-claimed insert on the selected alias."""

        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("simulated corporate-action write grant ledger is append-only")
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
        """Guard Django's lower-level save path with the same exact insert claim."""

        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("simulated corporate-action write grant ledger is append-only")
        self._require_claim(using)
        super().save_base(force_insert=force_insert, using=using)

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Reject direct deletion of immutable grant evidence."""

        del using, keep_parents
        raise ValidationError("simulated corporate-action write grant ledger is append-only")

    def _require_claim(self, using: str | None) -> None:
        """Verify the active UOW, exact model, alias, and all claimed scalar fields."""

        claim = _GRANT_INSERT_CLAIM.get()
        if (
            claim is None
            or claim.token is not _GRANT_UOW.get()
            or claim.using != using
            or claim.model_type is not type(self)
            or any(getattr(self, name) != value for name, value in claim.values)
        ):
            raise ValidationError("simulated corporate-action write grant requires exact appends")


class SimulatedCorporateActionWriteGrantModel(_SimulatedCorporateActionWriteGrantModel):
    """One immutable grant version, with a unique predecessor link per chain."""

    grant_id = models.CharField(max_length=192)
    grant_version = models.CharField(max_length=192)
    account_namespace = models.CharField(max_length=32)
    account_id = models.CharField(max_length=192)
    owner_user_id = models.PositiveBigIntegerField()
    tenant_id = models.CharField(max_length=192)
    owner_id = models.CharField(max_length=192)
    account_source_id = models.CharField(max_length=192)
    account_source_version = models.CharField(max_length=192)
    account_source_content_hash = models.CharField(max_length=64)
    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    policy_content_hash = models.CharField(max_length=64)
    consent_evidence_id = models.CharField(max_length=192)
    consent_evidence_version = models.CharField(max_length=192)
    consent_evidence_hash = models.CharField(max_length=64)
    issuer_evidence_id = models.CharField(max_length=192)
    issuer_evidence_version = models.CharField(max_length=192)
    issuer_evidence_hash = models.CharField(max_length=64)
    consented_at = models.DateTimeField()
    issued_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    supersedes_content_hash = models.CharField(max_length=64, null=True, blank=True)
    predecessor = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="successor",
    )

    class Meta(_SimulatedCorporateActionWriteGrantModel.Meta):
        app_label = "account"
        db_table = "account_sim_corp_action_write_grant_ledger"
        indexes = [
            models.Index(
                fields=("grant_id", "recorded_at"),
                name="acct_scawg_grant_time_ix",
            ),
            models.Index(
                fields=("account_id", "recorded_at"),
                name="acct_scawg_account_time_ix",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("grant_id", "grant_version"),
                name="acct_scawg_version_uq",
            ),
            models.UniqueConstraint(
                fields=("grant_id",),
                condition=models.Q(predecessor__isnull=True),
                name="acct_scawg_root_uq",
            ),
            models.UniqueConstraint(
                fields=("supersedes_content_hash",),
                name="acct_scawg_predecessor_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="simulated_corporate_action_write_grant",
                    schema="account.simulated_corporate_action_write_grant.v1",
                    permission="simulated_corporate_action_stage_write",
                    service_actor_id="simulated-trading",
                    status="active",
                    account_namespace="simulated",
                ),
                name="acct_scawg_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(consented_at__lte=models.F("issued_at"))
                    & models.Q(issued_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="acct_scawg_clock_ck",
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
                name="acct_scawg_chain_ck",
            ),
        ]


class SimulatedCorporateActionWriteGrantRevocationModel(_SimulatedCorporateActionWriteGrantModel):
    """One immutable revocation row for one exact grant version."""

    revocation_id = models.CharField(max_length=192)
    revocation_version = models.CharField(max_length=192)
    target_grant = models.OneToOneField(
        SimulatedCorporateActionWriteGrantModel,
        on_delete=models.PROTECT,
        related_name="simulated_corporate_action_write_grant_revocation",
    )
    grant_id = models.CharField(max_length=192)
    grant_version = models.CharField(max_length=192)
    grant_identity_hash = models.CharField(max_length=64)
    grant_content_hash = models.CharField(max_length=64, unique=True)
    revocation_evidence_id = models.CharField(max_length=192)
    revocation_evidence_version = models.CharField(max_length=192)
    revocation_evidence_hash = models.CharField(max_length=64)
    issuer_evidence_id = models.CharField(max_length=192)
    issuer_evidence_version = models.CharField(max_length=192)
    issuer_evidence_hash = models.CharField(max_length=64)
    revoked_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)

    class Meta(_SimulatedCorporateActionWriteGrantModel.Meta):
        app_label = "account"
        db_table = "account_sim_corp_action_write_grant_revocation_ledger"
        indexes = [
            models.Index(
                fields=("grant_content_hash", "recorded_at"),
                name="acct_scawgr_grant_time_ix",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("revocation_id", "revocation_version"),
                name="acct_scawgr_version_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="simulated_corporate_action_write_grant_revocation",
                    schema="account.simulated_corporate_action_write_grant.revocation.v1",
                    permission="simulated_corporate_action_stage_write",
                    service_actor_id="simulated-trading",
                    status="revoked",
                ),
                name="acct_scawgr_fixed_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(revoked_at__lte=models.F("recorded_at")),
                name="acct_scawgr_clock_ck",
            ),
        ]


def _reject_simulated_corporate_action_write_grant_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> NoReturn:
    """Reject signal-driven deletion, including cascades from unrelated code."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("simulated corporate-action write grant ledger is append-only")


for _model in (
    SimulatedCorporateActionWriteGrantModel,
    SimulatedCorporateActionWriteGrantRevocationModel,
):
    pre_delete.connect(
        _reject_simulated_corporate_action_write_grant_delete,
        sender=_model,
        dispatch_uid=f"{_model.__name__}_append_only",
        weak=False,
    )


__all__ = [
    "SimulatedCorporateActionWriteGrantModel",
    "SimulatedCorporateActionWriteGrantRevocationModel",
]
