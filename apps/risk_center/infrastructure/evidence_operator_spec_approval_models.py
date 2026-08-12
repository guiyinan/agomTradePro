"""Append-only Risk Center ledgers for Evidence operator spec approvals."""

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
_ACTIVE_APPROVAL_UOW: ContextVar[object | None] = ContextVar(
    "active_risk_center_evidence_operator_spec_approval_uow",
    default=None,
)


@dataclass(frozen=True)
class _ApprovalInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_APPROVAL_CLAIM: ContextVar[_ApprovalInsertClaim | None] = ContextVar(
    "active_risk_center_evidence_operator_spec_approval_claim",
    default=None,
)


@contextmanager
def _activate_evidence_operator_spec_approval_uow(token: object) -> Iterator[None]:
    reset = _ACTIVE_APPROVAL_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_APPROVAL_UOW.reset(reset)


@contextmanager
def _claim_evidence_operator_spec_approval_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    if _ACTIVE_APPROVAL_UOW.get() is not token:
        raise ValidationError("Risk Center approval insert requires its private unit of work.")
    reset = _ACTIVE_APPROVAL_CLAIM.set(
        _ApprovalInsertClaim(
            token=token,
            model_type=model_type,
            expected_values=tuple(sorted(expected_values.items())),
        )
    )
    try:
        yield
    finally:
        _ACTIVE_APPROVAL_CLAIM.reset(reset)


class EvidenceOperatorSpecApprovalQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject every bulk, conflict-update, private-update, and raw-delete shortcut."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Risk Center approvals require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Risk Center approvals cannot be updated.")

    def _raw_delete(self, using: str) -> NoReturn:
        raise ValidationError("Risk Center approvals cannot be deleted.")


class EvidenceOperatorSpecApprovalManager(AppendOnlyManager[_ModelT]):
    """Expose the strict approval guards through every manager path."""

    def get_queryset(self) -> EvidenceOperatorSpecApprovalQuerySet[_ModelT]:
        return EvidenceOperatorSpecApprovalQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Risk Center approvals require exact repository appends.")


class EvidenceOperatorSpecApprovalAppendOnlyModel(models.Model):
    """Permit only a repository-claimed insert with a database-assigned key."""

    objects: EvidenceOperatorSpecApprovalManager[models.Model] = (
        EvidenceOperatorSpecApprovalManager()
    )

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
            raise ValidationError("Risk Center approvals are append-only.")
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
            raise ValidationError("Risk Center approvals are append-only.")
        self._require_claim()
        super().save_base(
            raw=False,
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def _require_claim(self) -> None:
        claim = _ACTIVE_APPROVAL_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_APPROVAL_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Risk Center approval requires an exact insert claim.")

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("Risk Center approvals cannot be deleted.")


class EvidenceOperatorSpecApprovalSubjectModel(EvidenceOperatorSpecApprovalAppendOnlyModel):
    """One immutable external-definition approval subject first winner."""

    subject_id = models.CharField(max_length=192)
    subject_version = models.CharField(max_length=192)
    subject_identity_hash = models.CharField(max_length=64, unique=True)
    operator_id = models.CharField(max_length=192)
    operator_version = models.CharField(max_length=192)
    definition_hash = models.CharField(max_length=64, unique=True)
    supersedes_activation_hash = models.CharField(max_length=64, null=True)
    requested_actor_id = models.CharField(max_length=192)
    requested_actor_kind = models.CharField(max_length=16)
    requested_actor_is_staff = models.BooleanField()
    requested_actor_user_id = models.PositiveBigIntegerField(null=True)
    requested_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(EvidenceOperatorSpecApprovalAppendOnlyModel.Meta):
        db_table = "risk_center_evidence_operator_spec_subject"
        indexes = [
            models.Index(
                fields=("operator_id", "operator_version", "recorded_at"),
                name="risk_ev_op_subj_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("subject_id", "subject_version"),
                name="risk_ev_op_subj_identity_uq",
            ),
            models.UniqueConstraint(
                fields=("operator_id", "operator_version"),
                name="risk_ev_op_subj_operator_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(requested_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="risk_ev_op_subj_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        requested_actor_kind="human",
                        requested_actor_user_id__isnull=False,
                    )
                    | models.Q(
                        requested_actor_kind__in=("ai", "service"),
                        requested_actor_is_staff=False,
                        requested_actor_user_id__isnull=True,
                    )
                ),
                name="risk_ev_op_subj_actor_ck",
            ),
        ]


class EvidenceOperatorSpecApprovalRecordModel(EvidenceOperatorSpecApprovalAppendOnlyModel):
    """One immutable human-staff approval for one exact subject."""

    subject = models.OneToOneField(
        EvidenceOperatorSpecApprovalSubjectModel,
        on_delete=models.PROTECT,
        related_name="approval_record",
    )
    owner = models.CharField(max_length=32)
    capability = models.CharField(max_length=64)
    approval_id = models.CharField(max_length=192)
    approval_version = models.CharField(max_length=192)
    approval_identity_hash = models.CharField(max_length=64, unique=True)
    subject_hash = models.CharField(max_length=64, unique=True)
    operator_id = models.CharField(max_length=192)
    operator_version = models.CharField(max_length=192)
    definition_hash = models.CharField(max_length=64, unique=True)
    supersedes_activation_hash = models.CharField(max_length=64, null=True)
    approved_actor_id = models.CharField(max_length=192)
    approved_actor_kind = models.CharField(max_length=16)
    approved_actor_is_staff = models.BooleanField()
    approved_actor_user_id = models.PositiveBigIntegerField()
    issued_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(EvidenceOperatorSpecApprovalAppendOnlyModel.Meta):
        db_table = "risk_center_evidence_operator_spec_approval"
        indexes = [
            models.Index(
                fields=("operator_id", "operator_version", "recorded_at"),
                name="risk_ev_op_appr_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("approval_id", "approval_version"),
                name="risk_ev_op_appr_identity_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(owner="risk_center")
                    & models.Q(capability="evidence_operator_spec_activation")
                ),
                name="risk_ev_op_appr_owner_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(issued_at=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="risk_ev_op_appr_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    approved_actor_kind="human",
                    approved_actor_is_staff=True,
                    approved_actor_user_id__isnull=False,
                ),
                name="risk_ev_op_appr_actor_ck",
            ),
        ]


def _reject_evidence_operator_spec_approval_pre_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("Risk Center approvals cannot be deleted.")


for _model in (
    EvidenceOperatorSpecApprovalSubjectModel,
    EvidenceOperatorSpecApprovalRecordModel,
):
    pre_delete.connect(
        _reject_evidence_operator_spec_approval_pre_delete,
        sender=_model,
        dispatch_uid=f"reject_{_model._meta.db_table}_delete",
        weak=False,
    )


__all__ = [
    "EvidenceOperatorSpecApprovalRecordModel",
    "EvidenceOperatorSpecApprovalSubjectModel",
]
