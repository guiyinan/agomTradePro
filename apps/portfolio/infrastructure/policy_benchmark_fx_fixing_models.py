"""Append-only model for Portfolio benchmark FX-fixing definitions."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_FX_UOW: ContextVar[object | None] = ContextVar(
    "active_portfolio_fx_fixing_uow", default=None
)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_FX_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_portfolio_fx_fixing_claim", default=None
)


@contextmanager
def _activate_fx_uow(token: object) -> Iterator[None]:
    """Activate this ledger's private UOW."""
    reset = _ACTIVE_FX_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_FX_UOW.reset(reset)


@contextmanager
def _claim_fx_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact repository insert."""
    if _ACTIVE_FX_UOW.get() is not token:
        raise ValidationError("FX-fixing insert requires its private UOW.")
    reset = _ACTIVE_FX_CLAIM.set(
        _InsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_FX_CLAIM.reset(reset)


class FxFixingQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject bulk mutation paths."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("FX-fixing definitions require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("FX-fixing definitions cannot be updated.")

    def _raw_delete(self, using: str) -> NoReturn:
        raise ValidationError("FX-fixing definitions cannot be deleted.")


class FxFixingManager(AppendOnlyManager[_ModelT]):
    """Expose append-only guards."""

    def get_queryset(self) -> FxFixingQuerySet[_ModelT]:
        return FxFixingQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("FX-fixing definitions require exact repository appends.")


class PortfolioPolicyBenchmarkFxFixingModel(models.Model):
    """One immutable benchmark FX-fixing definition first winner."""

    objects: FxFixingManager[models.Model] = FxFixingManager()
    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=96)
    permission = models.CharField(max_length=32)
    methodology_id = models.CharField(max_length=192)
    methodology_version = models.CharField(max_length=192)
    base_currency = models.CharField(max_length=3)
    quote_currency = models.CharField(max_length=3)
    currency_pair = models.CharField(max_length=7)
    fixing_convention = models.CharField(max_length=32)
    inverse_rate_allowed = models.BooleanField()
    timezone_name = models.CharField(max_length=192)
    valuation_cutoff_local = models.CharField(max_length=32)
    source_count = models.PositiveIntegerField()
    sources_hash = models.CharField(max_length=64)
    stale_after_seconds = models.PositiveIntegerField()
    triangulation_policy = models.CharField(max_length=32)
    triangulation_currency = models.CharField(max_length=3, null=True, blank=True)
    source_failure_policy = models.CharField(max_length=32)
    missing_fx_policy = models.CharField(max_length=32)
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    persisted_at = models.DateTimeField()
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)

    class Meta:
        app_label = "portfolio"
        db_table = "portfolio_policy_benchmark_fx_fixing"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("methodology_id", "methodology_version", "recorded_at"),
                name="port_bench_fx_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("methodology_id", "methodology_version"), name="portfolio_bench_fx_id_uq"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(owner="portfolio")
                    & models.Q(artifact_type="fx_fixing_methodology")
                    & models.Q(schema="portfolio-policy-benchmark-fx-fixing.v1")
                    & models.Q(permission="methodology_definition_only")
                    & models.Q(source_count__gt=0)
                    & models.Q(stale_after_seconds__gt=0)
                    & models.Q(triangulation_policy="prohibited")
                    & models.Q(triangulation_currency__isnull=True)
                    & models.Q(source_failure_policy="block")
                    & models.Q(missing_fx_policy="fail_closed")
                ),
                name="portfolio_bench_fx_owner_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(persisted_at=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="portfolio_bench_fx_clock_ck",
            ),
        ]

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Permit only an exact claimed insert."""
        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("FX-fixing definitions are append-only.")
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
        """Reject raw/update bypasses."""
        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("FX-fixing definitions are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_FX_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_FX_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("FX-fixing definition requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""
        raise ValidationError("FX-fixing definitions cannot be deleted.")


def _reject_delete(
    sender: type[models.Model], instance: models.Model, using: str, origin: object, **kwargs: object
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("FX-fixing definitions cannot be deleted.")


pre_delete.connect(
    _reject_delete,
    sender=PortfolioPolicyBenchmarkFxFixingModel,
    dispatch_uid="reject_portfolio_policy_benchmark_fx_fixing_delete",
    weak=False,
)
__all__ = ["PortfolioPolicyBenchmarkFxFixingModel"]
