"""Append-only ORM ledgers for Research-owned R2 promotion evidence."""

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
_ACTIVE_R2_PROMOTION_UNIT_OF_WORK: ContextVar[object | None] = ContextVar(
    "active_research_r2_promotion_unit_of_work",
    default=None,
)


@dataclass(frozen=True)
class _R2PromotionInsertClaim:
    unit_of_work_token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_R2_PROMOTION_INSERT_CLAIM: ContextVar[_R2PromotionInsertClaim | None] = ContextVar(
    "active_research_r2_promotion_insert_claim",
    default=None,
)


@contextmanager
def _activate_r2_promotion_unit_of_work(token: object) -> Iterator[None]:
    """Activate one private repository transaction token."""

    reset_token = _ACTIVE_R2_PROMOTION_UNIT_OF_WORK.set(token)
    try:
        yield
    finally:
        _ACTIVE_R2_PROMOTION_UNIT_OF_WORK.reset(reset_token)


def _r2_promotion_unit_of_work_is_active(token: object) -> bool:
    return _ACTIVE_R2_PROMOTION_UNIT_OF_WORK.get() is token


@contextmanager
def _claim_r2_promotion_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Authorize exactly one complete append projection."""

    if _ACTIVE_R2_PROMOTION_UNIT_OF_WORK.get() is not token:
        raise ValidationError("R2 promotion insert requires its repository unit of work.")
    claim = _R2PromotionInsertClaim(
        unit_of_work_token=token,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset_token = _ACTIVE_R2_PROMOTION_INSERT_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_R2_PROMOTION_INSERT_CLAIM.reset(reset_token)


class R2PromotionAppendOnlyQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject all bulk insertion shortcuts."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R2 promotion evidence requires exact appends.")


class R2PromotionAppendOnlyManager(AppendOnlyManager[_ModelT]):
    """Expose identical append-only guards through every manager."""

    def get_queryset(self) -> R2PromotionAppendOnlyQuerySet[_ModelT]:
        return R2PromotionAppendOnlyQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R2 promotion evidence requires exact appends.")


class R2PromotionAppendOnlyModel(models.Model):
    """Permit only repository-claimed inserts."""

    objects = R2PromotionAppendOnlyManager()

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
            raise ValidationError("R2 promotion evidence is append-only.")
        self._require_exact_insert_claim()
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
            raise ValidationError("R2 promotion evidence is append-only.")
        self._require_exact_insert_claim()
        super().save_base(
            raw=False,
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def _require_exact_insert_claim(self) -> None:
        claim = _ACTIVE_R2_PROMOTION_INSERT_CLAIM.get()
        if (
            claim is None
            or claim.unit_of_work_token is not _ACTIVE_R2_PROMOTION_UNIT_OF_WORK.get()
            or claim.model_type is not type(self)
            or any(
                getattr(self, field_name) != value for field_name, value in claim.expected_values
            )
        ):
            raise ValidationError(
                "R2 promotion evidence requires an exact repository insert claim."
            )

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("R2 promotion evidence cannot be deleted.")


class R2MarketStructurePromotionPolicyModel(R2PromotionAppendOnlyModel):
    """Immutable owner-approved policy receipt."""

    policy_id = models.CharField(max_length=200)
    policy_version = models.CharField(max_length=100)
    scope_id = models.CharField(max_length=200, db_index=True)
    scope_content_hash = models.CharField(max_length=64)
    registered_at = models.DateTimeField(db_index=True)
    active_from = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    ledger_recorded_at = models.DateTimeField(db_index=True)
    ledger_receipt_hash = models.CharField(max_length=64, unique=True)
    canonical_payload = models.TextField()
    content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    structure_description_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)

    class Meta:
        db_table = "research_r2_ms_promotion_policy"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["policy_id", "policy_version"],
                name="research_r2_ms_policy_identity_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(research_only=True)
                & models.Q(structure_description_only=True)
                & models.Q(must_not_use_for_decision=True)
                & models.Q(must_not_execute=True),
                name="research_r2_ms_policy_safety",
            ),
            models.CheckConstraint(
                condition=models.Q(registered_at__lte=models.F("active_from"))
                & models.Q(active_from__lt=models.F("valid_until")),
                name="research_r2_ms_policy_clocks",
            ),
        ]


class R2MarketStructurePromotionDecisionModel(R2PromotionAppendOnlyModel):
    """Immutable exact promotion decision graph."""

    decision_id = models.CharField(max_length=200)
    decision_version = models.CharField(max_length=100)
    scope_id = models.CharField(max_length=200, db_index=True)
    scope_content_hash = models.CharField(max_length=64)
    policy_id = models.CharField(max_length=200)
    policy_version = models.CharField(max_length=100)
    policy_content_hash = models.CharField(max_length=64)
    evidence_key = models.CharField(max_length=128)
    evidence_version = models.PositiveIntegerField()
    evidence_content_hash = models.CharField(max_length=64)
    authorization_id = models.CharField(max_length=200)
    authorization_version = models.CharField(max_length=100)
    authorization_content_hash = models.CharField(max_length=64, unique=True)
    outcome = models.CharField(max_length=16)
    decided_at = models.DateTimeField(db_index=True)
    semantic_recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    ledger_recorded_at = models.DateTimeField(db_index=True)
    ledger_receipt_hash = models.CharField(max_length=64, unique=True)
    canonical_payload = models.TextField()
    content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    structure_description_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)

    class Meta:
        db_table = "research_r2_ms_promotion_decision"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["decision_id", "decision_version"],
                name="research_r2_ms_decision_identity_unique",
            ),
            models.UniqueConstraint(
                fields=["authorization_id", "authorization_version"],
                name="research_r2_ms_decision_auth_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(research_only=True)
                & models.Q(structure_description_only=True)
                & models.Q(must_not_use_for_decision=True)
                & models.Q(must_not_execute=True),
                name="research_r2_ms_decision_safety",
            ),
            models.CheckConstraint(
                condition=models.Q(decided_at__lte=models.F("semantic_recorded_at"))
                & models.Q(semantic_recorded_at__lt=models.F("valid_until")),
                name="research_r2_ms_decision_clocks",
            ),
        ]


class R2MarketStructurePromotionLifecycleEventModel(R2PromotionAppendOnlyModel):
    """Immutable scope-local lifecycle event and authorization graph."""

    event_id = models.CharField(max_length=200)
    event_version = models.CharField(max_length=100)
    scope_id = models.CharField(max_length=200, db_index=True)
    scope_content_hash = models.CharField(max_length=64)
    stream_id = models.CharField(max_length=300, db_index=True)
    sequence = models.PositiveIntegerField()
    event_type = models.CharField(max_length=16)
    decision_id = models.CharField(max_length=200)
    decision_version = models.CharField(max_length=100)
    decision_content_hash = models.CharField(max_length=64)
    rollback_target_id = models.CharField(max_length=200, blank=True)
    rollback_target_version = models.CharField(max_length=100, blank=True)
    rollback_target_content_hash = models.CharField(max_length=64, blank=True)
    authorization_id = models.CharField(max_length=200)
    authorization_version = models.CharField(max_length=100)
    authorization_content_hash = models.CharField(max_length=64, unique=True)
    previous_event_hash = models.CharField(max_length=64, blank=True)
    occurred_at = models.DateTimeField(db_index=True)
    semantic_recorded_at = models.DateTimeField(db_index=True)
    ledger_recorded_at = models.DateTimeField(db_index=True)
    ledger_receipt_hash = models.CharField(max_length=64, unique=True)
    canonical_payload = models.TextField()
    content_hash = models.CharField(max_length=64, unique=True)

    class Meta:
        db_table = "research_r2_ms_promotion_lifecycle"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["event_id", "event_version"],
                name="research_r2_ms_event_identity_unique",
            ),
            models.UniqueConstraint(
                fields=["stream_id", "sequence"],
                name="research_r2_ms_event_sequence_unique",
            ),
            models.UniqueConstraint(
                fields=["authorization_id", "authorization_version"],
                name="research_r2_ms_event_auth_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(occurred_at__lte=models.F("semantic_recorded_at")),
                name="research_r2_ms_event_clocks",
            ),
        ]


__all__ = [
    "R2MarketStructurePromotionDecisionModel",
    "R2MarketStructurePromotionLifecycleEventModel",
    "R2MarketStructurePromotionPolicyModel",
    "_activate_r2_promotion_unit_of_work",
    "_claim_r2_promotion_insert",
    "_r2_promotion_unit_of_work_is_active",
]
