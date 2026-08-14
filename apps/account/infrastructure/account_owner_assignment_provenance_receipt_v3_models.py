"""Append-only ledger model for Account creation-claim receipts v3."""

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
_UOW: ContextVar[object | None] = ContextVar("account_provenance_v3_uow", default=None)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    values: tuple[tuple[str, object], ...]


_CLAIM: ContextVar[_InsertClaim | None] = ContextVar("account_provenance_v3_claim", default=None)


@contextmanager
def _activate_account_owner_assignment_provenance_receipt_v3_uow(token: object) -> Iterator[None]:
    reset = _UOW.set(token)
    try:
        yield
    finally:
        _UOW.reset(reset)


@contextmanager
def _claim_account_owner_assignment_provenance_receipt_v3_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    if _UOW.get() is not token:
        raise ValidationError("provenance v3 insert requires private UOW")
    reset = _CLAIM.set(_InsertClaim(token, model_type, tuple(sorted(expected_values.items()))))
    try:
        yield
    finally:
        _CLAIM.reset(reset)


class AccountOwnerAssignmentProvenanceReceiptV3QuerySet(AppendOnlyQuerySet[_T]):
    def bulk_create(
        self,
        objs: Iterable[_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("provenance v3 requires exact appends")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("provenance v3 is append-only")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("provenance v3 is append-only")


class AccountOwnerAssignmentProvenanceReceiptV3Manager(AppendOnlyManager[_T]):
    def get_queryset(self) -> AccountOwnerAssignmentProvenanceReceiptV3QuerySet[_T]:
        return AccountOwnerAssignmentProvenanceReceiptV3QuerySet(self.model, using=self._db)

    def bulk_create(self, objs: Iterable[_T], **kwargs: object) -> NoReturn:
        raise ValidationError("provenance v3 requires exact appends")


class AccountOwnerAssignmentProvenanceReceiptV3Model(models.Model):
    """One immutable receipt with exact Binding-v2 and predecessor foreign keys."""

    objects = AccountOwnerAssignmentProvenanceReceiptV3Manager()
    binding = models.ForeignKey(
        "account.CanonicalAccountCreationBindingV2Model",
        on_delete=models.PROTECT,
        related_name="owner_claim_receipts_v3",
    )
    predecessor = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="successor",
    )
    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    provenance_kind = models.CharField(max_length=32)
    assignment_state = models.CharField(max_length=32)
    assigned_owner_user_id = models.PositiveBigIntegerField()
    receipt_id = models.CharField(max_length=192)
    receipt_version = models.CharField(max_length=192)
    binding_ref_id = models.CharField(max_length=192)
    binding_ref_version = models.CharField(max_length=192)
    binding_identity_hash = models.CharField(max_length=64)
    binding_content_hash = models.CharField(max_length=64)
    binding_recorded_at = models.DateTimeField()
    allocation_identity_hash = models.CharField(max_length=64)
    creation_root_content_hash = models.CharField(max_length=64)
    creation_root_identity_hash = models.CharField(max_length=64)
    creation_root_recorded_at = models.DateTimeField()
    creation_root_valid_until = models.DateTimeField()
    allocation_content_hash = models.CharField(max_length=64)
    account_claim_hash = models.CharField(max_length=64)
    underlying_claim_hash = models.CharField(max_length=64)
    physical_observation_content_hash = models.CharField(max_length=64)
    physical_source_content_hash = models.CharField(max_length=64)
    physical_raw_observation_content_hash = models.CharField(max_length=64)
    physical_row_user_id = models.PositiveBigIntegerField()
    claimant_user_id = models.PositiveBigIntegerField()
    claimant_actor_id = models.CharField(max_length=192)
    claimant_role = models.CharField(max_length=192)
    claimant_kind = models.CharField(max_length=16)
    claimant_is_staff = models.BooleanField()
    issuer_actor_id = models.CharField(max_length=192)
    issuer_user_id = models.PositiveBigIntegerField()
    issuer_role = models.CharField(max_length=192)
    issuer_kind = models.CharField(max_length=16)
    issuer_is_staff = models.BooleanField()
    issued_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField()
    supersedes_content_hash = models.CharField(max_length=64, null=True, blank=True)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    blocker_codes = models.JSONField()
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    record_seal = models.CharField(max_length=64, unique=True)
    binding_seal = models.CharField(max_length=64)
    claimant_seal = models.CharField(max_length=64)
    actor_binding_seal = models.CharField(max_length=64)
    chain_seal = models.CharField(max_length=64)
    fixed_authority_seal = models.CharField(max_length=64)
    header_seal = models.CharField(max_length=64)
    ledger_seal = models.CharField(max_length=64, unique=True)
    root_claim_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    persisted_at = models.DateTimeField()

    class Meta:
        app_label = "account"
        db_table = "account_owner_assignment_provenance_receipt_v3_ledger"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [models.Index(fields=("receipt_id", "recorded_at"), name="acct_prov_v3_chain_ix")]
        constraints = [
            models.UniqueConstraint(
                fields=("receipt_id", "receipt_version"), name="acct_prov_v3_id_uq"
            ),
            models.UniqueConstraint(
                fields=("receipt_id",),
                condition=models.Q(predecessor__isnull=True),
                name="acct_prov_v3_root_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="account_owner_assignment_provenance_receipt_v3",
                    schema="account-owner-assignment-provenance-receipt.v3",
                    provenance_kind="creation",
                    assignment_state="claimed_owner",
                    permission="claim_evidence_only",
                    status="inactive",
                    claimant_kind="human",
                    claimant_is_staff=False,
                    issuer_kind="human",
                    issuer_is_staff=False,
                ),
                name="acct_prov_v3_fixed_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    creation_root_recorded_at__lte=models.F("binding_recorded_at"),
                    binding_recorded_at__lte=models.F("issued_at"),
                    issued_at__lte=models.F("recorded_at"),
                    recorded_at__lt=models.F("valid_until"),
                    valid_until__lte=models.F("creation_root_valid_until"),
                    persisted_at=models.F("recorded_at"),
                ),
                name="acct_prov_v3_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(assigned_owner_user_id=models.F("claimant_user_id"))
                    & models.Q(claimant_user_id=models.F("physical_row_user_id"))
                    & models.Q(claimant_actor_id=models.F("issuer_actor_id"))
                    & models.Q(claimant_user_id=models.F("issuer_user_id"))
                    & models.Q(claimant_role=models.F("issuer_role"))
                    & models.Q(claimant_kind=models.F("issuer_kind"))
                    & models.Q(claimant_is_staff=models.F("issuer_is_staff"))
                ),
                name="acct_prov_v3_actor_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        predecessor__isnull=True,
                        supersedes_content_hash__isnull=True,
                        root_claim_hash__isnull=False,
                    )
                    | models.Q(
                        predecessor__isnull=False,
                        supersedes_content_hash__isnull=False,
                        root_claim_hash__isnull=True,
                    )
                ),
                name="acct_prov_v3_link_ck",
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
            raise ValidationError("provenance v3 is append-only")
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
            raise ValidationError("provenance v3 is append-only")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _CLAIM.get()
        if (
            claim is None
            or claim.token is not _UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != value for name, value in claim.values)
        ):
            raise ValidationError("provenance v3 requires exact insert claim")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("provenance v3 is append-only")


def _reject_delete(
    sender: type[models.Model], instance: models.Model, using: str, origin: object, **kwargs: object
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("provenance v3 is append-only")


pre_delete.connect(
    _reject_delete,
    sender=AccountOwnerAssignmentProvenanceReceiptV3Model,
    dispatch_uid="account_provenance_receipt_v3_append_only",
)

__all__ = ["AccountOwnerAssignmentProvenanceReceiptV3Model"]
