"""Append-only Broker owner ledger for R8 monitoring reconciliation receipts."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, NoReturn, TypeVar, cast

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_BROKER_MONITORING_UOW: ContextVar[object | None] = ContextVar(
    "active_r8_broker_monitoring_uow",
    default=None,
)


@dataclass(frozen=True)
class _BrokerMonitoringInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_BROKER_MONITORING_INSERT_CLAIM: ContextVar[_BrokerMonitoringInsertClaim | None] = (
    ContextVar("active_r8_broker_monitoring_insert_claim", default=None)
)


@contextmanager
def _activate_r8_broker_monitoring_uow(token: object) -> Iterator[None]:
    """Activate one composition-owned Broker transaction capability."""

    reset = _ACTIVE_BROKER_MONITORING_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_BROKER_MONITORING_UOW.reset(reset)


def _require_active_r8_broker_monitoring_uow() -> object:
    """Require the private owner transaction before an append."""

    token = _ACTIVE_BROKER_MONITORING_UOW.get()
    if token is None:
        raise ValidationError("R8 Broker monitoring evidence requires an active unit of work.")
    return token


@contextmanager
def _claim_r8_broker_monitoring_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Authorize one exact model/value insert inside the active owner UoW."""

    if _ACTIVE_BROKER_MONITORING_UOW.get() is not token:
        raise ValidationError("R8 Broker monitoring insert requires its unit of work.")
    claim = _BrokerMonitoringInsertClaim(
        token=token,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset = _ACTIVE_BROKER_MONITORING_INSERT_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_BROKER_MONITORING_INSERT_CLAIM.reset(reset)


class R8BrokerMonitoringAppendOnlyQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject bulk and private ORM mutation paths around exact inserts."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject every bulk insertion route."""

        raise ValidationError("R8 Broker monitoring evidence requires exact appends.")

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        """Reject lookup-or-write shortcuts."""

        raise ValidationError("R8 Broker monitoring get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        """Reject update-or-insert shortcuts."""

        raise ValidationError("R8 Broker monitoring update_or_create is forbidden.")

    def _update(self, values: object) -> NoReturn:
        """Reject Django's private SQL update path."""

        raise ValidationError("R8 Broker monitoring evidence cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        """Reject Django's private fast-delete path."""

        raise ValidationError("R8 Broker monitoring evidence cannot be deleted.")

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
        """Allow only one exact repository-claimed insert."""

        items = list(objs)
        if (
            len(items) != 1
            or raw
            or on_conflict is not None
            or update_fields is not None
            or unique_fields is not None
            or (using is not None and using != self.db)
        ):
            raise ValidationError("R8 Broker monitoring private insert is forbidden.")
        _require_exact_r8_broker_monitoring_insert_claim(items[0])
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
        """Reject Django's private bulk insertion path."""

        raise ValidationError("R8 Broker monitoring private bulk insert is forbidden.")


class R8BrokerMonitoringAppendOnlyManager(AppendOnlyManager[_ModelT]):
    """Expose the fully guarded Broker monitoring QuerySet."""

    def get_queryset(self) -> R8BrokerMonitoringAppendOnlyQuerySet[_ModelT]:
        """Return a guarded QuerySet for this database alias."""

        return R8BrokerMonitoringAppendOnlyQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject manager-level bulk insertion."""

        raise ValidationError("R8 Broker monitoring evidence requires exact appends.")

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        """Reject manager-level lookup-or-write."""

        raise ValidationError("R8 Broker monitoring get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        """Reject manager-level update-or-insert."""

        raise ValidationError("R8 Broker monitoring update_or_create is forbidden.")

    def raw(
        self,
        raw_query: str,
        params: Iterable[object] = (),
        translations: Mapping[str, str] | None = None,
        using: str | None = None,
    ) -> NoReturn:
        """Reject raw manager SQL."""

        raise ValidationError("R8 Broker monitoring raw manager queries are forbidden.")


class R8BrokerMonitoringAppendOnlyModel(models.Model):
    """Reject every unclaimed insert and all mutation/deletion paths."""

    objects = R8BrokerMonitoringAppendOnlyManager()

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
        """Allow only one exact claimed initial append."""

        if force_update or update_fields is not None or not self._state.adding:
            raise ValidationError("R8 Broker monitoring evidence is append-only.")
        _require_exact_r8_broker_monitoring_insert_claim(self)
        super().save(
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Guard raw fixtures and direct save_base mutation paths."""

        if raw or force_update or update_fields is not None or not self._state.adding:
            raise ValidationError("R8 Broker monitoring evidence is append-only.")
        _require_exact_r8_broker_monitoring_insert_claim(self)
        super().save_base(
            raw=False,
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def delete(
        self,
        using: Any | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("R8 Broker monitoring evidence is append-only.")


def _require_exact_r8_broker_monitoring_insert_claim(model: models.Model) -> None:
    claim = _ACTIVE_BROKER_MONITORING_INSERT_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_BROKER_MONITORING_UOW.get()
        or type(model) is not claim.model_type
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("R8 Broker monitoring evidence requires an exact insert claim.")


class R8BrokerMonitoringPeriodReceiptModel(R8BrokerMonitoringAppendOnlyModel):
    """One immutable complete Broker reconciliation period receipt."""

    receipt_id = models.CharField(max_length=96, primary_key=True)
    receipt_version = models.CharField(max_length=96)
    definition_id = models.CharField(max_length=96)
    definition_version = models.CharField(max_length=96)
    definition_hash = models.CharField(max_length=64)
    definition_payload = models.JSONField()
    source_receipt_id = models.CharField(max_length=128)
    source_receipt_version = models.CharField(max_length=96)
    source_receipt_hash = models.CharField(max_length=64)
    source_receipt_payload = models.JSONField()
    result_id = models.CharField(max_length=192)
    result_hash = models.CharField(max_length=64)
    portfolio_receipt_id = models.CharField(max_length=192)
    portfolio_receipt_version = models.CharField(max_length=128)
    portfolio_receipt_hash = models.CharField(max_length=64)
    calendar_id = models.CharField(max_length=192)
    calendar_version = models.CharField(max_length=128)
    calendar_hash = models.CharField(max_length=64)
    period_id = models.CharField(max_length=192)
    period_start_at = models.DateTimeField()
    period_end_at = models.DateTimeField()
    planning_reference_id = models.CharField(max_length=192)
    planning_reference_version = models.CharField(max_length=128)
    planning_reference_hash = models.CharField(max_length=64)
    reconciliation_manifest_id = models.CharField(max_length=192)
    reconciliation_manifest_version = models.CharField(max_length=128)
    reconciliation_manifest_hash = models.CharField(max_length=64)
    source_observed_at = models.DateTimeField()
    source_available_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    total_cost_amount = models.DecimalField(max_digits=38, decimal_places=12)
    total_cost_notional = models.DecimalField(max_digits=38, decimal_places=12)
    adverse_slippage_amount = models.DecimalField(max_digits=38, decimal_places=12)
    adverse_slippage_notional = models.DecimalField(max_digits=38, decimal_places=12)
    reconciliation_break_count = models.PositiveBigIntegerField()
    reconciliation_comparison_count = models.PositiveBigIntegerField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R8BrokerMonitoringAppendOnlyModel.Meta):
        app_label = "broker_execution"
        db_table = "broker_execution_r8_monitoring_period_receipt"
        constraints = [
            models.UniqueConstraint(
                fields=("definition_id", "definition_version"),
                name="be_r8_mon_definition_uq",
            ),
            models.UniqueConstraint(
                fields=("source_receipt_id", "source_receipt_version"),
                name="be_r8_mon_source_uq",
            ),
            models.UniqueConstraint(
                fields=("result_id", "calendar_id", "period_id"),
                name="be_r8_mon_period_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(period_start_at__lt=models.F("period_end_at"))
                    & models.Q(source_observed_at__gte=models.F("period_start_at"))
                    & models.Q(source_observed_at__lte=models.F("period_end_at"))
                    & models.Q(source_available_at__gte=models.F("source_observed_at"))
                    & models.Q(recorded_at__gte=models.F("source_available_at"))
                    & models.Q(valid_until__gt=models.F("recorded_at"))
                ),
                name="be_r8_mon_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(total_cost_amount__gte=0)
                    & models.Q(total_cost_notional__gt=0)
                    & models.Q(total_cost_amount__lte=models.F("total_cost_notional"))
                    & models.Q(adverse_slippage_amount__gte=0)
                    & models.Q(adverse_slippage_notional__gt=0)
                    & models.Q(adverse_slippage_amount__lte=models.F("adverse_slippage_notional"))
                    & models.Q(reconciliation_comparison_count__gt=0)
                    & models.Q(
                        reconciliation_break_count__lte=models.F("reconciliation_comparison_count")
                    )
                ),
                name="be_r8_mon_ratio_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    receipt_version="broker-r8-monitoring-period-receipt.v1",
                    definition_version="broker-r8-reconciliation-definition.v1",
                    source_receipt_version="broker-r8-reconciliation-source.v1",
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="be_r8_mon_safe_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("result_id", "calendar_id", "period_id", "recorded_at"),
                name="be_r8_mon_target_pit_ix",
            )
        ]


@receiver(
    pre_delete,
    sender=R8BrokerMonitoringPeriodReceiptModel,
    weak=False,
)
def _reject_r8_broker_monitoring_receipt_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject Collector, cascade, and direct deletion paths."""

    raise ValidationError("R8 Broker monitoring owner receipts cannot be deleted.")


__all__ = [
    "R8BrokerMonitoringPeriodReceiptModel",
]
