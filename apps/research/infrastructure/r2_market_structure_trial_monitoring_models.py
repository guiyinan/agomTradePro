"""Claimed append-only ORM ledgers for R2 explanatory monitoring."""

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

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_R2_TRIAL_MONITORING_UOW: ContextVar[object | None] = ContextVar(
    "active_r2_trial_monitoring_uow",
    default=None,
)


@dataclass(frozen=True)
class _R2TrialMonitoringInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_R2_TRIAL_MONITORING_CLAIM: ContextVar[_R2TrialMonitoringInsertClaim | None] = ContextVar(
    "active_r2_trial_monitoring_insert_claim", default=None
)


def _require_active_r2_trial_monitoring_uow() -> object:
    """Require the private R2 persistence transaction."""

    token = _ACTIVE_R2_TRIAL_MONITORING_UOW.get()
    if token is None:
        raise ValidationError("R2 trial monitoring requires an active unit of work.")
    return token


@contextmanager
def _activate_r2_trial_monitoring_uow(token: object) -> Iterator[None]:
    """Activate one private repository write capability."""

    reset = _ACTIVE_R2_TRIAL_MONITORING_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_R2_TRIAL_MONITORING_UOW.reset(reset)


@contextmanager
def _claim_r2_trial_monitoring_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Authorize one exact model insert inside the active UoW."""

    if _ACTIVE_R2_TRIAL_MONITORING_UOW.get() is not token:
        raise ValidationError("R2 trial monitoring insert requires its unit of work.")
    claim = _R2TrialMonitoringInsertClaim(
        token=token,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset = _ACTIVE_R2_TRIAL_MONITORING_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_R2_TRIAL_MONITORING_CLAIM.reset(reset)


def _require_r2_trial_monitoring_insert_claim(model: models.Model) -> None:
    claim = _ACTIVE_R2_TRIAL_MONITORING_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_R2_TRIAL_MONITORING_UOW.get()
        or claim.model_type is not type(model)
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("R2 trial monitoring requires an exact insert claim.")


class R2TrialMonitoringQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject public and private mutation shortcuts."""

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R2 trial monitoring get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R2 trial monitoring update_or_create is forbidden.")

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R2 trial monitoring rows require repository appends.")

    def _update(self, values: object) -> NoReturn:
        raise ValidationError("R2 trial monitoring evidence cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("R2 trial monitoring evidence cannot be deleted.")

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
            raise ValidationError("R2 trial monitoring private insert is forbidden.")
        for item in items:
            _require_r2_trial_monitoring_insert_claim(item)
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
        raise ValidationError("R2 trial monitoring private bulk insert is forbidden.")


class R2TrialMonitoringManager(AppendOnlyManager[_ModelT]):
    """Expose identical guards through default and base managers."""

    def get_queryset(self) -> R2TrialMonitoringQuerySet[_ModelT]:
        return R2TrialMonitoringQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R2 trial monitoring rows require repository appends.")

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R2 trial monitoring get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R2 trial monitoring update_or_create is forbidden.")


class R2TrialMonitoringAppendOnlyModel(models.Model):
    """Permit only repository-claimed first inserts."""

    objects = R2TrialMonitoringManager()

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
            raise ValidationError("R2 trial monitoring evidence is append-only.")
        _require_r2_trial_monitoring_insert_claim(self)
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
            raise ValidationError("R2 trial monitoring evidence is append-only.")
        _require_r2_trial_monitoring_insert_claim(self)
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
        raise ValidationError("R2 trial monitoring evidence cannot be deleted.")


class R2ExplanatoryTrialAssessmentLedgerModel(R2TrialMonitoringAppendOnlyModel):
    """Complete two-cycle trial owner graph and derived assessment."""

    assessment_id = models.CharField(max_length=192)
    assessment_version = models.CharField(max_length=64)
    policy_id = models.CharField(max_length=192, db_index=True)
    policy_version = models.CharField(max_length=192)
    policy_hash = models.CharField(max_length=64)
    taxonomy_publication_id = models.CharField(max_length=192)
    taxonomy_publication_version = models.CharField(max_length=192)
    taxonomy_publication_hash = models.CharField(max_length=64)
    calendar_publication_id = models.CharField(max_length=192)
    calendar_publication_version = models.CharField(max_length=192)
    calendar_publication_hash = models.CharField(max_length=64)
    cycle_one_hash = models.CharField(max_length=64)
    cycle_two_hash = models.CharField(max_length=64)
    audit_outcome_id = models.CharField(max_length=192)
    audit_outcome_version = models.CharField(max_length=192)
    audit_outcome_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=32)
    assessed_at = models.DateTimeField(db_index=True)
    owner_valid_until = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_as_predictive_signal = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    is_attested_ready = models.BooleanField(default=False)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R2TrialMonitoringAppendOnlyModel.Meta):
        db_table = "research_r2_explanatory_trial_assessment"
        indexes = [
            models.Index(
                fields=["policy_id", "policy_version", "assessed_at"],
                name="res_r2_tm_trial_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment_id", "assessment_version"],
                name="res_r2_tm_trial_ident_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("passed", "breached", "blocked")),
                name="res_r2_tm_trial_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(assessed_at__lte=models.F("ledger_recorded_at"))
                & models.Q(ledger_recorded_at__lt=models.F("owner_valid_until")),
                name="res_r2_tm_trial_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_as_predictive_signal=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                    is_attested_ready=False,
                ),
                name="res_r2_tm_trial_safe_ck",
            ),
        ]


class R2MonitoringAssessmentLedgerModel(R2TrialMonitoringAppendOnlyModel):
    """Manual-review-only assessment sealing one exact fact set."""

    trial_assessment = models.ForeignKey(
        R2ExplanatoryTrialAssessmentLedgerModel,
        on_delete=models.PROTECT,
        related_name="monitoring_assessments",
    )
    assessment_id = models.CharField(max_length=192)
    assessment_version = models.CharField(max_length=64)
    policy_id = models.CharField(max_length=192, db_index=True)
    policy_version = models.CharField(max_length=192)
    policy_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=40)
    assessed_at = models.DateTimeField(db_index=True)
    owner_valid_until = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    fact_count = models.PositiveIntegerField()
    fact_manifest_hash = models.CharField(max_length=64)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    retirement_review_required = models.BooleanField(default=False)
    automatic_retirement = models.BooleanField(default=False)
    research_only = models.BooleanField(default=True)
    must_not_use_as_predictive_signal = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R2TrialMonitoringAppendOnlyModel.Meta):
        db_table = "research_r2_monitoring_assessment"
        indexes = [
            models.Index(
                fields=["policy_id", "policy_version", "assessed_at"],
                name="res_r2_tm_asmt_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment_id", "assessment_version"],
                name="res_r2_tm_asmt_ident_uq",
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
                name="res_r2_tm_asmt_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(fact_count__gt=0)
                & models.Q(assessed_at__lte=models.F("ledger_recorded_at"))
                & models.Q(ledger_recorded_at__lt=models.F("owner_valid_until")),
                name="res_r2_tm_asmt_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    automatic_retirement=False,
                    research_only=True,
                    must_not_use_as_predictive_signal=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r2_tm_asmt_safe_ck",
            ),
        ]


class R2MonitoringObservationLedgerModel(R2TrialMonitoringAppendOnlyModel):
    """Assessment-scoped immutable owner raw fact."""

    monitoring_assessment = models.ForeignKey(
        R2MonitoringAssessmentLedgerModel,
        on_delete=models.PROTECT,
        related_name="observations",
    )
    trial_assessment = models.ForeignKey(
        R2ExplanatoryTrialAssessmentLedgerModel,
        on_delete=models.PROTECT,
        related_name="monitoring_observations",
    )
    fact_id = models.CharField(max_length=192)
    fact_version = models.CharField(max_length=192)
    fact_content_hash = models.CharField(max_length=64)
    policy_id = models.CharField(max_length=192, db_index=True)
    policy_version = models.CharField(max_length=192)
    policy_hash = models.CharField(max_length=64)
    period_id = models.CharField(max_length=192, db_index=True)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    source_owner = models.CharField(max_length=192)
    owner_observed_at = models.DateTimeField()
    owner_available_at = models.DateTimeField()
    owner_recorded_at = models.DateTimeField()
    owner_valid_until = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    row_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_as_predictive_signal = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R2TrialMonitoringAppendOnlyModel.Meta):
        db_table = "research_r2_monitoring_observation"
        indexes = [
            models.Index(
                fields=["policy_id", "period_end", "ledger_recorded_at"],
                name="res_r2_tm_obs_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["monitoring_assessment", "fact_id", "fact_version"],
                name="res_r2_tm_obs_scope_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(period_start__lt=models.F("period_end"))
                & models.Q(owner_observed_at__lte=models.F("owner_available_at"))
                & models.Q(owner_available_at__lte=models.F("owner_recorded_at"))
                & models.Q(owner_recorded_at__lte=models.F("ledger_recorded_at"))
                & models.Q(ledger_recorded_at__lt=models.F("owner_valid_until")),
                name="res_r2_tm_obs_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_as_predictive_signal=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r2_tm_obs_safe_ck",
            ),
        ]


class R2MonitoringAuditSnapshotModel(R2TrialMonitoringAppendOnlyModel):
    """Immutable manifest for signed, stable internal-audit pagination."""

    snapshot_id = models.CharField(max_length=192)
    snapshot_version = models.CharField(max_length=64)
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

    class Meta(R2TrialMonitoringAppendOnlyModel.Meta):
        db_table = "research_r2_monitoring_audit_snapshot"
        indexes = [
            models.Index(
                fields=["as_of", "created_at"],
                name="res_r2_tm_snap_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot_id", "snapshot_version"],
                name="res_r2_tm_snap_ident_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(as_of__lte=models.F("created_at")),
                name="res_r2_tm_snap_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    internal_audit_only=True,
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="res_r2_tm_snap_safe_ck",
            ),
        ]


@receiver(pre_delete, sender=R2ExplanatoryTrialAssessmentLedgerModel, weak=False)
@receiver(pre_delete, sender=R2MonitoringAssessmentLedgerModel, weak=False)
@receiver(pre_delete, sender=R2MonitoringObservationLedgerModel, weak=False)
@receiver(pre_delete, sender=R2MonitoringAuditSnapshotModel, weak=False)
def _reject_r2_trial_monitoring_collector_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject Collector, cascade, and direct deletion paths."""

    raise ValidationError("R2 trial monitoring evidence cannot be deleted.")


from apps.research.infrastructure.r2_market_structure_trial_policy_models import (  # noqa: E402,F401
    R2MarketStructureTrialPolicyLedgerModel,
)

__all__ = [
    "R2ExplanatoryTrialAssessmentLedgerModel",
    "R2MonitoringAssessmentLedgerModel",
    "R2MonitoringAuditSnapshotModel",
    "R2MonitoringObservationLedgerModel",
    "R2MarketStructureTrialPolicyLedgerModel",
    "_activate_r2_trial_monitoring_uow",
    "_claim_r2_trial_monitoring_insert",
    "_require_active_r2_trial_monitoring_uow",
]
