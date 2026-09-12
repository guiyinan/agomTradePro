"""Append-only receipt-v4 ledger with durable creation, policy and actor parents."""

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

_T = TypeVar("_T", bound=models.Model)
_UOW: ContextVar[object | None] = ContextVar("receipt_v4_uow", default=None)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    using: str
    values: tuple[tuple[str, object], ...]


_CLAIM: ContextVar[_InsertClaim | None] = ContextVar("receipt_v4_insert", default=None)


@contextmanager
def _activate_receipt_v4_uow(token: object) -> Iterator[None]:
    reset = _UOW.set(token)
    try:
        yield
    finally:
        _UOW.reset(reset)


@contextmanager
def _claim_receipt_v4_insert(
    *, token: object, using: str, values: Mapping[str, object]
) -> Iterator[None]:
    if _UOW.get() is not token:
        raise ValidationError("receipt v4 insert requires private UOW")
    reset = _CLAIM.set(_InsertClaim(token, using, tuple(sorted(values.items()))))
    try:
        yield
    finally:
        _CLAIM.reset(reset)


class AccountOwnerAssignmentProvenanceReceiptV4QuerySet(AppendOnlyQuerySet[_T]):
    """Deny bulk inserts and mutation paths outside the exact append claim."""

    def bulk_create(
        self,
        objs: Iterable[_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Require every inserted receipt to pass its repository append contract."""
        raise ValidationError("receipt v4 requires exact append")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("receipt v4 is append-only")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("receipt v4 is append-only")


class AccountOwnerAssignmentProvenanceReceiptV4Manager(AppendOnlyManager[_T]):
    """Use the guarded queryset on every database alias."""

    def get_queryset(self) -> AccountOwnerAssignmentProvenanceReceiptV4QuerySet[_T]:
        """Return a queryset that rejects mutations and bulk insertion."""
        return AccountOwnerAssignmentProvenanceReceiptV4QuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject manager-level bulk inserts without an exact receipt claim."""
        raise ValidationError("receipt v4 requires exact append")


class AccountOwnerAssignmentProvenanceReceiptV4Model(models.Model):
    """One immutable receipt envelope referencing three durable evidence parents."""

    objects: AccountOwnerAssignmentProvenanceReceiptV4Manager[Self] = (
        AccountOwnerAssignmentProvenanceReceiptV4Manager()
    )
    binding = models.ForeignKey(
        "account.CanonicalAccountCreationBindingV2Model",
        on_delete=models.PROTECT,
        related_name="owner_claim_receipts_v4",
    )
    policy = models.ForeignKey(
        "account.SingleOwnerAuthorityPolicyV1Model",
        on_delete=models.PROTECT,
        related_name="owner_claim_receipts_v4",
    )
    actor_source = models.ForeignKey(
        "account.AccountOwnerAssignmentActorAuthoritySourceV3Model",
        on_delete=models.PROTECT,
        related_name="owner_claim_receipts_v4",
    )
    predecessor = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="successor",
    )
    receipt_id = models.CharField(max_length=192)
    receipt_version = models.CharField(max_length=192)
    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    issued_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField()
    persisted_at = models.DateTimeField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    supersedes_content_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    canonical_payload = models.JSONField()
    record_seal = models.CharField(max_length=64, unique=True)
    ledger_seal = models.CharField(max_length=64, unique=True)

    class Meta:
        app_label = "account"
        db_table = "account_owner_assignment_provenance_receipt_v4_ledger"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [models.Index(fields=("receipt_id", "recorded_at"), name="acct_prov_v4_chain_ix")]
        constraints = [
            models.UniqueConstraint(
                fields=("receipt_id", "receipt_version"), name="acct_prov_v4_id_uq"
            ),
            models.UniqueConstraint(
                fields=("receipt_id",),
                condition=models.Q(predecessor__isnull=True),
                name="acct_prov_v4_root_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="account_owner_assignment_provenance_receipt_v4",
                    schema="account-owner-assignment-provenance-receipt.v4",
                    permission="claim_evidence_only",
                    status="inactive",
                ),
                name="acct_prov_v4_fixed_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    issued_at__lte=models.F("recorded_at"),
                    recorded_at__lt=models.F("valid_until"),
                    persisted_at=models.F("recorded_at"),
                ),
                name="acct_prov_v4_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(predecessor__isnull=True, supersedes_content_hash__isnull=True)
                    | models.Q(predecessor__isnull=False, supersedes_content_hash__isnull=False)
                ),
                name="acct_prov_v4_link_ck",
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
        """Accept only one exact repository insert on the claimed database alias."""
        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("receipt v4 is append-only")
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
        """Guard Django's lower-level insert path with the same exact claim."""
        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("receipt v4 is append-only")
        self._require_claim(using)
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self, using: str | None) -> None:
        claim = _CLAIM.get()
        if (
            claim is None
            or claim.token is not _UOW.get()
            or using != claim.using
            or type(self) is not AccountOwnerAssignmentProvenanceReceiptV4Model
            or any(getattr(self, name) != value for name, value in claim.values)
        ):
            raise ValidationError("receipt v4 requires exact insert claim")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject deletion of persisted provenance."""
        raise ValidationError("receipt v4 is append-only")


def _reject_delete(
    sender: type[models.Model], instance: models.Model, using: str, origin: object, **kwargs: object
) -> NoReturn:
    raise ValidationError("receipt v4 is append-only")


pre_delete.connect(
    _reject_delete,
    sender=AccountOwnerAssignmentProvenanceReceiptV4Model,
    dispatch_uid="AccountOwnerAssignmentProvenanceReceiptV4Model_append_only",
)

__all__ = ["AccountOwnerAssignmentProvenanceReceiptV4Model"]
