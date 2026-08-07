"""Append-only ORM ledgers for Research-owned R5 promotion evidence."""

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
_ACTIVE_R5_PROMOTION_UNIT_OF_WORK: ContextVar[object | None] = ContextVar(
    "active_research_r5_promotion_unit_of_work",
    default=None,
)


@dataclass(frozen=True)
class _R5PromotionInsertClaim:
    unit_of_work_token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_R5_PROMOTION_INSERT_CLAIM: ContextVar[_R5PromotionInsertClaim | None] = ContextVar(
    "active_research_r5_promotion_insert_claim",
    default=None,
)


@contextmanager
def _activate_r5_promotion_unit_of_work(token: object) -> Iterator[None]:
    """Activate one private repository transaction token."""

    reset_token = _ACTIVE_R5_PROMOTION_UNIT_OF_WORK.set(token)
    try:
        yield
    finally:
        _ACTIVE_R5_PROMOTION_UNIT_OF_WORK.reset(reset_token)


def _r5_promotion_unit_of_work_is_active(token: object) -> bool:
    return _ACTIVE_R5_PROMOTION_UNIT_OF_WORK.get() is token


@contextmanager
def _claim_r5_promotion_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Authorize exactly one model type and complete value projection."""

    if _ACTIVE_R5_PROMOTION_UNIT_OF_WORK.get() is not token:
        raise ValidationError("R5 promotion insert requires its repository unit of work.")
    claim = _R5PromotionInsertClaim(
        unit_of_work_token=token,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset_token = _ACTIVE_R5_PROMOTION_INSERT_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_R5_PROMOTION_INSERT_CLAIM.reset(reset_token)


class R5PromotionAppendOnlyQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject every bulk insertion shortcut for R5 promotion evidence."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject normal and conflict-aware bulk inserts."""

        raise ValidationError("R5 promotion evidence requires exact appends.")


class R5PromotionAppendOnlyManager(AppendOnlyManager[_ModelT]):
    """Expose identical guards through default and base managers."""

    def get_queryset(self) -> R5PromotionAppendOnlyQuerySet[_ModelT]:
        """Return the R5-specific guarded QuerySet."""

        return R5PromotionAppendOnlyQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject manager-level bulk inserts."""

        raise ValidationError("R5 promotion evidence requires exact appends.")


class R5PromotionAppendOnlyModel(models.Model):
    """Permit only claimed inserts with database-assigned primary keys."""

    objects = R5PromotionAppendOnlyManager()

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
        """Reject unclaimed inserts and every update path."""

        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("R5 promotion evidence is append-only.")
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
        """Guard direct and fixture/raw ``save_base`` bypasses."""

        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("R5 promotion evidence is append-only.")
        self._require_exact_insert_claim()
        super().save_base(
            raw=False,
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def _require_exact_insert_claim(self) -> None:
        claim = _ACTIVE_R5_PROMOTION_INSERT_CLAIM.get()
        if (
            claim is None
            or claim.unit_of_work_token is not _ACTIVE_R5_PROMOTION_UNIT_OF_WORK.get()
            or claim.model_type is not type(self)
            or any(
                getattr(self, field_name) != value for field_name, value in claim.expected_values
            )
        ):
            raise ValidationError(
                "R5 promotion evidence requires an exact repository insert claim."
            )

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("R5 promotion evidence cannot be deleted.")


class R5PromotionArtifactModel(R5PromotionAppendOnlyModel):
    """Typed immutable ledger shared only by exact policy and trial artifacts."""

    artifact_kind = models.CharField(max_length=16)
    stable_id = models.CharField(max_length=300)
    version = models.CharField(max_length=300)
    owner = models.CharField(max_length=32)
    capability = models.CharField(max_length=32)
    purpose = models.CharField(max_length=96)
    scope_id = models.CharField(max_length=300, db_index=True)
    scope_content_hash = models.CharField(max_length=64)
    semantic_recorded_at = models.DateTimeField(db_index=True)
    active_from = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    ledger_recorded_at = models.DateTimeField(db_index=True)
    ledger_receipt_hash = models.CharField(max_length=64, unique=True)
    command_hash = models.CharField(max_length=64)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)

    class Meta:
        db_table = "research_r5_promotion_artifact"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["artifact_kind", "stable_id", "version"],
                name="res_r5_art_identity_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(artifact_kind__in=["policy", "trial"]),
                name="res_r5_art_kind_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="research",
                    capability="r5",
                    purpose="fixed_income_relative_value_research",
                ),
                name="res_r5_art_authority_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(semantic_recorded_at__lte=models.F("active_from"))
                    & models.Q(active_from__lt=models.F("valid_until"))
                ),
                name="res_r5_art_time_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r5_art_research_ck",
            ),
        ]


class R5PromotionDecisionAuthorizationModel(R5PromotionAppendOnlyModel):
    """Exact Research authorization receipt persisted with its child decision."""

    authorization_id = models.CharField(max_length=300)
    authorization_version = models.CharField(max_length=300)
    policy = models.ForeignKey(
        R5PromotionArtifactModel,
        on_delete=models.PROTECT,
        related_name="r5_decision_policy_authorizations",
    )
    trial = models.ForeignKey(
        R5PromotionArtifactModel,
        on_delete=models.PROTECT,
        related_name="r5_decision_trial_authorizations",
    )
    owner = models.CharField(max_length=32)
    capability = models.CharField(max_length=32)
    purpose = models.CharField(max_length=96)
    scope_id = models.CharField(max_length=300, db_index=True)
    scope_content_hash = models.CharField(max_length=64)
    issued_at = models.DateTimeField()
    recorded_at = models.DateTimeField()
    decided_at = models.DateTimeField()
    decision_recorded_at = models.DateTimeField()
    decision_valid_until = models.DateTimeField()
    valid_until = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    ledger_receipt_hash = models.CharField(max_length=64, unique=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)

    class Meta:
        db_table = "research_r5_promotion_decision_auth"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["authorization_id", "authorization_version"],
                name="res_r5_da_identity_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="research",
                    capability="r5",
                    purpose="fixed_income_relative_value_research",
                ),
                name="res_r5_da_authority_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(issued_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lte=models.F("decided_at"))
                    & models.Q(decided_at__lte=models.F("decision_recorded_at"))
                    & models.Q(decision_recorded_at__lt=models.F("decision_valid_until"))
                    & models.Q(decision_valid_until__lte=models.F("valid_until"))
                ),
                name="res_r5_da_time_ck",
            ),
        ]


class R5PromotionDecisionBundleModel(R5PromotionAppendOnlyModel):
    """Derived decision child bound one-to-one to its exact authorization."""

    authorization = models.OneToOneField(
        R5PromotionDecisionAuthorizationModel,
        on_delete=models.PROTECT,
        related_name="decision_bundle",
    )
    policy = models.ForeignKey(
        R5PromotionArtifactModel,
        on_delete=models.PROTECT,
        related_name="r5_policy_decision_bundles",
    )
    trial = models.ForeignKey(
        R5PromotionArtifactModel,
        on_delete=models.PROTECT,
        related_name="r5_trial_decision_bundles",
    )
    decision_id = models.CharField(max_length=300)
    decision_version = models.CharField(max_length=300)
    owner = models.CharField(max_length=32)
    capability = models.CharField(max_length=32)
    purpose = models.CharField(max_length=96)
    scope_id = models.CharField(max_length=300, db_index=True)
    scope_content_hash = models.CharField(max_length=64)
    outcome = models.CharField(max_length=32)
    decided_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    ledger_recorded_at = models.DateTimeField(db_index=True)
    ledger_receipt_hash = models.CharField(max_length=64, unique=True)
    canonical_payload = models.JSONField()
    decision_content_hash = models.CharField(max_length=64, unique=True)
    bundle_content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)

    class Meta:
        db_table = "research_r5_promotion_decision_bundle"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["decision_id", "decision_version"],
                name="res_r5_db_identity_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="research",
                    capability="r5",
                    purpose="fixed_income_relative_value_research",
                ),
                name="res_r5_db_authority_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(decided_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="res_r5_db_time_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r5_db_research_ck",
            ),
        ]


class R5PromotionLifecycleAuthorizationModel(R5PromotionAppendOnlyModel):
    """Exact lifecycle authorization evidence persisted with its event child."""

    evidence_id = models.CharField(max_length=300)
    evidence_version = models.CharField(max_length=300)
    authorization_id = models.CharField(max_length=300)
    authorization_version = models.CharField(max_length=300)
    decision = models.ForeignKey(
        R5PromotionDecisionBundleModel,
        on_delete=models.PROTECT,
        related_name="r5_lifecycle_authorizations",
    )
    rollback_target = models.ForeignKey(
        R5PromotionDecisionBundleModel,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="r5_rollback_target_authorizations",
    )
    scope_id = models.CharField(max_length=300, db_index=True)
    scope_content_hash = models.CharField(max_length=64)
    event_id = models.CharField(max_length=300)
    event_version = models.CharField(max_length=300)
    event_type = models.CharField(max_length=32)
    reason_codes = models.JSONField()
    reason_hash = models.CharField(max_length=64)
    authorization_issued_at = models.DateTimeField()
    authorization_recorded_at = models.DateTimeField()
    authorization_valid_until = models.DateTimeField()
    receipt_recorded_at = models.DateTimeField()
    occurred_at = models.DateTimeField()
    event_recorded_at = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    ledger_receipt_hash = models.CharField(max_length=64, unique=True)
    authorization_content_hash = models.CharField(max_length=64, unique=True)
    evidence_content_hash = models.CharField(max_length=64, unique=True)
    event_content_hash = models.CharField(max_length=64, unique=True)
    canonical_payload = models.JSONField()

    class Meta:
        db_table = "research_r5_promotion_lifecycle_auth"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["evidence_id", "evidence_version"],
                name="res_r5_la_evidence_uq",
            ),
            models.UniqueConstraint(
                fields=["authorization_id", "authorization_version"],
                name="res_r5_la_auth_uq",
            ),
            models.UniqueConstraint(
                fields=["event_id", "event_version"],
                name="res_r5_la_event_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        event_type="rolled_back",
                        rollback_target__isnull=False,
                    )
                    | (~models.Q(event_type="rolled_back") & models.Q(rollback_target__isnull=True))
                ),
                name="res_r5_la_target_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(authorization_issued_at__lte=models.F("authorization_recorded_at"))
                    & models.Q(authorization_recorded_at__lte=models.F("receipt_recorded_at"))
                    & models.Q(receipt_recorded_at__lte=models.F("occurred_at"))
                    & models.Q(occurred_at__lte=models.F("event_recorded_at"))
                    & models.Q(occurred_at__lt=models.F("authorization_valid_until"))
                ),
                name="res_r5_la_time_ck",
            ),
        ]


class R5PromotionLifecycleEventModel(R5PromotionAppendOnlyModel):
    """Immutable scope-local lifecycle event and self-linked hash chain."""

    authorization = models.OneToOneField(
        R5PromotionLifecycleAuthorizationModel,
        on_delete=models.PROTECT,
        related_name="lifecycle_event",
    )
    decision = models.ForeignKey(
        R5PromotionDecisionBundleModel,
        on_delete=models.PROTECT,
        related_name="r5_lifecycle_events",
    )
    rollback_target = models.ForeignKey(
        R5PromotionDecisionBundleModel,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="r5_rollback_target_events",
    )
    previous_event = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="next_events",
    )
    event_id = models.CharField(max_length=300)
    event_version = models.CharField(max_length=300)
    scope_id = models.CharField(max_length=300, db_index=True)
    scope_content_hash = models.CharField(max_length=64)
    stream_id = models.CharField(max_length=384)
    event_type = models.CharField(max_length=32)
    sequence = models.PositiveIntegerField()
    reason_codes = models.JSONField()
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    ledger_recorded_at = models.DateTimeField(db_index=True)
    ledger_receipt_hash = models.CharField(max_length=64, unique=True)
    previous_event_hash = models.CharField(max_length=64, blank=True, default="")
    canonical_payload = models.JSONField()
    event_content_hash = models.CharField(max_length=64, unique=True)
    bundle_content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)

    class Meta:
        db_table = "research_r5_promotion_lifecycle_event"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["stream_id", "sequence"]
        indexes = [
            models.Index(
                fields=["stream_id", "recorded_at"],
                name="res_r5_le_stream_rec_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["event_id", "event_version"],
                name="res_r5_le_identity_uq",
            ),
            models.UniqueConstraint(
                fields=["stream_id", "sequence"],
                name="res_r5_le_stream_seq_uq",
            ),
            models.UniqueConstraint(
                fields=["stream_id", "previous_event"],
                condition=models.Q(previous_event__isnull=False),
                name="res_r5_le_previous_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(recorded_at__gte=models.F("occurred_at")),
                name="res_r5_le_time_ck",
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
                name="res_r5_le_link_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        event_type="rolled_back",
                        rollback_target__isnull=False,
                    )
                    | (~models.Q(event_type="rolled_back") & models.Q(rollback_target__isnull=True))
                ),
                name="res_r5_le_target_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r5_le_research_ck",
            ),
        ]


__all__ = [
    "R5PromotionAppendOnlyManager",
    "R5PromotionAppendOnlyModel",
    "R5PromotionAppendOnlyQuerySet",
    "R5PromotionArtifactModel",
    "R5PromotionDecisionAuthorizationModel",
    "R5PromotionDecisionBundleModel",
    "R5PromotionLifecycleAuthorizationModel",
    "R5PromotionLifecycleEventModel",
]
