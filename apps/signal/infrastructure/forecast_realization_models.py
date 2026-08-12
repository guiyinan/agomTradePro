"""Claimed append-only ORM models for Signal R7 realization receipts."""

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
_ACTIVE_REALIZATION_UOW: ContextVar[object | None] = ContextVar(
    "active_signal_realization_uow", default=None
)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_INSERT_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_signal_realization_insert_claim", default=None
)


@contextmanager
def _activate_forecast_realization_uow(token: object) -> Iterator[None]:
    """Activate the private composition-root write capability."""

    reset = _ACTIVE_REALIZATION_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_REALIZATION_UOW.reset(reset)


@contextmanager
def _claim_forecast_realization_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Authorize one exact model insert inside the active write UoW."""

    if _ACTIVE_REALIZATION_UOW.get() is not token:
        raise ValidationError("forecast realization insert requires its unit of work")
    claim = _InsertClaim(
        token=token,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset = _ACTIVE_INSERT_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_INSERT_CLAIM.reset(reset)


def _require_insert_claim(model: models.Model) -> None:
    claim = _ACTIVE_INSERT_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_REALIZATION_UOW.get()
        or claim.model_type is not type(model)
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("forecast realization row requires an exact insert claim")


class ForecastRealizationQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject unclaimed bulk and private mutation shortcuts."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("forecast realization rows require exact appends")

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("forecast realization get_or_create is forbidden")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("forecast realization update_or_create is forbidden")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("forecast realization rows cannot be deleted")

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
            raise ValidationError("forecast realization private insert is forbidden")
        for item in items:
            _require_insert_claim(item)
        insert = cast(
            Callable[..., list[tuple[object, ...]]],
            getattr(super(), "_insert"),  # noqa: B009 - guarded Django boundary
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


class ForecastRealizationManager(AppendOnlyManager[_ModelT]):
    """Expose the realization-specific guarded QuerySet."""

    def get_queryset(self) -> ForecastRealizationQuerySet[_ModelT]:
        return ForecastRealizationQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("forecast realization rows require exact appends")


class ForecastRealizationAppendOnlyModel(models.Model):
    """Permit only one repository-claimed insert and no mutation/deletion."""

    objects = ForecastRealizationManager()

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
            raise ValidationError("forecast realization evidence is append-only")
        _require_insert_claim(self)
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
            raise ValidationError("forecast realization evidence is append-only")
        _require_insert_claim(self)
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
        raise ValidationError("forecast realization evidence cannot be deleted")


class ForecastRealizationSourceDefinitionModel(ForecastRealizationAppendOnlyModel):
    """One versioned Signal-owned result/calendar/period source definition."""

    definition_version = models.CharField(max_length=96)
    owner = models.CharField(max_length=64, default="signal.forecast_ledger")
    owner_record_id = models.CharField(max_length=300)
    owner_record_version = models.CharField(max_length=300)
    result_id = models.CharField(max_length=300)
    result_version = models.CharField(max_length=300)
    result_hash = models.CharField(max_length=64)
    calendar_id = models.CharField(max_length=300)
    calendar_version = models.CharField(max_length=300)
    period_id = models.CharField(max_length=300)
    period_version = models.CharField(max_length=300)
    period_hash = models.CharField(max_length=64)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    available_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    evidence_ref = models.CharField(max_length=300)
    source_content_hash = models.CharField(max_length=64)
    registered_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "signal"
        db_table = "signal_forecast_realization_source_definition"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["owner_record_id", "owner_record_version"],
                name="sig_r7_srcdef_owner_uq",
            ),
            models.UniqueConstraint(
                fields=["result_id", "result_version", "period_id", "period_version"],
                name="sig_r7_srcdef_period_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(period_start__lt=models.F("period_end"))
                    & models.Q(period_end__lte=models.F("available_at"))
                    & models.Q(available_at__lte=models.F("registered_at"))
                    & models.Q(registered_at__lt=models.F("valid_until"))
                ),
                name="sig_r7_srcdef_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="signal.forecast_ledger",
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="sig_r7_srcdef_safe_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["owner_record_id", "owner_record_version", "registered_at"],
                name="sig_r7_srcdef_exact_idx",
            )
        ]


class ForecastRealizationSourceDefinitionMemberModel(ForecastRealizationAppendOnlyModel):
    """One exact outcome-free member selector within a source definition."""

    definition = models.ForeignKey(
        ForecastRealizationSourceDefinitionModel,
        on_delete=models.PROTECT,
        related_name="source_members",
    )
    entry_id = models.CharField(max_length=300)
    observation_id = models.CharField(max_length=300)
    observation_version = models.CharField(max_length=300)
    expected_observation_hash = models.CharField(max_length=64)
    forecast_group_id = models.CharField(max_length=300)
    pit_manifest_version = models.CharField(max_length=300)
    pit_manifest_hash = models.CharField(max_length=64)
    censoring_rule_version = models.CharField(max_length=300)
    outcome_evidence_valid_until = models.DateTimeField()
    available_at = models.DateTimeField(db_index=True)
    evidence_ref = models.CharField(max_length=300)
    content_hash = models.CharField(max_length=64)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "signal"
        db_table = "signal_forecast_realization_source_definition_member"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["definition", "entry_id"],
                name="sig_r7_srcmem_entry_uq",
            ),
            models.UniqueConstraint(
                fields=["definition", "observation_id", "observation_version"],
                name="sig_r7_srcmem_obs_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(observation_id=models.F("entry_id")),
                name="sig_r7_srcmem_alias_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(available_at__lt=models.F("outcome_evidence_valid_until")),
                name="sig_r7_srcmem_clock_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["definition", "entry_id"],
                name="sig_r7_srcmem_exact_idx",
            )
        ]


class ForecastRealizationManifestModel(ForecastRealizationAppendOnlyModel):
    """One complete Signal-owned realization period manifest."""

    manifest_version = models.CharField(max_length=96)
    owner = models.CharField(max_length=64, default="signal.forecast_ledger")
    owner_record_id = models.CharField(max_length=300)
    owner_record_version = models.CharField(max_length=300)
    result_id = models.CharField(max_length=300)
    result_version = models.CharField(max_length=300)
    result_hash = models.CharField(max_length=64)
    calendar_id = models.CharField(max_length=300)
    calendar_version = models.CharField(max_length=300)
    period_id = models.CharField(max_length=300)
    period_version = models.CharField(max_length=300)
    period_hash = models.CharField(max_length=64)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    pit_as_of = models.DateTimeField(db_index=True)
    available_at = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    evidence_ref = models.CharField(max_length=300)
    source_manifest_hash = models.CharField(max_length=64)
    payload_hash = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "signal"
        db_table = "signal_forecast_realization_manifest"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["owner_record_id", "owner_record_version"],
                name="sig_r7_real_owner_uq",
            ),
            models.UniqueConstraint(
                fields=["result_id", "result_version", "period_id", "period_version"],
                name="sig_r7_real_result_period_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(period_start__lt=models.F("period_end"))
                    & models.Q(period_end__lte=models.F("available_at"))
                    & models.Q(available_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lte=models.F("pit_as_of"))
                    & models.Q(pit_as_of__lt=models.F("valid_until"))
                ),
                name="sig_r7_real_manifest_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="signal.forecast_ledger",
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="sig_r7_real_manifest_safe_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["result_id", "result_version", "period_id", "period_version"],
                name="sig_r7_real_exact_idx",
            )
        ]


class ForecastRealizationReceiptModel(ForecastRealizationAppendOnlyModel):
    """One exact ForecastOutcome-derived member receipt."""

    manifest = models.ForeignKey(
        ForecastRealizationManifestModel,
        on_delete=models.PROTECT,
        related_name="receipts",
    )
    entry = models.ForeignKey(
        "signal.ForecastLedgerEntry",
        on_delete=models.PROTECT,
        related_name="realization_receipts",
    )
    receipt_id = models.CharField(max_length=300, unique=True)
    receipt_version = models.CharField(max_length=96)
    observation_id = models.CharField(max_length=300, unique=True)
    observation_version = models.CharField(max_length=96)
    observation_hash = models.CharField(max_length=64, unique=True)
    forecast_group_id = models.CharField(max_length=300)
    scenario_revision_id = models.UUIDField()
    scenario_set_revision_id = models.UUIDField(null=True, blank=True)
    subjective_probability = models.DecimalField(max_digits=18, decimal_places=12)
    subjective_probability_source_version = models.CharField(max_length=64)
    model_probability = models.DecimalField(max_digits=18, decimal_places=12, null=True, blank=True)
    model_probability_source_version = models.CharField(max_length=64, blank=True)
    model_promotion_decision_id = models.CharField(max_length=64, blank=True)
    pit_manifest_id = models.CharField(max_length=300)
    pit_manifest_version = models.CharField(max_length=300)
    pit_manifest_hash = models.CharField(max_length=64)
    censoring_rule_version = models.CharField(max_length=300)
    published_at = models.DateTimeField()
    horizon_end = models.DateTimeField(db_index=True)
    scenario_realized = models.BooleanField()
    outcome_recorded_at = models.DateTimeField()
    outcome_evidence_valid_until = models.DateTimeField()
    available_at = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField(db_index=True)
    evidence_ref = models.CharField(max_length=300)
    member_source_hash = models.CharField(max_length=64)
    source_outcome_hash = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "signal"
        db_table = "signal_forecast_realization_receipt"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["manifest", "entry"], name="sig_r7_real_manifest_entry_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(observation_id=models.F("entry_id")),
                name="sig_r7_real_observation_entry_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(published_at__lt=models.F("horizon_end"))
                    & models.Q(horizon_end__lte=models.F("outcome_recorded_at"))
                    & models.Q(outcome_recorded_at__lte=models.F("available_at"))
                    & models.Q(available_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("outcome_evidence_valid_until"))
                ),
                name="sig_r7_real_receipt_clock_ck",
            ),
        ]
        indexes = [models.Index(fields=["manifest", "entry"], name="sig_r7_real_member_idx")]


@receiver(
    pre_delete,
    sender=ForecastRealizationSourceDefinitionModel,
    dispatch_uid="signal_forecast_realization_source_definition_no_delete",
)
@receiver(
    pre_delete,
    sender=ForecastRealizationSourceDefinitionMemberModel,
    dispatch_uid="signal_forecast_realization_source_definition_member_no_delete",
)
@receiver(
    pre_delete,
    sender=ForecastRealizationManifestModel,
    dispatch_uid="signal_forecast_realization_manifest_no_delete",
)
@receiver(
    pre_delete,
    sender=ForecastRealizationReceiptModel,
    dispatch_uid="signal_forecast_realization_receipt_no_delete",
)
def _reject_forecast_realization_delete(**kwargs: object) -> NoReturn:
    """Reject Collector and cascade deletion paths."""

    raise ValidationError("forecast realization evidence cannot be deleted")


__all__ = [
    "ForecastRealizationManifestModel",
    "ForecastRealizationReceiptModel",
    "ForecastRealizationSourceDefinitionMemberModel",
    "ForecastRealizationSourceDefinitionModel",
]
