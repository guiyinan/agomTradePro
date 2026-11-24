"""Portfolio's immutable live benchmark epochs, source files and daily unit ledger."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, NoReturn, Self, TypeVar
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_Row = TypeVar("_Row", bound=models.Model)

_write_claim: ContextVar[models.Model | None] = ContextVar("benchmark_day_write", default=None)


@contextmanager
def _claim_valuation_insert(row: models.Model) -> Iterator[None]:
    token = _write_claim.set(row)
    try:
        yield
    finally:
        _write_claim.reset(token)


class _ValuationRows(AppendOnlyQuerySet[_Row]):
    def bulk_create(
        self,
        objs: Iterable[_Row],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("benchmark ledger requires the owner publication workflow")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("benchmark ledger updates are forbidden")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("benchmark ledger deletion is forbidden")


class _ValuationManager(AppendOnlyManager[_Row]):
    def get_queryset(self) -> _ValuationRows[_Row]:
        """Return a guarded ledger queryset."""
        return _ValuationRows(self.model, using=self._db)


class _ImmutableValuation(models.Model):
    objects: _ValuationManager[Self] = _ValuationManager()

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Restrict inserts to the exact owner-controlled row."""
        if (
            _write_claim.get() is not self
            or not self._state.adding
            or not kwargs.get("force_insert")
        ):
            raise ValidationError("benchmark ledger accepts owner-authorized new entries only")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        """Reject instance deletion of immutable valuation facts."""
        raise ValidationError("benchmark ledger deletion is forbidden")


class PortfolioBenchmarkValuationEpochModel(_ImmutableValuation):
    """Configuration and scope chosen prospectively before the first closing fixing."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    account_namespace = models.CharField(max_length=128)
    account_id = models.CharField(max_length=128)
    owner_user_id = models.PositiveBigIntegerField()
    sequence = models.PositiveIntegerField()
    scope_hash = models.CharField(max_length=64)
    definition_id = models.CharField(max_length=192)
    policy_id = models.CharField(max_length=192)
    configuration_hash = models.CharField(max_length=64)
    started_at = models.DateTimeField()
    content_hash = models.CharField(max_length=64, unique=True)

    class Meta(_ImmutableValuation.Meta):
        app_label = "portfolio"
        db_table = "portfolio_benchmark_valuation_epoch"
        constraints = [
            models.UniqueConstraint(
                fields=["account_namespace", "account_id", "sequence"],
                name="pf_bench_val_epoch_seq",
            )
        ]


class PortfolioBenchmarkDailyValuationModel(_ImmutableValuation):
    """One accepted original day packet and its reproducible daily closing balances."""

    epoch = models.ForeignKey(
        PortfolioBenchmarkValuationEpochModel, on_delete=models.PROTECT, related_name="closes"
    )
    version = models.PositiveIntegerField()
    observation_date = models.DateField()
    observed_at = models.DateTimeField()
    recorded_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    snapshot_id = models.PositiveBigIntegerField()
    reconciliation_hash = models.CharField(max_length=64)
    original_statement = models.BinaryField()
    original_hash = models.CharField(max_length=64)
    fixing_hash = models.CharField(max_length=64)
    predecessor_hash = models.CharField(max_length=64, blank=True)
    balance = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)

    class Meta(_ImmutableValuation.Meta):
        app_label = "portfolio"
        db_table = "portfolio_benchmark_daily_valuation"
        constraints = [
            models.UniqueConstraint(fields=["epoch", "version"], name="pf_bench_day_seq"),
            models.UniqueConstraint(fields=["epoch", "observation_date"], name="pf_bench_day_date"),
        ]
