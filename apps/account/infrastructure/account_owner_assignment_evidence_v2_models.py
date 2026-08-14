"""Append-only models for Account owner-assignment approval evidence v2."""

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
_UOW: ContextVar[object | None] = ContextVar("account_assignment_v2_uow", default=None)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    values: tuple[tuple[str, object], ...]


_CLAIM: ContextVar[_InsertClaim | None] = ContextVar("account_assignment_v2_claim", default=None)


@contextmanager
def _activate_account_owner_assignment_evidence_v2_uow(token: object) -> Iterator[None]:
    reset = _UOW.set(token)
    try:
        yield
    finally:
        _UOW.reset(reset)


@contextmanager
def _claim_account_owner_assignment_evidence_v2_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    if _UOW.get() is not token:
        raise ValidationError("owner-assignment v2 insert requires private UOW")
    reset = _CLAIM.set(_InsertClaim(token, model_type, tuple(sorted(expected_values.items()))))
    try:
        yield
    finally:
        _CLAIM.reset(reset)


class AccountOwnerAssignmentEvidenceV2QuerySet(AppendOnlyQuerySet[_T]):
    """Reject every bulk mutation path for both v2 ledgers."""

    def bulk_create(
        self,
        objs: Iterable[_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("owner-assignment v2 requires exact appends")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("owner-assignment v2 is append-only")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("owner-assignment v2 is append-only")


class AccountOwnerAssignmentEvidenceV2Manager(AppendOnlyManager[_T]):
    """Return the guarded queryset and reject manager bulk inserts."""

    def get_queryset(self) -> AccountOwnerAssignmentEvidenceV2QuerySet[_T]:
        return AccountOwnerAssignmentEvidenceV2QuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("owner-assignment v2 requires exact appends")


class _AppendOnlyAccountOwnerAssignmentEvidenceV2Model(models.Model):
    """Private claimed-insert and append-only behavior shared by both tables."""

    objects = AccountOwnerAssignmentEvidenceV2Manager()

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
            raise ValidationError("owner-assignment v2 is append-only")
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
            raise ValidationError("owner-assignment v2 is append-only")
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
            raise ValidationError("owner-assignment v2 requires exact insert claim")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("owner-assignment v2 is append-only")


class AccountOwnerAssignmentSubjectV2Model(_AppendOnlyAccountOwnerAssignmentEvidenceV2Model):
    """One immutable registration winner containing both canonical upstreams."""

    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    subject_id = models.CharField(max_length=192)
    subject_version = models.CharField(max_length=192)
    physical_observation_id = models.CharField(max_length=192)
    physical_observation_version = models.CharField(max_length=192)
    physical_identity_hash = models.CharField(max_length=64)
    physical_content_hash = models.CharField(max_length=64)
    receipt_id = models.CharField(max_length=192)
    receipt_version = models.CharField(max_length=192)
    receipt_identity_hash = models.CharField(max_length=64)
    receipt_content_hash = models.CharField(max_length=64)
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    underlying_unified_account_namespace = models.CharField(max_length=192)
    underlying_unified_account_id = models.PositiveBigIntegerField()
    requested_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    upstream_binding_seal = models.CharField(max_length=64)
    fixed_authority_seal = models.CharField(max_length=64)
    record_seal = models.CharField(max_length=64, unique=True)
    ledger_seal = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta(_AppendOnlyAccountOwnerAssignmentEvidenceV2Model.Meta):
        app_label = "account"
        db_table = "account_owner_assignment_subject_v2_ledger"
        indexes = [
            models.Index(fields=("subject_id", "requested_at"), name="acct_own_v2_sub_chain_ix")
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("subject_id", "subject_version"), name="acct_own_v2_sub_id_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="account_owner_assignment_subject_v2",
                    schema="account-owner-assignment-subject.v2",
                    permission="evidence_only",
                    status="inactive",
                ),
                name="acct_own_v2_sub_fixed_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    requested_at__lt=models.F("valid_until"),
                    persisted_at=models.F("requested_at"),
                ),
                name="acct_own_v2_sub_clock_ck",
            ),
        ]


class AccountOwnerAssignmentEvidenceV2Model(_AppendOnlyAccountOwnerAssignmentEvidenceV2Model):
    """One independent staff approval over an exact registered subject."""

    subject = models.OneToOneField(
        AccountOwnerAssignmentSubjectV2Model,
        on_delete=models.PROTECT,
        related_name="approved_evidence",
    )
    subject_content_hash = models.CharField(max_length=64, unique=True)
    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    evidence_id = models.CharField(max_length=192)
    evidence_version = models.CharField(max_length=192)
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    underlying_unified_account_namespace = models.CharField(max_length=192)
    underlying_unified_account_id = models.PositiveBigIntegerField()
    assignment_state = models.CharField(max_length=32)
    assigned_owner_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    approved_actor_id = models.CharField(max_length=192)
    approved_user_id = models.PositiveBigIntegerField()
    approved_role = models.CharField(max_length=192)
    approved_kind = models.CharField(max_length=16)
    approved_is_staff = models.BooleanField()
    approved_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    approval_valid_until = models.DateTimeField()
    valid_until = models.DateTimeField(db_index=True)
    supersedes_content_hash = models.CharField(max_length=64, null=True, blank=True)
    account_root_claim_hash = models.CharField(max_length=64, null=True, blank=True)
    underlying_root_claim_hash = models.CharField(max_length=64, null=True, blank=True)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    blocker_codes = models.JSONField()
    canonical_payload = models.JSONField()
    subject_binding_seal = models.CharField(max_length=64)
    approver_binding_seal = models.CharField(max_length=64)
    mapping_binding_seal = models.CharField(max_length=64)
    fixed_authority_seal = models.CharField(max_length=64)
    record_seal = models.CharField(max_length=64, unique=True)
    ledger_seal = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta(_AppendOnlyAccountOwnerAssignmentEvidenceV2Model.Meta):
        app_label = "account"
        db_table = "account_owner_assignment_evidence_v2_ledger"
        indexes = [
            models.Index(fields=("evidence_id", "recorded_at"), name="acct_own_v2_ev_chain_ix")
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("evidence_id", "evidence_version"), name="acct_own_v2_ev_id_uq"
            ),
            models.UniqueConstraint(
                fields=("account_root_claim_hash",),
                condition=models.Q(account_root_claim_hash__isnull=False),
                name="acct_own_v2_acct_root_uq",
            ),
            models.UniqueConstraint(
                fields=("underlying_root_claim_hash",),
                condition=models.Q(underlying_root_claim_hash__isnull=False),
                name="acct_own_v2_under_root_uq",
            ),
            models.UniqueConstraint(
                fields=("supersedes_content_hash",),
                condition=models.Q(supersedes_content_hash__isnull=False),
                name="acct_own_v2_next_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="account_owner_assignment_evidence_v2",
                    schema="account-owner-assignment-evidence.v2",
                    permission="evidence_only",
                    status="inactive",
                    approved_kind="human",
                    approved_is_staff=True,
                    approved_role="account_owner_assignment_approver",
                ),
                name="acct_own_v2_ev_fixed_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    approved_at__lte=models.F("recorded_at"),
                    recorded_at__lt=models.F("approval_valid_until"),
                    valid_until__lte=models.F("approval_valid_until"),
                    persisted_at=models.F("recorded_at"),
                ),
                name="acct_own_v2_ev_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        supersedes_content_hash__isnull=True,
                        account_root_claim_hash__isnull=False,
                        underlying_root_claim_hash__isnull=False,
                    )
                    | models.Q(
                        supersedes_content_hash__isnull=False,
                        account_root_claim_hash__isnull=True,
                        underlying_root_claim_hash__isnull=True,
                    )
                ),
                name="acct_own_v2_link_ck",
            ),
        ]


def _reject_delete(
    sender: type[models.Model], instance: models.Model, using: str, origin: object, **kwargs: object
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("owner-assignment v2 is append-only")


for _model in (AccountOwnerAssignmentSubjectV2Model, AccountOwnerAssignmentEvidenceV2Model):
    pre_delete.connect(
        _reject_delete,
        sender=_model,
        dispatch_uid=f"{_model.__name__}_append_only",
    )


__all__ = [
    "AccountOwnerAssignmentEvidenceV2Model",
    "AccountOwnerAssignmentSubjectV2Model",
]
