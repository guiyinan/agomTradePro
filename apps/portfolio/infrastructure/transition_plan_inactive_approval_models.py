"""Append-only ledgers for inactive transition-plan approvals."""

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

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_TRANSITION_APPROVAL_UOW: ContextVar[object | None] = ContextVar(
    "active_portfolio_transition_inactive_approval_uow", default=None
)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_TRANSITION_APPROVAL_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_portfolio_transition_inactive_approval_claim", default=None
)


@contextmanager
def _activate_transition_plan_inactive_approval_uow(token: object) -> Iterator[None]:
    """Activate this ledger's private unit-of-work token."""

    reset = _ACTIVE_TRANSITION_APPROVAL_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_TRANSITION_APPROVAL_UOW.reset(reset)


@contextmanager
def _claim_transition_plan_inactive_approval_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact repository-controlled insert."""

    if _ACTIVE_TRANSITION_APPROVAL_UOW.get() is not token:
        raise ValidationError("Transition approval insert requires its private UOW.")
    reset = _ACTIVE_TRANSITION_APPROVAL_CLAIM.set(
        _InsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_TRANSITION_APPROVAL_CLAIM.reset(reset)


class TransitionPlanInactiveApprovalQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject every mutation, delete, and bulk insertion shortcut."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Transition approvals require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Transition approvals cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("Transition approvals cannot be deleted.")


class TransitionPlanInactiveApprovalManager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> TransitionPlanInactiveApprovalQuerySet[_ModelT]:
        return TransitionPlanInactiveApprovalQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Transition approvals require exact repository appends.")


class TransitionPlanInactiveApprovalAppendOnlyModel(models.Model):
    """Permit only exact, repository-claimed inserts."""

    objects: TransitionPlanInactiveApprovalManager[Self] = TransitionPlanInactiveApprovalManager()

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
            raise ValidationError("Transition approvals are append-only.")
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
            raise ValidationError("Transition approvals are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_TRANSITION_APPROVAL_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_TRANSITION_APPROVAL_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Transition approval requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("Transition approvals cannot be deleted.")


class TransitionPlanInactiveApprovalSubjectModel(TransitionPlanInactiveApprovalAppendOnlyModel):
    """One immutable exact-plan subject first winner."""

    subject_id = models.CharField(max_length=192)
    subject_version = models.CharField(max_length=192)
    subject_identity_hash = models.CharField(max_length=64, unique=True)
    plan_id = models.CharField(max_length=64)
    plan_version = models.PositiveIntegerField()
    plan_content_hash = models.CharField(max_length=64)
    account_id = models.CharField(max_length=64)
    decision_snapshot_id = models.CharField(max_length=64)
    requested_actor_id = models.CharField(max_length=192)
    requested_actor_user_id = models.PositiveBigIntegerField()
    requested_actor_role = models.CharField(max_length=192)
    requested_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta(TransitionPlanInactiveApprovalAppendOnlyModel.Meta):
        db_table = "portfolio_transition_inactive_approval_subject"
        indexes = [
            models.Index(
                fields=("plan_id", "plan_version", "recorded_at"),
                name="portfolio_tr_ap_subj_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("subject_id", "subject_version"),
                name="portfolio_tr_ap_subj_id_uq",
            ),
            models.UniqueConstraint(
                fields=("plan_id", "plan_version"),
                name="portfolio_tr_ap_subj_plan_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(recorded_at__lt=models.F("valid_until"))
                    & models.Q(requested_at=models.F("recorded_at"))
                ),
                name="portfolio_tr_ap_subj_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(persisted_at=models.F("recorded_at")),
                name="portfolio_tr_ap_subj_persist_ck",
            ),
        ]


class TransitionPlanInactiveApprovalReceiptModel(TransitionPlanInactiveApprovalAppendOnlyModel):
    """One immutable inactive receipt for one registered subject."""

    subject_record = models.OneToOneField(
        TransitionPlanInactiveApprovalSubjectModel,
        on_delete=models.PROTECT,
        related_name="approval_receipt",
    )
    owner = models.CharField(max_length=32)
    schema = models.CharField(max_length=96)
    receipt_id = models.CharField(max_length=192)
    receipt_version = models.CharField(max_length=192)
    receipt_identity_hash = models.CharField(max_length=64, unique=True)
    subject_hash = models.CharField(max_length=64, unique=True)
    subject_id = models.CharField(max_length=192)
    subject_version = models.CharField(max_length=192)
    subject_content_hash = models.CharField(max_length=64)
    plan_id = models.CharField(max_length=64)
    plan_version = models.PositiveIntegerField()
    plan_content_hash = models.CharField(max_length=64)
    account_id = models.CharField(max_length=64)
    decision_snapshot_id = models.CharField(max_length=64)
    requested_actor_id = models.CharField(max_length=192)
    requested_actor_user_id = models.PositiveBigIntegerField()
    requested_actor_role = models.CharField(max_length=192)
    approved_actor_id = models.CharField(max_length=192)
    approved_actor_user_id = models.PositiveBigIntegerField()
    approved_actor_role = models.CharField(max_length=192)
    plan_status_at_issue = models.CharField(max_length=16)
    issued_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField()

    class Meta(TransitionPlanInactiveApprovalAppendOnlyModel.Meta):
        db_table = "portfolio_transition_inactive_approval_receipt"
        indexes = [
            models.Index(
                fields=("plan_id", "plan_version", "recorded_at"),
                name="portfolio_tr_ap_rcpt_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("receipt_id", "receipt_version"),
                name="portfolio_tr_ap_rcpt_id_uq",
            ),
            models.UniqueConstraint(
                fields=("plan_id", "plan_version"),
                name="portfolio_tr_ap_rcpt_plan_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(owner="portfolio")
                    & models.Q(plan_status_at_issue="APPROVED")
                    & models.Q(schema="portfolio-transition-plan-approval-receipt.v1")
                ),
                name="portfolio_tr_ap_rcpt_owner_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(issued_at=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="portfolio_tr_ap_rcpt_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(persisted_at=models.F("recorded_at")),
                name="portfolio_tr_ap_rcpt_persist_ck",
            ),
        ]


def _reject_transition_plan_inactive_approval_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject collector and cascade deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Transition approvals cannot be deleted.")


for _model in (
    TransitionPlanInactiveApprovalSubjectModel,
    TransitionPlanInactiveApprovalReceiptModel,
):
    pre_delete.connect(
        _reject_transition_plan_inactive_approval_delete,
        sender=_model,
        dispatch_uid=f"reject_{_model._meta.db_table}_delete",
        weak=False,
    )


__all__ = [
    "TransitionPlanInactiveApprovalReceiptModel",
    "TransitionPlanInactiveApprovalSubjectModel",
]
