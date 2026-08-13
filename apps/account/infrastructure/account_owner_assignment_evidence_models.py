"""Append-only subject and evidence tables for Account owner assignment."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, TypeVar, cast

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_ACCOUNT_OWNER_ASSIGNMENT_UOW: ContextVar[object | None] = ContextVar(
    "active_account_owner_assignment_uow",
    default=None,
)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_ACCOUNT_OWNER_ASSIGNMENT_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_account_owner_assignment_claim",
    default=None,
)


@contextmanager
def _activate_account_owner_assignment_uow(token: object) -> Iterator[None]:
    """Activate only this ledger's private unit-of-work token."""

    reset = _ACTIVE_ACCOUNT_OWNER_ASSIGNMENT_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_ACCOUNT_OWNER_ASSIGNMENT_UOW.reset(reset)


@contextmanager
def _claim_account_owner_assignment_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Claim one exact repository-controlled subject or evidence insert."""

    if _ACTIVE_ACCOUNT_OWNER_ASSIGNMENT_UOW.get() is not token:
        raise ValidationError("Account owner assignment insert requires its private UOW.")
    reset = _ACTIVE_ACCOUNT_OWNER_ASSIGNMENT_CLAIM.set(
        _InsertClaim(
            token=token,
            model_type=model_type,
            expected_values=tuple(sorted(expected_values.items())),
        )
    )
    try:
        yield
    finally:
        _ACTIVE_ACCOUNT_OWNER_ASSIGNMENT_CLAIM.reset(reset)


def _require_account_owner_assignment_insert_claim(model: models.Model) -> None:
    claim = _ACTIVE_ACCOUNT_OWNER_ASSIGNMENT_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_ACCOUNT_OWNER_ASSIGNMENT_UOW.get()
        or claim.model_type is not type(model)
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("Account owner assignment requires an exact insert claim.")


class AccountOwnerAssignmentQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject mutation and every unclaimed/bulk insert shortcut."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Account owner assignments require exact repository appends.")

    def _update(self, values: object) -> NoReturn:
        raise ValidationError("Account owner assignments cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("Account owner assignments cannot be deleted.")

    def _insert(
        self,
        objs: Iterable[_ModelT],
        fields: Iterable[object],
        returning_fields: Iterable[object] | None = None,
        raw: bool = False,
        using: str | None = None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> list[tuple[object, ...]]:
        items = list(objs)
        if (
            not items
            or raw
            or on_conflict is not None
            or update_fields is not None
            or unique_fields is not None
            or (using is not None and using != self.db)
        ):
            raise ValidationError("Account owner assignment private insert is forbidden.")
        for item in items:
            _require_account_owner_assignment_insert_claim(item)
        insert = cast(
            Callable[..., list[tuple[object, ...]]],
            getattr(super(), "_insert"),  # noqa: B009 -- private Django boundary
        )
        return insert(
            items,
            fields,
            returning_fields=returning_fields,
            raw=False,
            using=using,
            on_conflict=None,
            update_fields=None,
            unique_fields=None,
        )

    def _batched_insert(
        self,
        objs: list[_ModelT],
        fields: list[object],
        batch_size: int | None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> NoReturn:
        raise ValidationError("Account owner assignment private bulk insert is forbidden.")


class AccountOwnerAssignmentManager(AppendOnlyManager[_ModelT]):
    """Expose identical append-only guards through base/default managers."""

    def get_queryset(self) -> AccountOwnerAssignmentQuerySet[_ModelT]:
        return AccountOwnerAssignmentQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Account owner assignments require exact repository appends.")


class AccountOwnerAssignmentAppendOnlyModel(models.Model):
    """Permit only one exact repository-claimed insert."""

    objects = AccountOwnerAssignmentManager()

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
            raise ValidationError("Account owner assignments are append-only.")
        _require_account_owner_assignment_insert_claim(self)
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
            raise ValidationError("Account owner assignments are append-only.")
        _require_account_owner_assignment_insert_claim(self)
        super().save_base(force_insert=force_insert, using=using)

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("Account owner assignments cannot be deleted.")


class AccountOwnerAssignmentSubjectModel(AccountOwnerAssignmentAppendOnlyModel):
    """Complete immutable row/provenance/claimant registration first winner."""

    evidence_id = models.CharField(max_length=192)
    evidence_version = models.CharField(max_length=192)
    subject_identity_hash = models.CharField(max_length=64, unique=True)

    row_owner = models.CharField(max_length=32)
    row_artifact_type = models.CharField(max_length=64)
    row_observation_id = models.CharField(max_length=192)
    row_observation_version = models.CharField(max_length=192)
    row_content_hash = models.CharField(max_length=64)
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    underlying_unified_account_namespace = models.CharField(max_length=192)
    underlying_unified_account_id = models.PositiveBigIntegerField()
    row_observed_at = models.DateTimeField()
    row_recorded_at = models.DateTimeField()
    row_valid_until = models.DateTimeField()
    row_binding_hash = models.CharField(max_length=64, unique=True)

    receipt_owner = models.CharField(max_length=32)
    receipt_artifact_type = models.CharField(max_length=64)
    receipt_id = models.CharField(max_length=192)
    receipt_version = models.CharField(max_length=192)
    receipt_content_hash = models.CharField(max_length=64)
    provenance_kind = models.CharField(max_length=32)
    assignment_state = models.CharField(max_length=32)
    assigned_owner_user_id = models.PositiveBigIntegerField(null=True)
    receipt_account_namespace = models.CharField(max_length=192)
    receipt_account_id = models.CharField(max_length=192)
    receipt_underlying_namespace = models.CharField(max_length=192)
    receipt_underlying_id = models.PositiveBigIntegerField()
    receipt_row_id = models.CharField(max_length=192)
    receipt_row_version = models.CharField(max_length=192)
    receipt_row_content_hash = models.CharField(max_length=64)
    receipt_claimant_actor_id = models.CharField(max_length=192)
    receipt_claimant_user_id = models.PositiveBigIntegerField()
    receipt_claimant_role = models.CharField(max_length=192)
    receipt_claimant_kind = models.CharField(max_length=16)
    receipt_claimant_is_staff = models.BooleanField()
    receipt_issued_at = models.DateTimeField()
    receipt_recorded_at = models.DateTimeField()
    receipt_valid_until = models.DateTimeField()
    provenance_binding_hash = models.CharField(max_length=64, unique=True)

    claimant_actor_id = models.CharField(max_length=192)
    claimant_user_id = models.PositiveBigIntegerField()
    claimant_role = models.CharField(max_length=192)
    claimant_kind = models.CharField(max_length=16)
    claimant_is_staff = models.BooleanField()
    requested_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta(AccountOwnerAssignmentAppendOnlyModel.Meta):
        db_table = "account_owner_assignment_subject"
        indexes = [
            models.Index(
                fields=("account_namespace", "account_id", "recorded_at"),
                name="acct_own_asg_subj_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("evidence_id", "evidence_version"),
                name="acct_own_asg_subj_id_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    row_owner="simulated_trading",
                    row_artifact_type="unified_account_row_observation",
                    account_namespace="account",
                    underlying_unified_account_namespace="simulated-account-row",
                    receipt_owner="account",
                    claimant_kind="human",
                    receipt_claimant_kind="human",
                ),
                name="acct_own_asg_subj_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(row_observed_at__lte=models.F("row_recorded_at"))
                    & models.Q(row_recorded_at__lte=models.F("requested_at"))
                    & models.Q(receipt_issued_at__lte=models.F("receipt_recorded_at"))
                    & models.Q(receipt_recorded_at__lte=models.F("requested_at"))
                    & models.Q(requested_at=models.F("recorded_at"))
                    & models.Q(recorded_at=models.F("persisted_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                    & models.Q(valid_until__lte=models.F("row_valid_until"))
                    & models.Q(valid_until__lte=models.F("receipt_valid_until"))
                ),
                name="acct_own_asg_subj_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(receipt_account_namespace=models.F("account_namespace"))
                    & models.Q(receipt_account_id=models.F("account_id"))
                    & models.Q(
                        receipt_underlying_namespace=models.F(
                            "underlying_unified_account_namespace"
                        )
                    )
                    & models.Q(receipt_underlying_id=models.F("underlying_unified_account_id"))
                    & models.Q(receipt_row_id=models.F("row_observation_id"))
                    & models.Q(receipt_row_version=models.F("row_observation_version"))
                    & models.Q(receipt_row_content_hash=models.F("row_content_hash"))
                    & models.Q(receipt_claimant_actor_id=models.F("claimant_actor_id"))
                    & models.Q(receipt_claimant_user_id=models.F("claimant_user_id"))
                    & models.Q(receipt_claimant_role=models.F("claimant_role"))
                    & models.Q(receipt_claimant_kind=models.F("claimant_kind"))
                    & models.Q(receipt_claimant_is_staff=models.F("claimant_is_staff"))
                ),
                name="acct_own_asg_subj_bind_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        provenance_kind__in=("creation", "manual_reclaim"),
                        assignment_state="authoritative",
                        assigned_owner_user_id=models.F("claimant_user_id"),
                    )
                    | models.Q(
                        provenance_kind="migration",
                        assignment_state="legacy_default",
                        assigned_owner_user_id__isnull=True,
                    )
                ),
                name="acct_own_asg_subj_assign_ck",
            ),
        ]


class AccountOwnerAssignmentEvidenceModel(AccountOwnerAssignmentAppendOnlyModel):
    """One immutable approved evidence record in a logical assignment chain."""

    subject = models.OneToOneField(
        AccountOwnerAssignmentSubjectModel,
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
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    underlying_unified_account_namespace = models.CharField(max_length=192)
    underlying_unified_account_id = models.PositiveBigIntegerField()
    assignment_state = models.CharField(max_length=32)
    assigned_owner_user_id = models.PositiveBigIntegerField(null=True)
    row_observation_owner = models.CharField(max_length=32)
    row_observation_artifact_type = models.CharField(max_length=64)
    row_observation_id = models.CharField(max_length=192)
    row_observation_version = models.CharField(max_length=192)
    row_observation_content_hash = models.CharField(max_length=64)
    provenance_kind = models.CharField(max_length=32)
    provenance_ref_owner = models.CharField(max_length=32)
    provenance_ref_artifact_type = models.CharField(max_length=64)
    provenance_ref_id = models.CharField(max_length=192)
    provenance_ref_version = models.CharField(max_length=192)
    provenance_ref_content_hash = models.CharField(max_length=64)
    claimant_actor_id = models.CharField(max_length=192)
    claimant_user_id = models.PositiveBigIntegerField()
    claimant_role = models.CharField(max_length=192)
    claimant_kind = models.CharField(max_length=16)
    claimant_is_staff = models.BooleanField()
    approved_actor_id = models.CharField(max_length=192)
    approved_user_id = models.PositiveBigIntegerField()
    approved_role = models.CharField(max_length=192)
    approved_kind = models.CharField(max_length=16)
    approved_is_staff = models.BooleanField()
    issued_at = models.DateTimeField()
    approved_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField()
    supersedes_content_hash = models.CharField(max_length=64, null=True)
    root_claim_hash = models.CharField(max_length=64, null=True)
    permission = models.CharField(max_length=32)
    status = models.CharField(max_length=16)
    blocker_codes = models.JSONField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta(AccountOwnerAssignmentAppendOnlyModel.Meta):
        db_table = "account_owner_assignment_evidence"
        indexes = [
            models.Index(
                fields=(
                    "account_namespace",
                    "account_id",
                    "row_observation_id",
                    "recorded_at",
                ),
                name="acct_own_asg_ev_chain_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("evidence_id", "evidence_version"),
                name="acct_own_asg_ev_id_uq",
            ),
            models.UniqueConstraint(
                fields=("root_claim_hash",),
                condition=models.Q(root_claim_hash__isnull=False),
                name="acct_own_asg_ev_root_uq",
            ),
            models.UniqueConstraint(
                fields=("supersedes_content_hash",),
                condition=models.Q(supersedes_content_hash__isnull=False),
                name="acct_own_asg_ev_next_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="account",
                    artifact_type="account_owner_assignment_evidence",
                    schema="account-owner-assignment-evidence.v1",
                    account_namespace="account",
                    underlying_unified_account_namespace="simulated-account-row",
                    row_observation_owner="simulated_trading",
                    row_observation_artifact_type="unified_account_row_observation",
                    provenance_ref_owner="account",
                    claimant_kind="human",
                    approved_kind="human",
                    approved_is_staff=True,
                    permission="evidence_only",
                    status="inactive",
                ),
                name="acct_own_asg_ev_fixed_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(issued_at__lte=models.F("approved_at"))
                    & models.Q(approved_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at=models.F("persisted_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="acct_own_asg_ev_clock_ck",
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
                name="acct_own_asg_ev_link_ck",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(claimant_actor_id=models.F("approved_actor_id"))
                    & ~models.Q(claimant_user_id=models.F("approved_user_id"))
                ),
                name="acct_own_asg_ev_actor_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        provenance_kind__in=("creation", "manual_reclaim"),
                        assignment_state="authoritative",
                        assigned_owner_user_id=models.F("claimant_user_id"),
                    )
                    | models.Q(
                        provenance_kind="migration",
                        assignment_state="legacy_default",
                        assigned_owner_user_id__isnull=True,
                    )
                ),
                name="acct_own_asg_ev_assign_ck",
            ),
        ]


def _reject_account_owner_assignment_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject Collector, cascade, and protected-parent deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Account owner assignments cannot be deleted.")


for _model in (
    AccountOwnerAssignmentSubjectModel,
    AccountOwnerAssignmentEvidenceModel,
):
    pre_delete.connect(
        _reject_account_owner_assignment_delete,
        sender=_model,
        dispatch_uid=f"reject_{_model._meta.db_table}_delete",
        weak=False,
    )


__all__ = [
    "AccountOwnerAssignmentEvidenceModel",
    "AccountOwnerAssignmentSubjectModel",
]
