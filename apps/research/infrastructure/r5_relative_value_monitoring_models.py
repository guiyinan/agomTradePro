"""Claimed append-only ORM ledgers for R5 post-promotion monitoring."""

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

from apps.research.infrastructure.r5_relative_value_promotion_models import (
    R5PromotionDecisionBundleModel,
    R5PromotionLifecycleEventModel,
)
from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_R5_MONITORING_UOW: ContextVar[object | None] = ContextVar(
    "active_r5_monitoring_uow",
    default=None,
)


@dataclass(frozen=True)
class _R5MonitoringInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_R5_MONITORING_CLAIM: ContextVar[_R5MonitoringInsertClaim | None] = ContextVar(
    "active_r5_monitoring_insert_claim",
    default=None,
)


def _require_active_r5_monitoring_uow() -> object:
    """Require the private R5 monitoring write transaction."""

    token = _ACTIVE_R5_MONITORING_UOW.get()
    if token is None:
        raise ValidationError("R5 monitoring access requires an active unit of work.")
    return token


@contextmanager
def _activate_r5_monitoring_uow(token: object) -> Iterator[None]:
    """Activate one private repository capability token."""

    reset = _ACTIVE_R5_MONITORING_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_R5_MONITORING_UOW.reset(reset)


@contextmanager
def _claim_r5_monitoring_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Authorize one exact insert payload inside the active write UoW."""

    if _ACTIVE_R5_MONITORING_UOW.get() is not token:
        raise ValidationError("R5 monitoring insert requires its unit of work.")
    claim = _R5MonitoringInsertClaim(
        token=token,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset = _ACTIVE_R5_MONITORING_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_R5_MONITORING_CLAIM.reset(reset)


def _require_r5_monitoring_insert_claim(model: models.Model) -> None:
    claim = _ACTIVE_R5_MONITORING_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_R5_MONITORING_UOW.get()
        or claim.model_type is not type(model)
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("R5 monitoring evidence requires an exact insert claim.")


class R5MonitoringQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject public and private mutation shortcuts."""

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R5 monitoring get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R5 monitoring update_or_create is forbidden.")

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R5 monitoring rows require exact repository appends.")

    def _update(self, values: object) -> NoReturn:
        raise ValidationError("R5 monitoring evidence cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("R5 monitoring evidence cannot be deleted.")

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
            raise ValidationError("R5 monitoring private insert is forbidden.")
        for item in items:
            _require_r5_monitoring_insert_claim(item)
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
        raise ValidationError("R5 monitoring private bulk insert is forbidden.")


class R5MonitoringManager(AppendOnlyManager[_ModelT]):
    """Expose identical guards through default and base managers."""

    def get_queryset(self) -> R5MonitoringQuerySet[_ModelT]:
        return R5MonitoringQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R5 monitoring rows require exact repository appends.")

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R5 monitoring get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R5 monitoring update_or_create is forbidden.")


class R5MonitoringAppendOnlyModel(models.Model):
    """Permit only one repository-claimed database-keyed insert."""

    objects = R5MonitoringManager()

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
            raise ValidationError("R5 monitoring evidence is append-only.")
        _require_r5_monitoring_insert_claim(self)
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
            raise ValidationError("R5 monitoring evidence is append-only.")
        _require_r5_monitoring_insert_claim(self)
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
        raise ValidationError("R5 monitoring evidence cannot be deleted.")


class R5MonitoringAssessmentLedgerModel(R5MonitoringAppendOnlyModel):
    """Immutable assessment plus its complete exact owner graph."""

    assessment_id = models.CharField(max_length=192, unique=True)
    assessment_version = models.CharField(max_length=192)
    active_decision = models.ForeignKey(
        R5PromotionDecisionBundleModel,
        on_delete=models.PROTECT,
        related_name="r5_monitoring_assessments",
    )
    lifecycle_event = models.ForeignKey(
        R5PromotionLifecycleEventModel,
        on_delete=models.PROTECT,
        related_name="r5_monitoring_assessments",
    )
    scope_id = models.CharField(max_length=300)
    scope_hash = models.CharField(max_length=64)
    active_decision_stable_id = models.CharField(max_length=300)
    active_decision_version = models.CharField(max_length=300)
    active_decision_hash = models.CharField(max_length=64)
    active_lifecycle_hash = models.CharField(max_length=64)
    fixed_income_result_id = models.CharField(max_length=300)
    fixed_income_result_version = models.CharField(max_length=300)
    fixed_income_result_hash = models.CharField(max_length=64)
    fixed_income_owner_seal_hash = models.CharField(max_length=64)
    requested_policy_id = models.CharField(max_length=192)
    requested_policy_version = models.CharField(max_length=192)
    expected_policy_hash = models.CharField(max_length=64)
    calendar_id = models.CharField(max_length=192)
    calendar_version = models.CharField(max_length=192)
    calendar_hash = models.CharField(max_length=64)
    evaluated_at = models.DateTimeField()
    active_owner_recorded_at = models.DateTimeField()
    fixed_income_owner_recorded_at = models.DateTimeField()
    policy_owner_recorded_at = models.DateTimeField()
    calendar_owner_recorded_at = models.DateTimeField()
    latest_fact_owner_recorded_at = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    ledger_header_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=48)
    fact_count = models.PositiveIntegerField()
    fact_hashes = models.JSONField()
    active_lifecycle_payload = models.JSONField()
    fixed_income_payload = models.JSONField()
    policy_payload = models.JSONField()
    calendar_payload = models.JSONField()
    assessment_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    automatic_retirement = models.BooleanField(default=False)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R5MonitoringAppendOnlyModel.Meta):
        db_table = "research_r5_monitoring_assessment"
        indexes = [
            models.Index(
                fields=["active_decision", "expected_policy_hash", "ledger_recorded_at"],
                name="res_r5_mon_asmt_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "requested_policy_id",
                    "requested_policy_version",
                    "expected_policy_hash",
                    "evaluated_at",
                ],
                name="res_r5_mon_asmt_cmd_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(active_owner_recorded_at__lte=models.F("evaluated_at"))
                    & models.Q(fixed_income_owner_recorded_at__lte=models.F("evaluated_at"))
                    & models.Q(policy_owner_recorded_at__lte=models.F("evaluated_at"))
                    & models.Q(calendar_owner_recorded_at__lte=models.F("evaluated_at"))
                    & models.Q(latest_fact_owner_recorded_at__lte=models.F("evaluated_at"))
                    & models.Q(evaluated_at__lte=models.F("ledger_recorded_at"))
                ),
                name="res_r5_mon_asmt_clock_ck",
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
                name="res_r5_mon_asmt_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    automatic_retirement=False,
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="res_r5_mon_asmt_safe_ck",
            ),
        ]


class R5MonitoringObservationLedgerModel(R5MonitoringAppendOnlyModel):
    """Immutable assessment-scoped canonical Portfolio raw fact."""

    assessment = models.ForeignKey(
        R5MonitoringAssessmentLedgerModel,
        on_delete=models.PROTECT,
        related_name="observations",
    )
    active_decision = models.ForeignKey(
        R5PromotionDecisionBundleModel,
        on_delete=models.PROTECT,
        related_name="r5_monitoring_observations",
    )
    lifecycle_event = models.ForeignKey(
        R5PromotionLifecycleEventModel,
        on_delete=models.PROTECT,
        related_name="r5_monitoring_observations",
    )
    fact_id = models.CharField(max_length=192)
    fact_version = models.CharField(max_length=192)
    domain_fact_hash = models.CharField(max_length=64)
    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    policy_hash = models.CharField(max_length=64)
    target_hash = models.CharField(max_length=64)
    calendar_id = models.CharField(max_length=192)
    calendar_version = models.CharField(max_length=192)
    calendar_hash = models.CharField(max_length=64)
    period_id = models.CharField(max_length=64)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    source_owner = models.CharField(max_length=192)
    source_owner_id = models.CharField(max_length=192)
    source_owner_version = models.CharField(max_length=192)
    source_owner_hash = models.CharField(max_length=64)
    source_observed_at = models.DateTimeField()
    observed_at = models.DateTimeField()
    available_at = models.DateTimeField()
    owner_recorded_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    observed_label_hash = models.CharField(max_length=64)
    observed_data_schema_hash = models.CharField(max_length=64)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64)
    ledger_recorded_at = models.DateTimeField(db_index=True)
    ledger_header_hash = models.CharField(max_length=64)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R5MonitoringAppendOnlyModel.Meta):
        db_table = "research_r5_monitoring_observation"
        indexes = [
            models.Index(
                fields=["active_decision", "policy_hash", "ledger_recorded_at"],
                name="res_r5_mon_obs_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "period_id"],
                name="res_r5_mon_obs_period_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(period_start__lt=models.F("period_end"))
                    & models.Q(period_end__lte=models.F("observed_at"))
                    & models.Q(source_observed_at__lte=models.F("observed_at"))
                    & models.Q(observed_at__lte=models.F("available_at"))
                    & models.Q(available_at__lte=models.F("owner_recorded_at"))
                    & models.Q(owner_recorded_at__lt=models.F("valid_until"))
                    & models.Q(owner_recorded_at__lte=models.F("ledger_recorded_at"))
                ),
                name="res_r5_mon_obs_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="res_r5_mon_obs_safe_ck",
            ),
        ]


class R5MonitoringAuditSnapshotModel(R5MonitoringAppendOnlyModel):
    """Immutable manifest backing signed internal-audit cursors."""

    snapshot_id = models.CharField(max_length=192)
    snapshot_version = models.CharField(max_length=192)
    as_of = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(db_index=True)
    entry_count = models.PositiveIntegerField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64)
    internal_audit_only = models.BooleanField(default=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R5MonitoringAppendOnlyModel.Meta):
        db_table = "research_r5_monitoring_audit_snapshot"
        indexes = [
            models.Index(
                fields=["as_of", "created_at"],
                name="res_r5_mon_snap_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot_id", "snapshot_version"],
                name="res_r5_mon_snap_ident_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(as_of__lte=models.F("created_at")),
                name="res_r5_mon_snap_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    internal_audit_only=True,
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="res_r5_mon_snap_safe_ck",
            ),
        ]


@receiver(pre_delete, sender=R5MonitoringObservationLedgerModel, weak=False)
@receiver(pre_delete, sender=R5MonitoringAssessmentLedgerModel, weak=False)
@receiver(pre_delete, sender=R5MonitoringAuditSnapshotModel, weak=False)
def _reject_r5_monitoring_collector_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject Django Collector, cascade, and direct deletion paths."""

    raise ValidationError("R5 monitoring evidence cannot be deleted.")


__all__ = [
    "R5MonitoringAssessmentLedgerModel",
    "R5MonitoringAuditSnapshotModel",
    "R5MonitoringObservationLedgerModel",
]
