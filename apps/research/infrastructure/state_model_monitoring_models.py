"""Claimed append-only ORM ledgers for R6 monitoring evidence."""

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
from django.dispatch import receiver

from apps.research.infrastructure.state_model_qualification_models import (
    R6QualificationAssessmentModel,
)
from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_R6_MONITORING_UOW: ContextVar[object | None] = ContextVar(
    "active_r6_monitoring_uow",
    default=None,
)


@dataclass(frozen=True)
class _R6MonitoringInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_R6_MONITORING_CLAIM: ContextVar[_R6MonitoringInsertClaim | None] = ContextVar(
    "active_r6_monitoring_insert_claim",
    default=None,
)


def _require_active_r6_monitoring_uow() -> object:
    """Require the composition-owned monitoring transaction."""

    token = _ACTIVE_R6_MONITORING_UOW.get()
    if token is None:
        raise ValidationError("R6 monitoring access requires an active unit of work.")
    return token


@contextmanager
def _activate_r6_monitoring_uow(token: object) -> Iterator[None]:
    """Activate one repository capability token for owner reads and appends."""

    reset = _ACTIVE_R6_MONITORING_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_R6_MONITORING_UOW.reset(reset)


@contextmanager
def _claim_r6_monitoring_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Authorize one exact model/payload insert inside the active UoW."""

    if _ACTIVE_R6_MONITORING_UOW.get() is not token:
        raise ValidationError("R6 monitoring insert requires its unit of work.")
    claim = _R6MonitoringInsertClaim(
        token=token,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset = _ACTIVE_R6_MONITORING_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_R6_MONITORING_CLAIM.reset(reset)


def _require_r6_monitoring_insert_claim(model: models.Model) -> None:
    claim = _ACTIVE_R6_MONITORING_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_R6_MONITORING_UOW.get()
        or claim.model_type is not type(model)
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("R6 monitoring evidence requires an exact insert claim.")


class R6MonitoringQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject public and private mutation shortcuts."""

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R6 monitoring get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R6 monitoring update_or_create is forbidden.")

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R6 monitoring rows require exact repository appends.")

    def _update(self, values: object) -> NoReturn:
        raise ValidationError("R6 monitoring evidence cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("R6 monitoring evidence cannot be deleted.")

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
        """Allow only Model.save's exact claimed first insert."""

        items = list(objs)
        if (
            not items
            or raw
            or on_conflict is not None
            or update_fields is not None
            or unique_fields is not None
            or (using is not None and using != self.db)
        ):
            raise ValidationError("R6 monitoring private insert is forbidden.")
        for item in items:
            _require_r6_monitoring_insert_claim(item)
        insert = cast(
            Callable[..., list[tuple[object, ...]]],
            getattr(super(), "_insert"),  # noqa: B009 - typed private Django boundary
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
        raise ValidationError("R6 monitoring private bulk insert is forbidden.")


class R6MonitoringManager(AppendOnlyManager[_ModelT]):
    """Expose identical monitoring guards through default/base managers."""

    def get_queryset(self) -> R6MonitoringQuerySet[_ModelT]:
        return R6MonitoringQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R6 monitoring rows require exact repository appends.")

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R6 monitoring get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R6 monitoring update_or_create is forbidden.")


class R6MonitoringAppendOnlyModel(models.Model):
    """Permit only one repository-claimed database-keyed insert."""

    objects = R6MonitoringManager()

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
            raise ValidationError("R6 monitoring evidence is append-only.")
        _require_r6_monitoring_insert_claim(self)
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
            raise ValidationError("R6 monitoring evidence is append-only.")
        _require_r6_monitoring_insert_claim(self)
        super().save_base(
            raw=False,
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("R6 monitoring evidence cannot be deleted.")


class R6MonitoringObservationModel(R6MonitoringAppendOnlyModel):
    """Immutable canonical raw monitoring observation."""

    qualification = models.ForeignKey(
        R6QualificationAssessmentModel,
        on_delete=models.PROTECT,
        related_name="monitoring_observations",
    )
    observation_id = models.CharField(max_length=192)
    observation_version = models.CharField(max_length=192)
    qualification_assessment_id = models.CharField(max_length=192)
    qualification_assessment_hash = models.CharField(max_length=64)
    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    policy_hash = models.CharField(max_length=64)
    period_calendar_id = models.CharField(max_length=192)
    period_calendar_version = models.CharField(max_length=192)
    period_calendar_hash = models.CharField(max_length=64)
    observation_period_id = models.CharField(max_length=64)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    source_owner = models.CharField(max_length=192)
    observed_at = models.DateTimeField()
    available_at = models.DateTimeField()
    owner_recorded_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    pit_manifest_id = models.CharField(max_length=192)
    pit_manifest_hash = models.CharField(max_length=64)
    evidence_ref = models.CharField(max_length=300)
    label_protocol_version = models.CharField(max_length=192)
    observed_label_set_hash = models.CharField(max_length=64)
    metric_count = models.PositiveIntegerField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_recorded_at = models.DateTimeField(db_index=True)
    ledger_header_hash = models.CharField(max_length=64)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_replace_regime = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R6MonitoringAppendOnlyModel.Meta):
        db_table = "research_r6_monitoring_observation"
        indexes = [
            models.Index(
                fields=["qualification", "policy_hash", "ledger_recorded_at"],
                name="res_r6_mon_obs_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["observation_id", "observation_version"],
                name="res_r6_mon_obs_ident_uq",
            ),
            models.UniqueConstraint(
                fields=["qualification", "policy_hash", "observation_period_id"],
                name="res_r6_mon_obs_period_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(observed_at__lte=models.F("available_at"))
                    & models.Q(available_at__lte=models.F("owner_recorded_at"))
                    & models.Q(owner_recorded_at__lt=models.F("valid_until"))
                    & models.Q(owner_recorded_at__lte=models.F("ledger_recorded_at"))
                ),
                name="res_r6_mon_obs_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(period_start__lt=models.F("period_end"))
                    & models.Q(period_start__lte=models.F("observed_at"))
                    & models.Q(observed_at__lt=models.F("period_end"))
                ),
                name="res_r6_mon_obs_window_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_replace_regime=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="res_r6_mon_obs_safe_ck",
            ),
        ]


class R6MonitoringAssessmentModel(R6MonitoringAppendOnlyModel):
    """Immutable recomputed monitoring assessment and exact owner graph."""

    qualification = models.ForeignKey(
        R6QualificationAssessmentModel,
        on_delete=models.PROTECT,
        related_name="monitoring_assessments",
    )
    assessment_id = models.CharField(max_length=192, unique=True)
    qualification_assessment_id = models.CharField(max_length=192)
    qualification_assessment_hash = models.CharField(max_length=64)
    requested_policy_id = models.CharField(max_length=192)
    requested_policy_version = models.CharField(max_length=192)
    expected_policy_hash = models.CharField(max_length=64)
    policy_hash = models.CharField(max_length=64)
    period_calendar_id = models.CharField(max_length=192)
    period_calendar_version = models.CharField(max_length=192)
    period_calendar_hash = models.CharField(max_length=64)
    evaluated_at = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    ledger_header_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=40)
    observation_count = models.PositiveIntegerField()
    metric_result_count = models.PositiveIntegerField()
    observation_hashes = models.JSONField()
    blockers = models.JSONField()
    policy_payload = models.JSONField()
    period_calendar_payload = models.JSONField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    label_drift_detected = models.BooleanField()
    retirement_review_required = models.BooleanField()
    automatic_retirement = models.BooleanField(default=False)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_replace_regime = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R6MonitoringAppendOnlyModel.Meta):
        db_table = "research_r6_monitoring_assessment"
        indexes = [
            models.Index(
                fields=["qualification", "expected_policy_hash", "ledger_recorded_at"],
                name="res_r6_mon_asmt_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["qualification", "expected_policy_hash", "evaluated_at"],
                name="res_r6_mon_asmt_cmd_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(evaluated_at__lte=models.F("ledger_recorded_at")),
                name="res_r6_mon_asmt_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    automatic_retirement=False,
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_replace_regime=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="res_r6_mon_asmt_safe_ck",
            ),
        ]


@receiver(pre_delete, sender=R6MonitoringObservationModel, weak=False)
@receiver(pre_delete, sender=R6MonitoringAssessmentModel, weak=False)
def _reject_r6_monitoring_collector_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject Django Collector, cascade, and direct deletion paths."""

    raise ValidationError("R6 monitoring evidence cannot be deleted.")


__all__ = [
    "R6MonitoringAssessmentModel",
    "R6MonitoringObservationModel",
    "_activate_r6_monitoring_uow",
    "_claim_r6_monitoring_insert",
    "_require_active_r6_monitoring_uow",
]
