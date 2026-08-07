"""Append-only ORM ledgers for R6 qualification evidence and lifecycle."""

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

_ACTIVE_R6_QUALIFICATION_UOW: ContextVar[object | None] = ContextVar(
    "active_r6_qualification_uow",
    default=None,
)


@dataclass(frozen=True)
class _R6QualificationInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_R6_QUALIFICATION_CLAIM: ContextVar[_R6QualificationInsertClaim | None] = ContextVar(
    "active_r6_qualification_insert_claim",
    default=None,
)


def _require_active_r6_qualification_uow() -> object:
    """Require a repository-owned unit of work before owner reads/writes."""

    token = _ACTIVE_R6_QUALIFICATION_UOW.get()
    if token is None:
        raise ValidationError("R6 qualification access requires an active unit of work.")
    return token


@contextmanager
def _activate_r6_qualification_uow(token: object) -> Iterator[None]:
    """Activate a repository unit-of-work token for the current context."""

    reset = _ACTIVE_R6_QUALIFICATION_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_R6_QUALIFICATION_UOW.reset(reset)


@contextmanager
def _claim_r6_qualification_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Authorize one exact append; bulk and unclaimed saves stay blocked."""

    if _ACTIVE_R6_QUALIFICATION_UOW.get() is not token:
        raise ValidationError("R6 qualification insert requires its repository unit of work.")
    claim = _R6QualificationInsertClaim(
        token=token,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset = _ACTIVE_R6_QUALIFICATION_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_R6_QUALIFICATION_CLAIM.reset(reset)


class R6QualificationQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject bulk writes to every R6 ledger."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R6 qualification evidence requires exact repository appends.")


class R6QualificationManager(AppendOnlyManager[_ModelT]):
    """Expose append-only guards through all default/base managers."""

    def get_queryset(self) -> R6QualificationQuerySet[_ModelT]:
        return R6QualificationQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R6 qualification evidence requires exact repository appends.")


class R6QualificationAppendOnlyModel(models.Model):
    """Permit only one exact claimed insert with a database-assigned key."""

    objects = R6QualificationManager()

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
            raise ValidationError("R6 qualification evidence is append-only.")
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
            raise ValidationError("R6 qualification evidence is append-only.")
        self._require_claim()
        super().save_base(
            raw=False,
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def _require_claim(self) -> None:
        claim = _ACTIVE_R6_QUALIFICATION_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_R6_QUALIFICATION_UOW.get()
            or claim.model_type is not type(self)
            or any(
                getattr(self, field_name) != expected
                for field_name, expected in claim.expected_values
            )
        ):
            raise ValidationError("R6 qualification evidence requires an exact insert claim.")

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("R6 qualification evidence cannot be deleted.")


class R6QualificationAssessmentModel(R6QualificationAppendOnlyModel):
    """Immutable canonical qualification assessment evidence."""

    assessment_id = models.CharField(max_length=192, unique=True)
    study_id = models.CharField(max_length=192, db_index=True)
    assessed_at = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=32)
    candidate_id = models.CharField(max_length=192, null=True)
    candidate_version = models.CharField(max_length=192, null=True)
    study_hash = models.CharField(max_length=64, null=True)
    preregistration_hash = models.CharField(max_length=64, null=True)
    baseline_shortfall_report_hash = models.CharField(max_length=64, null=True)
    candidate_evidence_hash = models.CharField(max_length=64, null=True)
    advanced_assessment_hash = models.CharField(max_length=64, null=True)
    pit_manifest_canonical_hash = models.CharField(max_length=64, null=True)
    artifact_attestation_hash = models.CharField(max_length=64, null=True)
    advanced_threshold_hash = models.CharField(max_length=64, null=True)
    derived_metric_bundle_hash = models.CharField(max_length=64, null=True)
    policy_hash = models.CharField(max_length=64, null=True)
    metric_result_count = models.PositiveIntegerField()
    blockers = models.JSONField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    may_request_promotion_review = models.BooleanField()
    promotion_decision_present = models.BooleanField(default=False)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_replace_regime = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_r6_qualification_assessment"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=["study_id", "recorded_at"],
                name="res_r6_qual_pit_ix",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(assessed_at__lte=models.F("recorded_at")),
                name="res_r6_qual_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    promotion_decision_present=False,
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_replace_regime=True,
                ),
                name="res_r6_qual_safety_ck",
            ),
        ]


class R6QualificationLifecycleAuthorizationModel(R6QualificationAppendOnlyModel):
    """Immutable copy of one research owner lifecycle authorization."""

    assessment = models.ForeignKey(
        R6QualificationAssessmentModel,
        on_delete=models.PROTECT,
        related_name="lifecycle_authorizations",
    )
    authorization_id = models.CharField(max_length=192)
    authorization_version = models.CharField(max_length=192)
    event_id = models.CharField(max_length=192)
    event_version = models.CharField(max_length=192)
    action = models.CharField(max_length=16)
    expected_sequence = models.PositiveIntegerField()
    owner = models.CharField(max_length=32)
    issued_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField()
    reason_codes = models.JSONField()
    evidence_ref = models.CharField(max_length=300)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_replace_regime = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_r6_qualification_lifecycle_auth"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["authorization_id", "authorization_version"],
                name="res_r6_qual_auth_identity_uq",
            ),
            models.UniqueConstraint(
                fields=["event_id", "event_version"],
                name="res_r6_qual_auth_event_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(issued_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="res_r6_qual_auth_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="research",
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_replace_regime=True,
                ),
                name="res_r6_qual_auth_safety_ck",
            ),
        ]


class R6QualificationLifecycleEventModel(R6QualificationAppendOnlyModel):
    """Append-only transition event linked to exactly one authorization."""

    assessment = models.ForeignKey(
        R6QualificationAssessmentModel,
        on_delete=models.PROTECT,
        related_name="lifecycle_events",
    )
    authorization = models.OneToOneField(
        R6QualificationLifecycleAuthorizationModel,
        on_delete=models.PROTECT,
        related_name="lifecycle_event",
    )
    event_id = models.CharField(max_length=192)
    event_version = models.CharField(max_length=192)
    action = models.CharField(max_length=16)
    sequence = models.PositiveIntegerField()
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    previous_event_hash = models.CharField(max_length=64, null=True)
    reason_codes = models.JSONField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_replace_regime = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_r6_qualification_lifecycle_event"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["event_id", "event_version"],
                name="res_r6_qual_event_identity_uq",
            ),
            models.UniqueConstraint(
                fields=["assessment", "sequence"],
                name="res_r6_qual_event_sequence_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(occurred_at__lte=models.F("recorded_at")),
                name="res_r6_qual_event_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_replace_regime=True,
                ),
                name="res_r6_qual_event_safety_ck",
            ),
        ]


__all__ = [
    "R6QualificationAssessmentModel",
    "R6QualificationLifecycleAuthorizationModel",
    "R6QualificationLifecycleEventModel",
    "_activate_r6_qualification_uow",
    "_claim_r6_qualification_insert",
    "_require_active_r6_qualification_uow",
]
