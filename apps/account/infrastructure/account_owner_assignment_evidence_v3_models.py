"""Append-only ledgers for Account owner-assignment evidence v3."""

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
_UOW: ContextVar[object | None] = ContextVar("account_assignment_v3_uow", default=None)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    values: tuple[tuple[str, object], ...]


_CLAIM: ContextVar[_InsertClaim | None] = ContextVar("account_assignment_v3_claim", default=None)


@contextmanager
def _activate_account_owner_assignment_evidence_v3_uow(token: object) -> Iterator[None]:
    reset = _UOW.set(token)
    try:
        yield
    finally:
        _UOW.reset(reset)


@contextmanager
def _claim_account_owner_assignment_evidence_v3_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    if _UOW.get() is not token:
        raise ValidationError("owner-assignment v3 insert requires private UOW")
    reset = _CLAIM.set(_InsertClaim(token, model_type, tuple(sorted(expected_values.items()))))
    try:
        yield
    finally:
        _CLAIM.reset(reset)


class AccountOwnerAssignmentEvidenceV3QuerySet(AppendOnlyQuerySet[_T]):
    def bulk_create(
        self,
        objs: Iterable[_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("owner-assignment v3 requires exact appends")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("owner-assignment v3 is append-only")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("owner-assignment v3 is append-only")


class AccountOwnerAssignmentEvidenceV3Manager(AppendOnlyManager[_T]):
    def get_queryset(self) -> AccountOwnerAssignmentEvidenceV3QuerySet[_T]:
        return AccountOwnerAssignmentEvidenceV3QuerySet(self.model, using=self._db)

    def bulk_create(self, objs: Iterable[_T], **kwargs: object) -> NoReturn:
        raise ValidationError("owner-assignment v3 requires exact appends")


class _AppendOnlyEvidenceV3Model(models.Model):
    objects = AccountOwnerAssignmentEvidenceV3Manager()

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
        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("owner-assignment v3 is append-only")
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
            raise ValidationError("owner-assignment v3 is append-only")
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
            raise ValidationError("owner-assignment v3 requires exact insert claim")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("owner-assignment v3 is append-only")


class AccountOwnerAssignmentSubjectV3Model(_AppendOnlyEvidenceV3Model):
    receipt = models.OneToOneField(
        "account.AccountOwnerAssignmentProvenanceReceiptV3Model",
        on_delete=models.PROTECT,
        related_name="owner_assignment_subject_v3",
    )
    binding = models.ForeignKey(
        "account.CanonicalAccountCreationBindingV2Model",
        on_delete=models.PROTECT,
        related_name="owner_assignment_subjects_v3",
    )
    creation_root = models.ForeignKey(
        "account.AllocatedPhysicalAccountRowObservationV3Model",
        on_delete=models.PROTECT,
        related_name="owner_assignment_subjects_v3",
    )
    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    subject_id = models.CharField(max_length=192)
    subject_version = models.CharField(max_length=192)
    receipt_ref_id = models.CharField(max_length=192)
    receipt_ref_version = models.CharField(max_length=192)
    binding_ref_id = models.CharField(max_length=192)
    binding_ref_version = models.CharField(max_length=192)
    creation_root_ref_id = models.CharField(max_length=192)
    creation_root_ref_version = models.CharField(max_length=192)
    receipt_identity_hash = models.CharField(max_length=64)
    receipt_content_hash = models.CharField(max_length=64)
    binding_identity_hash = models.CharField(max_length=64)
    binding_content_hash = models.CharField(max_length=64)
    creation_root_identity_hash = models.CharField(max_length=64)
    creation_root_content_hash = models.CharField(max_length=64)
    binding_account_claim_hash = models.CharField(max_length=64)
    binding_underlying_claim_hash = models.CharField(max_length=64)
    physical_observation_content_hash = models.CharField(max_length=64)
    physical_source_content_hash = models.CharField(max_length=64)
    physical_raw_observation_content_hash = models.CharField(max_length=64)
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    underlying_unified_account_namespace = models.CharField(max_length=192)
    underlying_unified_account_id = models.PositiveBigIntegerField()
    assigned_owner_user_id = models.PositiveBigIntegerField()
    physical_row_user_id = models.PositiveBigIntegerField()
    claimant_actor_id = models.CharField(max_length=192)
    claimant_user_id = models.PositiveBigIntegerField()
    claimant_role = models.CharField(max_length=192)
    claimant_kind = models.CharField(max_length=16)
    claimant_is_staff = models.BooleanField()
    receipt_recorded_at = models.DateTimeField()
    receipt_valid_until = models.DateTimeField()
    creation_root_recorded_at = models.DateTimeField()
    creation_root_valid_until = models.DateTimeField()
    requested_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    blocker_codes = models.JSONField()
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    upstream_binding_seal = models.CharField(max_length=64)
    claimant_binding_seal = models.CharField(max_length=64)
    fixed_authority_seal = models.CharField(max_length=64)
    header_seal = models.CharField(max_length=64)
    record_seal = models.CharField(max_length=64, unique=True)
    ledger_seal = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta(_AppendOnlyEvidenceV3Model.Meta):
        app_label = "account"
        db_table = "account_owner_assignment_subject_v3_ledger"
        indexes = [models.Index(fields=("subject_id", "requested_at"), name="acct_own_v3_sub_ix")]
        constraints = [
            models.UniqueConstraint(
                fields=("subject_id", "subject_version"), name="acct_own_v3_sub_id_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="account_owner_assignment_subject_v3",
                    schema="account-owner-assignment-subject.v3",
                    permission="evidence_only",
                    status="inactive",
                    claimant_role="account_owner_claimant",
                    claimant_kind="human",
                    claimant_is_staff=False,
                ),
                name="acct_own_v3_sub_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(assigned_owner_user_id=models.F("claimant_user_id"))
                    & models.Q(claimant_user_id=models.F("physical_row_user_id"))
                ),
                name="acct_own_v3_sub_actor_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(receipt_recorded_at__lte=models.F("requested_at"))
                    & models.Q(requested_at__lt=models.F("valid_until"))
                    & models.Q(valid_until__lte=models.F("receipt_valid_until"))
                    & models.Q(valid_until__lte=models.F("creation_root_valid_until"))
                    & (
                        models.Q(valid_until=models.F("receipt_valid_until"))
                        | models.Q(valid_until=models.F("creation_root_valid_until"))
                    )
                    & models.Q(persisted_at=models.F("requested_at"))
                ),
                name="acct_own_v3_sub_clock_ck",
            ),
        ]


class AccountOwnerAssignmentEvidenceV3Model(_AppendOnlyEvidenceV3Model):
    subject = models.OneToOneField(
        AccountOwnerAssignmentSubjectV3Model,
        on_delete=models.PROTECT,
        related_name="approved_evidence_v3",
    )
    subject_content_hash = models.CharField(max_length=64, unique=True)
    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    evidence_id = models.CharField(max_length=192)
    evidence_version = models.CharField(max_length=192)
    assignment_state = models.CharField(max_length=32)
    assigned_owner_user_id = models.PositiveBigIntegerField()
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    underlying_unified_account_namespace = models.CharField(max_length=192)
    underlying_unified_account_id = models.PositiveBigIntegerField()
    claimant_actor_id = models.CharField(max_length=192)
    claimant_user_id = models.PositiveBigIntegerField()
    approved_actor_id = models.CharField(max_length=192)
    approved_user_id = models.PositiveBigIntegerField()
    approved_role = models.CharField(max_length=192)
    approved_kind = models.CharField(max_length=16)
    approved_is_staff = models.BooleanField()
    subject_requested_at = models.DateTimeField()
    subject_valid_until = models.DateTimeField()
    approved_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    approval_valid_until = models.DateTimeField()
    valid_until = models.DateTimeField(db_index=True)
    account_root_claim_hash = models.CharField(max_length=64, unique=True)
    underlying_root_claim_hash = models.CharField(max_length=64, unique=True)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    blocker_codes = models.JSONField()
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    subject_binding_seal = models.CharField(max_length=64)
    approver_binding_seal = models.CharField(max_length=64)
    mapping_binding_seal = models.CharField(max_length=64)
    fixed_authority_seal = models.CharField(max_length=64)
    header_seal = models.CharField(max_length=64)
    record_seal = models.CharField(max_length=64, unique=True)
    ledger_seal = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta(_AppendOnlyEvidenceV3Model.Meta):
        app_label = "account"
        db_table = "account_owner_assignment_evidence_v3_ledger"
        indexes = [models.Index(fields=("evidence_id", "recorded_at"), name="acct_own_v3_ev_ix")]
        constraints = [
            models.UniqueConstraint(
                fields=("evidence_id", "evidence_version"), name="acct_own_v3_ev_id_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="account_owner_assignment_evidence_v3",
                    schema="account-owner-assignment-evidence.v3",
                    assignment_state="authoritative",
                    permission="evidence_only",
                    status="inactive",
                    approved_role="account_owner_assignment_approver",
                    approved_kind="human",
                    approved_is_staff=True,
                ),
                name="acct_own_v3_ev_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(assigned_owner_user_id=models.F("claimant_user_id"))
                    & ~models.Q(approved_actor_id=models.F("claimant_actor_id"))
                    & ~models.Q(approved_user_id=models.F("claimant_user_id"))
                ),
                name="acct_own_v3_ev_actor_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(subject_requested_at__lte=models.F("approved_at"))
                    & models.Q(approved_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                    & models.Q(valid_until__lte=models.F("subject_valid_until"))
                    & models.Q(valid_until__lte=models.F("approval_valid_until"))
                    & (
                        models.Q(valid_until=models.F("subject_valid_until"))
                        | models.Q(valid_until=models.F("approval_valid_until"))
                    )
                    & models.Q(persisted_at=models.F("recorded_at"))
                ),
                name="acct_own_v3_ev_clock_ck",
            ),
        ]


def _reject_delete(
    sender: type[models.Model], instance: models.Model, using: str, origin: object, **kwargs: object
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("owner-assignment v3 is append-only")


for _model in (AccountOwnerAssignmentSubjectV3Model, AccountOwnerAssignmentEvidenceV3Model):
    pre_delete.connect(_reject_delete, sender=_model, dispatch_uid=f"{_model.__name__}_append_only")


__all__ = ["AccountOwnerAssignmentEvidenceV3Model", "AccountOwnerAssignmentSubjectV3Model"]
