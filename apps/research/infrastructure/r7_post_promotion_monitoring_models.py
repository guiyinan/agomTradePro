"""Claimed append-only ORM ledgers for R7 post-promotion monitoring."""

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

from apps.research.infrastructure.r7_research_result_lifecycle_models import (
    R7ResultLifecycleEventModel,
)
from apps.research.infrastructure.r7_research_result_models import R7ResearchResultModel
from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_R7_MONITORING_UOW: ContextVar[object | None] = ContextVar(
    "active_r7_monitoring_uow",
    default=None,
)


@dataclass(frozen=True)
class _R7MonitoringInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_R7_MONITORING_CLAIM: ContextVar[_R7MonitoringInsertClaim | None] = ContextVar(
    "active_r7_monitoring_insert_claim",
    default=None,
)


def _require_active_r7_monitoring_uow() -> object:
    """Require the private R7 monitoring write transaction."""

    token = _ACTIVE_R7_MONITORING_UOW.get()
    if token is None:
        raise ValidationError("R7 monitoring access requires an active unit of work.")
    return token


@contextmanager
def _activate_r7_monitoring_uow(token: object) -> Iterator[None]:
    """Activate one private repository capability token."""

    reset = _ACTIVE_R7_MONITORING_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_R7_MONITORING_UOW.reset(reset)


@contextmanager
def _claim_r7_monitoring_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Authorize one exact insert payload inside the active write UoW."""

    if _ACTIVE_R7_MONITORING_UOW.get() is not token:
        raise ValidationError("R7 monitoring insert requires its unit of work.")
    claim = _R7MonitoringInsertClaim(
        token=token,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset = _ACTIVE_R7_MONITORING_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_R7_MONITORING_CLAIM.reset(reset)


def _require_r7_monitoring_insert_claim(model: models.Model) -> None:
    claim = _ACTIVE_R7_MONITORING_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_R7_MONITORING_UOW.get()
        or claim.model_type is not type(model)
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("R7 monitoring evidence requires an exact insert claim.")


class R7MonitoringQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject public and private mutation shortcuts."""

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R7 monitoring get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R7 monitoring update_or_create is forbidden.")

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R7 monitoring rows require exact repository appends.")

    def _update(self, values: object) -> NoReturn:
        raise ValidationError("R7 monitoring evidence cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("R7 monitoring evidence cannot be deleted.")

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
            raise ValidationError("R7 monitoring private insert is forbidden.")
        for item in items:
            _require_r7_monitoring_insert_claim(item)
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
        raise ValidationError("R7 monitoring private bulk insert is forbidden.")


class R7MonitoringManager(AppendOnlyManager[_ModelT]):
    """Expose identical guards through default and base managers."""

    def get_queryset(self) -> R7MonitoringQuerySet[_ModelT]:
        return R7MonitoringQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R7 monitoring rows require exact repository appends.")

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R7 monitoring get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R7 monitoring update_or_create is forbidden.")


class R7MonitoringAppendOnlyModel(models.Model):
    """Permit only a repository-claimed insert inside its private UoW."""

    objects = R7MonitoringManager()

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
            raise ValidationError("R7 monitoring evidence is append-only.")
        _require_r7_monitoring_insert_claim(self)
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
            raise ValidationError("R7 monitoring evidence is append-only.")
        _require_r7_monitoring_insert_claim(self)
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
        raise ValidationError("R7 monitoring evidence cannot be deleted.")


class R7MonitoringAssessmentLedgerModel(R7MonitoringAppendOnlyModel):
    """Immutable complete assessment bound to authoritative result/lifecycle rows."""

    assessment_id = models.CharField(max_length=192, unique=True)
    assessment_version = models.CharField(max_length=192)
    result = models.ForeignKey(
        R7ResearchResultModel,
        on_delete=models.PROTECT,
        related_name="r7_monitoring_assessments",
    )
    lifecycle_head = models.ForeignKey(
        R7ResultLifecycleEventModel,
        on_delete=models.PROTECT,
        related_name="r7_monitoring_assessments",
    )
    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    policy_hash = models.CharField(max_length=64)
    result_stable_id = models.CharField(max_length=192)
    result_version = models.CharField(max_length=192)
    result_hash = models.CharField(max_length=64)
    lifecycle_attestation_id = models.CharField(max_length=192)
    lifecycle_attestation_version = models.CharField(max_length=192)
    lifecycle_attestation_hash = models.CharField(max_length=64)
    lifecycle_head_hash = models.CharField(max_length=64)
    calendar_id = models.CharField(max_length=192)
    calendar_version = models.CharField(max_length=192)
    calendar_hash = models.CharField(max_length=64)
    period_id = models.CharField(max_length=192)
    period_version = models.CharField(max_length=192)
    period_hash = models.CharField(max_length=64)
    realization_owner_id = models.CharField(max_length=300)
    realization_owner_version = models.CharField(max_length=192)
    realization_owner_hash = models.CharField(max_length=64)
    evaluated_at = models.DateTimeField()
    policy_recorded_at = models.DateTimeField()
    result_recorded_at = models.DateTimeField()
    lifecycle_recorded_at = models.DateTimeField()
    calendar_recorded_at = models.DateTimeField()
    realization_recorded_at = models.DateTimeField()
    owner_valid_until = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    observation_count = models.PositiveIntegerField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=48)
    automatic_retirement = models.BooleanField(default=False)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R7MonitoringAppendOnlyModel.Meta):
        db_table = "research_r7_monitoring_assessment"
        indexes = [
            models.Index(
                fields=["result", "policy_hash", "ledger_recorded_at"],
                name="res_r7_mon_asmt_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["policy_id", "policy_version", "policy_hash", "evaluated_at"],
                name="res_r7_mon_asmt_cmd_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(policy_recorded_at__lte=models.F("evaluated_at"))
                    & models.Q(result_recorded_at__lte=models.F("evaluated_at"))
                    & models.Q(lifecycle_recorded_at__lte=models.F("evaluated_at"))
                    & models.Q(calendar_recorded_at__lte=models.F("evaluated_at"))
                    & models.Q(realization_recorded_at__lte=models.F("evaluated_at"))
                    & models.Q(evaluated_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(ledger_recorded_at__lt=models.F("owner_valid_until"))
                ),
                name="res_r7_mon_asmt_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "healthy",
                        "breached",
                        "retirement_review_required",
                        "blocked",
                    )
                ),
                name="res_r7_mon_asmt_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    automatic_retirement=False,
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="res_r7_mon_asmt_safe_ck",
            ),
        ]


class R7MonitoringObservationLedgerModel(R7MonitoringAppendOnlyModel):
    """Immutable assessment-scoped Forecast Ledger realization member."""

    assessment = models.ForeignKey(
        R7MonitoringAssessmentLedgerModel,
        on_delete=models.PROTECT,
        related_name="observations",
    )
    result = models.ForeignKey(
        R7ResearchResultModel,
        on_delete=models.PROTECT,
        related_name="r7_monitoring_observations",
    )
    lifecycle_head = models.ForeignKey(
        R7ResultLifecycleEventModel,
        on_delete=models.PROTECT,
        related_name="r7_monitoring_observations",
    )
    observation_index = models.PositiveIntegerField()
    observation_id = models.CharField(max_length=300)
    observation_version = models.CharField(max_length=192)
    observation_hash = models.CharField(max_length=64)
    prediction_hash = models.CharField(max_length=64)
    member_hash = models.CharField(max_length=64)
    period_id = models.CharField(max_length=192)
    period_hash = models.CharField(max_length=64)
    published_at = models.DateTimeField()
    horizon_end = models.DateTimeField()
    available_at = models.DateTimeField()
    owner_recorded_at = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R7MonitoringAppendOnlyModel.Meta):
        db_table = "research_r7_monitoring_observation"
        indexes = [
            models.Index(
                fields=["result", "period_id", "ledger_recorded_at"],
                name="res_r7_mon_obs_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "observation_index"],
                name="res_r7_mon_obs_index_uq",
            ),
            models.UniqueConstraint(
                fields=["assessment", "observation_id", "observation_version"],
                name="res_r7_mon_obs_ident_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(published_at__lt=models.F("horizon_end"))
                    & models.Q(horizon_end__lte=models.F("available_at"))
                    & models.Q(available_at__lte=models.F("owner_recorded_at"))
                    & models.Q(owner_recorded_at__lte=models.F("ledger_recorded_at"))
                ),
                name="res_r7_mon_obs_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="res_r7_mon_obs_safe_ck",
            ),
        ]


class R7MonitoringAuditSnapshotModel(R7MonitoringAppendOnlyModel):
    """Immutable manifest backing signed internal-audit cursors."""

    snapshot_id = models.CharField(max_length=192)
    snapshot_version = models.CharField(max_length=192)
    as_of = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(db_index=True)
    entry_count = models.PositiveIntegerField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    internal_audit_only = models.BooleanField(default=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R7MonitoringAppendOnlyModel.Meta):
        db_table = "research_r7_monitoring_audit_snapshot"
        indexes = [
            models.Index(
                fields=["as_of", "created_at"],
                name="res_r7_mon_snap_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot_id", "snapshot_version"],
                name="res_r7_mon_snap_ident_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(as_of__lte=models.F("created_at")),
                name="res_r7_mon_snap_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    internal_audit_only=True,
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="res_r7_mon_snap_safe_ck",
            ),
        ]


@receiver(pre_delete, sender=R7MonitoringObservationLedgerModel, weak=False)
@receiver(pre_delete, sender=R7MonitoringAssessmentLedgerModel, weak=False)
@receiver(pre_delete, sender=R7MonitoringAuditSnapshotModel, weak=False)
def _reject_r7_monitoring_collector_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject Django Collector, cascade, and direct deletion paths."""

    raise ValidationError("R7 monitoring evidence cannot be deleted.")


__all__ = [
    "R7MonitoringAssessmentLedgerModel",
    "R7MonitoringAuditSnapshotModel",
    "R7MonitoringObservationLedgerModel",
]
