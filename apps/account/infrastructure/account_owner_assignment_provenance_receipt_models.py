"""Append-only storage model for Account assignment provenance receipts."""

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
_ACTIVE_PROVENANCE_UOW: ContextVar[object | None] = ContextVar(
    "active_account_owner_assignment_provenance_uow", default=None
)


@dataclass(frozen=True)
class _ProvenanceInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_PROVENANCE_CLAIM: ContextVar[_ProvenanceInsertClaim | None] = ContextVar(
    "active_account_owner_assignment_provenance_claim", default=None
)


@contextmanager
def _activate_account_owner_assignment_provenance_uow(token: object) -> Iterator[None]:
    """Activate only this ledger's private unit-of-work token."""

    reset = _ACTIVE_PROVENANCE_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_PROVENANCE_UOW.reset(reset)


@contextmanager
def _claim_account_owner_assignment_provenance_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact repository-controlled provenance insert."""

    if _ACTIVE_PROVENANCE_UOW.get() is not token:
        raise ValidationError("Account provenance insert requires its private UOW.")
    reset = _ACTIVE_PROVENANCE_CLAIM.set(
        _ProvenanceInsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_PROVENANCE_CLAIM.reset(reset)


class AccountOwnerAssignmentProvenanceReceiptQuerySet(AppendOnlyQuerySet[_ModelT]):
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
        raise ValidationError("Account provenance receipts require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Account provenance receipts cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("Account provenance receipts cannot be deleted.")


class AccountOwnerAssignmentProvenanceReceiptManager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> AccountOwnerAssignmentProvenanceReceiptQuerySet[_ModelT]:
        return AccountOwnerAssignmentProvenanceReceiptQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Account provenance receipts require exact repository appends.")


class AccountOwnerAssignmentProvenanceReceiptModel(models.Model):
    """One immutable actor-bound Account provenance receipt ledger record."""

    objects = AccountOwnerAssignmentProvenanceReceiptManager()

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
    row_observation_id = models.CharField(max_length=192)
    row_observation_version = models.CharField(max_length=192)
    row_observation_identity_hash = models.CharField(max_length=64)
    row_observation_content_hash = models.CharField(max_length=64)
    row_observation_valid_until = models.DateTimeField()
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
    row_binding_hash = models.CharField(max_length=64)
    issuer_binding_hash = models.CharField(max_length=64, unique=True)
    record_header_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta:
        app_label = "account"
        db_table = "account_owner_assignment_provenance_receipt_ledger"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(fields=("receipt_id", "recorded_at"), name="acct_prov_receipt_chain_ix")
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("receipt_id", "receipt_version"), name="acct_prov_receipt_id_uq"
            ),
            models.UniqueConstraint(
                fields=("root_claim_hash",),
                condition=models.Q(root_claim_hash__isnull=False),
                name="acct_prov_receipt_root_uq",
            ),
            models.UniqueConstraint(
                fields=("supersedes_content_hash",),
                condition=models.Q(supersedes_content_hash__isnull=False),
                name="acct_prov_receipt_next_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    schema="account-owner-assignment-provenance-receipt.v1",
                    permission="evidence_only",
                    status="inactive",
                    claimant_kind="human",
                    issuer_kind="human",
                ),
                name="acct_prov_receipt_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        issued_at__lte=models.F("recorded_at"),
                        recorded_at__lt=models.F("valid_until"),
                        valid_until__lte=models.F("row_observation_valid_until"),
                        persisted_at=models.F("recorded_at"),
                    )
                ),
                name="acct_prov_receipt_clock_ck",
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
                name="acct_prov_receipt_link_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    claimant_actor_id=models.F("issuer_actor_id"),
                    claimant_user_id=models.F("issuer_user_id"),
                    claimant_role=models.F("issuer_role"),
                    claimant_kind=models.F("issuer_kind"),
                    claimant_is_staff=models.F("issuer_is_staff"),
                ),
                name="acct_prov_receipt_actor_ck",
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
            raise ValidationError("Account provenance receipts are append-only.")
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
            raise ValidationError("Account provenance receipts are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_PROVENANCE_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_PROVENANCE_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Account provenance receipt requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Account provenance receipts cannot be deleted.")


def _reject_account_owner_assignment_provenance_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject collector deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Account provenance receipts cannot be deleted.")


pre_delete.connect(
    _reject_account_owner_assignment_provenance_delete,
    sender=AccountOwnerAssignmentProvenanceReceiptModel,
    dispatch_uid="reject_account_owner_assignment_provenance_delete",
    weak=False,
)


__all__ = ["AccountOwnerAssignmentProvenanceReceiptModel"]
