"""Append-only Receipt, Subject, and Evidence V5 ownership ledgers."""

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
_UOW: ContextVar[object | None] = ContextVar("assignment_v5_uow", default=None)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    using: str
    model_type: type[models.Model]
    values: tuple[tuple[str, object], ...]


_CLAIM: ContextVar[_InsertClaim | None] = ContextVar("assignment_v5_claim", default=None)


@contextmanager
def _activate_assignment_v5_uow(token: object) -> Iterator[None]:
    reset = _UOW.set(token)
    try:
        yield
    finally:
        _UOW.reset(reset)


@contextmanager
def _claim_assignment_v5_insert(
    *, token: object, using: str, model_type: type[models.Model], values: Mapping[str, object]
) -> Iterator[None]:
    if _UOW.get() is not token:
        raise ValidationError("assignment v5 insert requires private UOW")
    reset = _CLAIM.set(_InsertClaim(token, using, model_type, tuple(sorted(values.items()))))
    try:
        yield
    finally:
        _CLAIM.reset(reset)


class AccountOwnerAssignmentV5QuerySet(AppendOnlyQuerySet[_T]):
    """Reject mutations and insertion paths without exact repository claims."""

    def bulk_create(
        self,
        objs: Iterable[_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject bulk insertion because each envelope requires parent verification."""
        raise ValidationError("assignment v5 requires exact appends")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("assignment v5 is append-only")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("assignment v5 is append-only")


class AccountOwnerAssignmentV5Manager(AppendOnlyManager[_T]):
    """Use the guarded queryset on every selected database alias."""

    def get_queryset(self) -> AccountOwnerAssignmentV5QuerySet[_T]:
        """Return a queryset that rejects mutation and bulk insertion."""
        return AccountOwnerAssignmentV5QuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject manager-level bulk insertion."""
        raise ValidationError("assignment v5 requires exact appends")


class _AssignmentV5Model(models.Model):
    objects: AccountOwnerAssignmentV5Manager[Self] = AccountOwnerAssignmentV5Manager()
    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    valid_until = models.DateTimeField()
    persisted_at = models.DateTimeField()
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
        """Accept only one exact repository insert on the claimed alias."""
        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("assignment v5 is append-only")
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
        """Guard Django's lower-level insert path with the exact claim."""
        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("assignment v5 is append-only")
        self._require_claim(using)
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self, using: str | None) -> None:
        claim = _CLAIM.get()
        if (
            claim is None
            or claim.token is not _UOW.get()
            or using != claim.using
            or claim.model_type is not type(self)
            or any(getattr(self, name) != value for name, value in claim.values)
        ):
            raise ValidationError("assignment v5 requires exact insert claim")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject removal of persisted ownership provenance."""
        raise ValidationError("assignment v5 is append-only")


class AccountOwnerAssignmentProvenanceReceiptV5Model(_AssignmentV5Model):
    """One immutable receipt binding policy, Binding V2, and re-observation V1."""

    policy = models.ForeignKey(
        "account.SingleOwnerAuthorityPolicyV1Model",
        on_delete=models.PROTECT,
        related_name="owner_claim_receipts_v5",
    )
    binding = models.ForeignKey(
        "account.CanonicalAccountCreationBindingV2Model",
        on_delete=models.PROTECT,
        related_name="owner_claim_receipts_v5",
    )
    reobservation = models.ForeignKey(
        "account.CanonicalAccountOwnershipReobservationV1Model",
        on_delete=models.PROTECT,
        related_name="owner_claim_receipts_v5",
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
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    underlying_unified_account_namespace = models.CharField(max_length=192)
    underlying_unified_account_id = models.PositiveBigIntegerField()
    assigned_owner_user_id = models.PositiveBigIntegerField()
    issued_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    supersedes_content_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)

    class Meta(_AssignmentV5Model.Meta):
        app_label = "account"
        db_table = "account_owner_assignment_provenance_receipt_v5_ledger"
        indexes = [models.Index(fields=("receipt_id", "recorded_at"), name="acct_prov_v5_chain_ix")]
        constraints = [
            models.UniqueConstraint(
                fields=("receipt_id", "receipt_version"), name="acct_prov_v5_id_uq"
            ),
            models.UniqueConstraint(
                fields=("receipt_id",),
                condition=models.Q(predecessor__isnull=True),
                name="acct_prov_v5_root_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="account_owner_assignment_provenance_receipt_v5",
                    schema="account-owner-assignment-provenance-receipt.v5",
                    permission="claim_evidence_only",
                    status="inactive",
                ),
                name="acct_prov_v5_fixed_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    issued_at__lte=models.F("recorded_at"),
                    recorded_at__lt=models.F("valid_until"),
                    persisted_at=models.F("recorded_at"),
                ),
                name="acct_prov_v5_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(predecessor__isnull=True, supersedes_content_hash__isnull=True)
                    | models.Q(predecessor__isnull=False, supersedes_content_hash__isnull=False)
                ),
                name="acct_prov_v5_link_ck",
            ),
        ]


class AccountOwnerAssignmentSubjectV5Model(_AssignmentV5Model):
    """One immutable subject with exact V5 receipt and canonical graph parents."""

    receipt = models.OneToOneField(
        AccountOwnerAssignmentProvenanceReceiptV5Model,
        on_delete=models.PROTECT,
        related_name="assignment_subject_v5",
    )
    binding = models.ForeignKey(
        "account.CanonicalAccountCreationBindingV2Model",
        on_delete=models.PROTECT,
        related_name="owner_assignment_subjects_v5",
    )
    reobservation = models.ForeignKey(
        "account.CanonicalAccountOwnershipReobservationV1Model",
        on_delete=models.PROTECT,
        related_name="owner_assignment_subjects_v5",
    )
    subject_id = models.CharField(max_length=192)
    subject_version = models.CharField(max_length=192)
    requested_at = models.DateTimeField(db_index=True)

    class Meta(_AssignmentV5Model.Meta):
        app_label = "account"
        db_table = "account_owner_assignment_subject_v5_ledger"
        constraints = [
            models.UniqueConstraint(
                fields=("subject_id", "subject_version"), name="acct_asg_v5_sub_id_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="account_owner_assignment_subject_v5",
                    schema="account-owner-assignment-subject.v5",
                    permission="evidence_only",
                    status="inactive",
                ),
                name="acct_asg_v5_sub_fixed_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    requested_at__lt=models.F("valid_until"),
                    persisted_at=models.F("requested_at"),
                ),
                name="acct_asg_v5_sub_clock_ck",
            ),
        ]


class AccountOwnerAssignmentEvidenceV5Model(_AssignmentV5Model):
    """One inactive root assignment with exact Subject V5 and approval source."""

    subject = models.OneToOneField(
        AccountOwnerAssignmentSubjectV5Model,
        on_delete=models.PROTECT,
        related_name="evidence_v5",
    )
    actor_source = models.ForeignKey(
        "account.AccountOwnerAssignmentActorAuthoritySourceV3Model",
        on_delete=models.PROTECT,
        related_name="assignment_approvals_v5",
    )
    evidence_id = models.CharField(max_length=192)
    evidence_version = models.CharField(max_length=192)
    assignment_state = models.CharField(max_length=32)
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    underlying_unified_account_namespace = models.CharField(max_length=192)
    underlying_unified_account_id = models.PositiveBigIntegerField()
    account_claim_hash = models.CharField(max_length=64, unique=True)
    underlying_claim_hash = models.CharField(max_length=64, unique=True)
    approved_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    approval_valid_until = models.DateTimeField()

    class Meta(_AssignmentV5Model.Meta):
        app_label = "account"
        db_table = "account_owner_assignment_evidence_v5_ledger"
        constraints = [
            models.UniqueConstraint(
                fields=("evidence_id", "evidence_version"), name="acct_asg_v5_ev_id_uq"
            ),
            models.UniqueConstraint(
                fields=("account_namespace", "account_id"), name="acct_asg_v5_account_uq"
            ),
            models.UniqueConstraint(
                fields=("underlying_unified_account_namespace", "underlying_unified_account_id"),
                name="acct_asg_v5_underlying_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="account_owner_assignment_evidence_v5",
                    schema="account-owner-assignment-evidence.v5",
                    assignment_state="authoritative",
                    permission="evidence_only",
                    status="inactive",
                ),
                name="acct_asg_v5_ev_fixed_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    approved_at__lte=models.F("recorded_at"),
                    recorded_at__lt=models.F("valid_until"),
                    valid_until__lte=models.F("approval_valid_until"),
                    persisted_at=models.F("recorded_at"),
                ),
                name="acct_asg_v5_ev_clock_ck",
            ),
        ]


def _reject_delete(
    sender: type[models.Model], instance: models.Model, using: str, origin: object, **kwargs: object
) -> NoReturn:
    raise ValidationError("assignment v5 is append-only")


for _model in (
    AccountOwnerAssignmentProvenanceReceiptV5Model,
    AccountOwnerAssignmentSubjectV5Model,
    AccountOwnerAssignmentEvidenceV5Model,
):
    pre_delete.connect(_reject_delete, sender=_model, dispatch_uid=_model.__name__ + "_append_only")


__all__ = [
    "AccountOwnerAssignmentEvidenceV5Model",
    "AccountOwnerAssignmentProvenanceReceiptV5Model",
    "AccountOwnerAssignmentSubjectV5Model",
]
