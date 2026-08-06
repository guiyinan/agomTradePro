"""Research-owned append-only ORM ledgers for exact R4 promotion."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_R4_PROMOTION_UNIT_OF_WORK: ContextVar[object | None] = ContextVar(
    "active_r4_promotion_model_unit_of_work",
    default=None,
)
_ACTIVE_R4_PROMOTION_INSERT_CLAIM: ContextVar[_R4PromotionInsertClaim | None]


@dataclass(frozen=True)
class _R4PromotionInsertClaim:
    unit_of_work_token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_R4_PROMOTION_INSERT_CLAIM = ContextVar(
    "active_r4_promotion_insert_claim",
    default=None,
)


@contextmanager
def _activate_r4_promotion_unit_of_work(token: object) -> Iterator[None]:
    reset_token = _ACTIVE_R4_PROMOTION_UNIT_OF_WORK.set(token)
    try:
        yield
    finally:
        _ACTIVE_R4_PROMOTION_UNIT_OF_WORK.reset(reset_token)


def _r4_promotion_unit_of_work_is_active(token: object) -> bool:
    return _ACTIVE_R4_PROMOTION_UNIT_OF_WORK.get() is token


@contextmanager
def _claim_r4_promotion_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    if _ACTIVE_R4_PROMOTION_UNIT_OF_WORK.get() is not token:
        raise ValidationError("R4 promotion insert claim requires its repository unit of work.")
    claim = _R4PromotionInsertClaim(
        unit_of_work_token=token,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items())),
    )
    reset_token = _ACTIVE_R4_PROMOTION_INSERT_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_R4_PROMOTION_INSERT_CLAIM.reset(reset_token)


class R4PromotionAppendOnlyQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject every bulk insertion shortcut for exact R4 evidence."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject normal, ignore-conflict and update-conflict bulk inserts."""

        raise ValidationError("R4 promotion evidence requires exact append operations.")


class R4PromotionAppendOnlyManager(AppendOnlyManager[_ModelT]):
    """Expose the same R4 guard through every manager path."""

    def get_queryset(self) -> R4PromotionAppendOnlyQuerySet[_ModelT]:
        """Return the R4 promotion-specific guarded QuerySet."""

        return R4PromotionAppendOnlyQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject manager-level bulk inserts and both conflict modes."""

        raise ValidationError("R4 promotion evidence requires exact append operations.")


class R4PromotionAppendOnlyModel(models.Model):
    """Permit only database-assigned primary-key inserts."""

    objects = R4PromotionAppendOnlyManager()

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
        """Reject updates and caller-supplied primary keys, including zero."""

        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("R4 promotion evidence is append-only.")
        claim = _ACTIVE_R4_PROMOTION_INSERT_CLAIM.get()
        if (
            claim is None
            or claim.unit_of_work_token is not _ACTIVE_R4_PROMOTION_UNIT_OF_WORK.get()
            or claim.model_type is not type(self)
            or any(
                getattr(self, field_name) != value for field_name, value in claim.expected_values
            )
        ):
            raise ValidationError(
                "R4 promotion evidence requires an exact repository insert claim."
            )
        super().save(force_insert=force_insert, using=using)

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("R4 promotion evidence cannot be deleted.")


class R4PromotionPolicyModel(R4PromotionAppendOnlyModel):
    """Canonical pre-registered Research R4 promotion policy."""

    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    owner = models.CharField(max_length=32)
    capability = models.CharField(max_length=32)
    purpose = models.CharField(max_length=64)
    status = models.CharField(max_length=32)
    scope_id = models.CharField(max_length=192, db_index=True)
    scope_content_hash = models.CharField(max_length=64)
    study_family_id = models.CharField(max_length=192)
    target_method = models.CharField(max_length=64)
    universe_policy_id = models.CharField(max_length=192)
    factor_policy_id = models.CharField(max_length=192)
    split_policy_id = models.CharField(max_length=192)
    cost_semantics_id = models.CharField(max_length=192)
    approved_at = models.DateTimeField()
    recorded_at = models.DateTimeField()
    active_from = models.DateTimeField(db_index=True)
    active_until = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_r4_promotion_policy"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["policy_id", "policy_version"],
                name="res_r4_pol_identity_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="research",
                    capability="r4",
                    purpose="macro_risk_method_research",
                ),
                name="res_r4_pol_authority_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(approved_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lte=models.F("active_from"))
                    & models.Q(active_from__lt=models.F("active_until"))
                ),
                name="res_r4_pol_time_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r4_pol_research_ck",
            ),
        ]


class R4PromotionDecisionReceiptModel(R4PromotionAppendOnlyModel):
    """Stable server claim for one exact R4 decision identity."""

    receipt_id = models.CharField(max_length=192)
    receipt_version = models.CharField(max_length=192)
    decision_id = models.CharField(max_length=192)
    decision_version = models.CharField(max_length=192)
    trial_id = models.CharField(max_length=192)
    trial_version = models.CharField(max_length=192)
    policy = models.ForeignKey(
        R4PromotionPolicyModel,
        on_delete=models.PROTECT,
        related_name="decision_receipts",
    )
    policy_content_hash = models.CharField(max_length=64)
    portfolio_record_id = models.CharField(max_length=192)
    portfolio_record_hash = models.CharField(max_length=64)
    portfolio_owner_record_key = models.CharField(max_length=192)
    portfolio_recorded_at = models.DateTimeField()
    current_r3_content_hash = models.CharField(max_length=64)
    owner = models.CharField(max_length=32)
    capability = models.CharField(max_length=32)
    purpose = models.CharField(max_length=64)
    decided_at = models.DateTimeField()
    recorded_at = models.DateTimeField()
    decision_valid_until = models.DateTimeField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_r4_promotion_decision_receipt"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["receipt_id", "receipt_version"],
                name="res_r4_dr_identity_uq",
            ),
            models.UniqueConstraint(
                fields=["decision_id", "decision_version"],
                name="res_r4_dr_decision_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="research",
                    capability="r4",
                    purpose="macro_risk_method_research",
                ),
                name="res_r4_dr_authority_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(portfolio_recorded_at__lte=models.F("decided_at"))
                    & models.Q(decided_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("decision_valid_until"))
                ),
                name="res_r4_dr_time_ck",
            ),
        ]


class R4PromotionDecisionBundleModel(R4PromotionAppendOnlyModel):
    """Atomic R4 decision plus its preclaimed Research receipt."""

    receipt = models.OneToOneField(
        R4PromotionDecisionReceiptModel,
        on_delete=models.PROTECT,
        related_name="decision_bundle",
    )
    policy = models.ForeignKey(
        R4PromotionPolicyModel,
        on_delete=models.PROTECT,
        related_name="decision_bundles",
    )
    decision_id = models.CharField(max_length=192)
    decision_version = models.CharField(max_length=192)
    trial_id = models.CharField(max_length=192)
    trial_version = models.CharField(max_length=192)
    trial_content_hash = models.CharField(max_length=64)
    policy_content_hash = models.CharField(max_length=64)
    portfolio_record_id = models.CharField(max_length=192)
    portfolio_record_hash = models.CharField(max_length=64)
    portfolio_owner_record_key = models.CharField(max_length=192)
    current_r3_content_hash = models.CharField(max_length=64)
    owner = models.CharField(max_length=32)
    capability = models.CharField(max_length=32)
    purpose = models.CharField(max_length=64)
    scope_id = models.CharField(max_length=192, db_index=True)
    scope_content_hash = models.CharField(max_length=64)
    outcome = models.CharField(max_length=32)
    decided_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    decision_content_hash = models.CharField(max_length=64, unique=True)
    bundle_content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_r4_promotion_decision_bundle"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["decision_id", "decision_version"],
                name="res_r4_db_identity_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="research",
                    capability="r4",
                    purpose="macro_risk_method_research",
                ),
                name="res_r4_db_authority_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(decided_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="res_r4_db_time_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r4_db_research_ck",
            ),
        ]


class R4PromotionLifecycleAuthorizationReceiptModel(R4PromotionAppendOnlyModel):
    """Stable Research authorization and server event-clock receipt."""

    authorization_id = models.CharField(max_length=192)
    authorization_version = models.CharField(max_length=192)
    event_id = models.CharField(max_length=192)
    event_version = models.CharField(max_length=192)
    decision = models.ForeignKey(
        R4PromotionDecisionBundleModel,
        on_delete=models.PROTECT,
        related_name="lifecycle_authorization_receipts",
    )
    rollback_target = models.ForeignKey(
        R4PromotionDecisionBundleModel,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rollback_target_authorization_receipts",
    )
    decision_content_hash = models.CharField(max_length=64)
    rollback_target_content_hash = models.CharField(max_length=64, blank=True, default="")
    owner = models.CharField(max_length=32)
    capability = models.CharField(max_length=32)
    purpose = models.CharField(max_length=64)
    scope_id = models.CharField(max_length=192, db_index=True)
    scope_content_hash = models.CharField(max_length=64)
    event_type = models.CharField(max_length=32)
    reason_codes = models.JSONField()
    reason_hash = models.CharField(max_length=64)
    authorization_issued_at = models.DateTimeField()
    authorization_recorded_at = models.DateTimeField()
    authorization_valid_until = models.DateTimeField()
    occurred_at = models.DateTimeField()
    event_recorded_at = models.DateTimeField()
    authorization_content_hash = models.CharField(max_length=64, unique=True)
    evidence_content_hash = models.CharField(max_length=64, unique=True)
    canonical_payload = models.JSONField()
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_r4_promotion_lifecycle_auth_receipt"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["authorization_id", "authorization_version"],
                name="res_r4_lr_auth_identity_uq",
            ),
            models.UniqueConstraint(
                fields=["event_id", "event_version"],
                name="res_r4_lr_event_identity_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="research",
                    capability="r4",
                    purpose="macro_risk_method_research",
                ),
                name="res_r4_lr_authority_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(authorization_issued_at__lte=models.F("authorization_recorded_at"))
                    & models.Q(authorization_recorded_at__lte=models.F("occurred_at"))
                    & models.Q(occurred_at__lte=models.F("event_recorded_at"))
                    & models.Q(occurred_at__lt=models.F("authorization_valid_until"))
                ),
                name="res_r4_lr_time_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(event_type="rolled_back", rollback_target__isnull=False)
                    | (~models.Q(event_type="rolled_back") & models.Q(rollback_target__isnull=True))
                ),
                name="res_r4_lr_target_ck",
            ),
        ]


class R4PromotionLifecycleEventModel(R4PromotionAppendOnlyModel):
    """Immutable scope-local R4 lifecycle event and hash-chain bundle."""

    receipt = models.OneToOneField(
        R4PromotionLifecycleAuthorizationReceiptModel,
        on_delete=models.PROTECT,
        related_name="lifecycle_event",
    )
    decision = models.ForeignKey(
        R4PromotionDecisionBundleModel,
        on_delete=models.PROTECT,
        related_name="lifecycle_events",
    )
    rollback_target = models.ForeignKey(
        R4PromotionDecisionBundleModel,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rollback_target_lifecycle_events",
    )
    previous_event = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="next_events",
    )
    decision_content_hash = models.CharField(max_length=64)
    rollback_target_content_hash = models.CharField(max_length=64, blank=True, default="")
    event_id = models.CharField(max_length=192)
    event_version = models.CharField(max_length=192)
    scope_id = models.CharField(max_length=192, db_index=True)
    scope_content_hash = models.CharField(max_length=64)
    stream_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=32)
    sequence = models.PositiveIntegerField()
    reason_codes = models.JSONField()
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    previous_event_hash = models.CharField(max_length=64, blank=True, default="")
    event_content_hash = models.CharField(max_length=64, unique=True)
    bundle_content_hash = models.CharField(max_length=64, unique=True)
    canonical_payload = models.JSONField()
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_r4_promotion_lifecycle_event"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["stream_id", "sequence"]
        indexes = [
            models.Index(
                fields=["stream_id", "recorded_at"],
                name="res_r4_le_stream_rec_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["event_id", "event_version"],
                name="res_r4_le_identity_uq",
            ),
            models.UniqueConstraint(
                fields=["stream_id", "sequence"],
                name="res_r4_le_stream_seq_uq",
            ),
            models.UniqueConstraint(
                fields=["stream_id", "previous_event"],
                condition=models.Q(previous_event__isnull=False),
                name="res_r4_le_previous_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(recorded_at__gte=models.F("occurred_at")),
                name="res_r4_le_time_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        sequence=1,
                        event_type="promoted",
                        previous_event__isnull=True,
                        previous_event_hash="",
                    )
                    | (
                        models.Q(sequence__gt=1, previous_event__isnull=False)
                        & ~models.Q(previous_event_hash="")
                    )
                ),
                name="res_r4_le_link_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(event_type="rolled_back", rollback_target__isnull=False)
                    | (~models.Q(event_type="rolled_back") & models.Q(rollback_target__isnull=True))
                ),
                name="res_r4_le_target_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r4_le_research_ck",
            ),
        ]


__all__ = [
    "R4PromotionAppendOnlyManager",
    "R4PromotionAppendOnlyModel",
    "R4PromotionAppendOnlyQuerySet",
    "R4PromotionDecisionBundleModel",
    "R4PromotionDecisionReceiptModel",
    "R4PromotionLifecycleAuthorizationReceiptModel",
    "R4PromotionLifecycleEventModel",
    "R4PromotionPolicyModel",
]
