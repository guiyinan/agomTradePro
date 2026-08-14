"""Append-only model for Account claimant provenance receipts v2."""

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

_T = TypeVar("_T", bound=models.Model)
_UOW: ContextVar[object | None] = ContextVar("account_provenance_v2_uow", default=None)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    values: tuple[tuple[str, object], ...]


_CLAIM: ContextVar[_InsertClaim | None] = ContextVar("account_provenance_v2_claim", default=None)


@contextmanager
def _activate_account_owner_assignment_provenance_receipt_v2_uow(token: object) -> Iterator[None]:
    reset = _UOW.set(token)
    try:
        yield
    finally:
        _UOW.reset(reset)


@contextmanager
def _claim_account_owner_assignment_provenance_receipt_v2_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    if _UOW.get() is not token:
        raise ValidationError("provenance v2 insert requires private UOW")
    reset = _CLAIM.set(_InsertClaim(token, model_type, tuple(sorted(expected_values.items()))))
    try:
        yield
    finally:
        _CLAIM.reset(reset)


class AccountOwnerAssignmentProvenanceReceiptV2QuerySet(AppendOnlyQuerySet[_T]):
    def bulk_create(
        self,
        objs: Iterable[_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("provenance v2 requires exact appends")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("provenance v2 is append-only")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("provenance v2 is append-only")


class AccountOwnerAssignmentProvenanceReceiptV2Manager(AppendOnlyManager[_T]):
    def get_queryset(self) -> AccountOwnerAssignmentProvenanceReceiptV2QuerySet[_T]:
        return AccountOwnerAssignmentProvenanceReceiptV2QuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("provenance v2 requires exact appends")


class AccountOwnerAssignmentProvenanceReceiptV2Model(models.Model):
    """One immutable actor-bound receipt."""

    objects = AccountOwnerAssignmentProvenanceReceiptV2Manager()
    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    receipt_id = models.CharField(max_length=192)
    receipt_version = models.CharField(max_length=192)
    provenance_kind = models.CharField(max_length=32)
    assignment_state = models.CharField(max_length=32)
    assigned_owner_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    underlying_unified_account_namespace = models.CharField(max_length=192)
    underlying_unified_account_id = models.PositiveBigIntegerField()
    row_observation_owner = models.CharField(max_length=32)
    row_observation_artifact_type = models.CharField(max_length=64)
    row_observation_schema = models.CharField(max_length=64)
    row_observation_id = models.CharField(max_length=192)
    row_observation_version = models.CharField(max_length=192)
    row_observation_identity_hash = models.CharField(max_length=64)
    row_observation_content_hash = models.CharField(max_length=64)
    row_observation_supersedes_content_hash = models.CharField(max_length=64, null=True, blank=True)
    row_observation_recorded_at = models.DateTimeField()
    row_observation_valid_until = models.DateTimeField()
    source_content_hash = models.CharField(max_length=64)
    raw_observation_content_hash = models.CharField(max_length=64)
    row_is_active = models.BooleanField()
    row_is_present = models.BooleanField()
    row_is_tombstone = models.BooleanField()
    row_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    claimant_actor_id = models.CharField(max_length=192)
    claimant_user_id = models.PositiveBigIntegerField()
    claimant_role = models.CharField(max_length=192)
    claimant_kind = models.CharField(max_length=16)
    claimant_is_staff = models.BooleanField()
    issued_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    supersedes_content_hash = models.CharField(max_length=64, null=True, blank=True)
    root_claim_hash = models.CharField(max_length=64, null=True, blank=True)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    blocker_codes = models.JSONField()
    issuer_actor_id = models.CharField(max_length=192)
    issuer_user_id = models.PositiveBigIntegerField()
    issuer_role = models.CharField(max_length=192)
    issuer_kind = models.CharField(max_length=16)
    issuer_is_staff = models.BooleanField()
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    row_binding_seal = models.CharField(max_length=64)
    actor_binding_seal = models.CharField(max_length=64)
    fixed_authority_seal = models.CharField(max_length=64)
    header_seal = models.CharField(max_length=64)
    record_seal = models.CharField(max_length=64, unique=True)
    ledger_seal = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta:
        app_label = "account"
        db_table = "account_owner_assignment_provenance_receipt_v2_ledger"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [models.Index(fields=("receipt_id", "recorded_at"), name="acct_prov_v2_chain_ix")]
        constraints = [
            models.UniqueConstraint(
                fields=("receipt_id", "receipt_version"), name="acct_prov_v2_id_uq"
            ),
            models.UniqueConstraint(
                fields=("root_claim_hash",),
                condition=models.Q(root_claim_hash__isnull=False),
                name="acct_prov_v2_root_uq",
            ),
            models.UniqueConstraint(
                fields=("supersedes_content_hash",),
                condition=models.Q(supersedes_content_hash__isnull=False),
                name="acct_prov_v2_next_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="account_owner_assignment_provenance_receipt_v2",
                    schema="account-owner-assignment-provenance-receipt.v2",
                    permission="evidence_only",
                    status="inactive",
                    claimant_kind="human",
                    issuer_kind="human",
                    row_observation_owner="account",
                    row_observation_artifact_type="physical_account_row_observation_v2",
                    row_observation_schema="physical-account-row-observation.v2",
                    row_is_active=True,
                    row_is_present=True,
                    row_is_tombstone=False,
                ),
                name="acct_prov_v2_fixed_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    row_observation_recorded_at__lte=models.F("issued_at"),
                    issued_at__lte=models.F("recorded_at"),
                    recorded_at__lt=models.F("valid_until"),
                    valid_until__lte=models.F("row_observation_valid_until"),
                    persisted_at=models.F("recorded_at"),
                ),
                name="acct_prov_v2_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    claimant_actor_id=models.F("issuer_actor_id"),
                    claimant_user_id=models.F("issuer_user_id"),
                    claimant_role=models.F("issuer_role"),
                    claimant_kind=models.F("issuer_kind"),
                    claimant_is_staff=models.F("issuer_is_staff"),
                ),
                name="acct_prov_v2_actor_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    models.Q(supersedes_content_hash__isnull=True, root_claim_hash__isnull=False)
                    | models.Q(supersedes_content_hash__isnull=False, root_claim_hash__isnull=True)
                ),
                name="acct_prov_v2_link_ck",
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
            raise ValidationError("provenance v2 is append-only")
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
            raise ValidationError("provenance v2 is append-only")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _CLAIM.get()
        if (
            claim is None
            or claim.token is not _UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, n) != v for n, v in claim.values)
        ):
            raise ValidationError("provenance v2 requires exact insert claim")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("provenance v2 is append-only")


def _reject_delete(
    sender: type[models.Model], instance: models.Model, using: str, origin: object, **kwargs: object
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("provenance v2 is append-only")


pre_delete.connect(
    _reject_delete,
    sender=AccountOwnerAssignmentProvenanceReceiptV2Model,
    dispatch_uid="account_provenance_receipt_v2_append_only",
)

__all__ = ["AccountOwnerAssignmentProvenanceReceiptV2Model"]
