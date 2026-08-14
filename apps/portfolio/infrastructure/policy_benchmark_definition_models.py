"""Append-only storage model for Portfolio policy-benchmark definitions."""

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
_ACTIVE_POLICY_BENCHMARK_DEFINITION_UOW: ContextVar[object | None] = ContextVar(
    "active_portfolio_policy_benchmark_definition_uow", default=None
)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_POLICY_BENCHMARK_DEFINITION_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_portfolio_policy_benchmark_definition_claim", default=None
)


@contextmanager
def _activate_policy_benchmark_definition_uow(token: object) -> Iterator[None]:
    """Activate this ledger's private unit-of-work token."""

    reset = _ACTIVE_POLICY_BENCHMARK_DEFINITION_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_POLICY_BENCHMARK_DEFINITION_UOW.reset(reset)


@contextmanager
def _claim_policy_benchmark_definition_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact repository-controlled insert."""

    if _ACTIVE_POLICY_BENCHMARK_DEFINITION_UOW.get() is not token:
        raise ValidationError("Policy-benchmark definition insert requires its private UOW.")
    reset = _ACTIVE_POLICY_BENCHMARK_DEFINITION_CLAIM.set(
        _InsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_POLICY_BENCHMARK_DEFINITION_CLAIM.reset(reset)


class PolicyBenchmarkDefinitionQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject bulk insertion, mutation, and raw deletion shortcuts."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Policy-benchmark definitions require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Policy-benchmark definitions cannot be updated.")

    def _raw_delete(self, using: str) -> NoReturn:
        raise ValidationError("Policy-benchmark definitions cannot be deleted.")


class PolicyBenchmarkDefinitionManager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> PolicyBenchmarkDefinitionQuerySet[_ModelT]:
        return PolicyBenchmarkDefinitionQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Policy-benchmark definitions require exact repository appends.")


class PortfolioPolicyBenchmarkDefinitionModel(models.Model):
    """One immutable policy-benchmark definition first winner."""

    objects: PolicyBenchmarkDefinitionManager[models.Model] = PolicyBenchmarkDefinitionManager()

    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=96)
    permission = models.CharField(max_length=32)
    definition_id = models.CharField(max_length=192)
    definition_version = models.CharField(max_length=192)
    base_currency = models.CharField(max_length=3)
    constituent_count = models.PositiveIntegerField()
    constituents_hash = models.CharField(max_length=64)
    methodology_refs_hash = models.CharField(max_length=64)
    valuation_timezone = models.CharField(max_length=192)
    valuation_cutoff = models.CharField(max_length=192)
    evaluation_window_days = models.PositiveIntegerField()
    max_price_age_seconds = models.PositiveIntegerField()
    max_fx_age_seconds = models.PositiveIntegerField()
    missing_price_policy = models.CharField(max_length=32)
    missing_fx_policy = models.CharField(max_length=32)
    blocker_codes_hash = models.CharField(max_length=64)
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    persisted_at = models.DateTimeField()
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)

    class Meta:
        app_label = "portfolio"
        db_table = "portfolio_policy_benchmark_definition"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("definition_id", "definition_version", "recorded_at"),
                name="port_pol_bench_def_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("definition_id", "definition_version"),
                name="portfolio_pol_bench_def_id_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(owner="portfolio")
                    & models.Q(artifact_type="policy_benchmark_definition")
                    & models.Q(schema="portfolio-policy-benchmark-definition.v1")
                    & models.Q(permission="definition_only")
                    & models.Q(missing_price_policy="fail_closed")
                    & models.Q(missing_fx_policy="fail_closed")
                    & models.Q(constituent_count__gt=0)
                    & models.Q(evaluation_window_days__gt=0)
                    & models.Q(max_price_age_seconds__gt=0)
                    & models.Q(max_fx_age_seconds__gt=0)
                ),
                name="portfolio_pol_bench_def_owner_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(persisted_at=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="portfolio_pol_bench_def_clock_ck",
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
        """Permit only one exact repository-claimed insert."""

        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("Policy-benchmark definitions are append-only.")
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
        """Reject raw fixture and update bypasses."""

        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("Policy-benchmark definitions are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_POLICY_BENCHMARK_DEFINITION_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_POLICY_BENCHMARK_DEFINITION_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Policy-benchmark definition requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Policy-benchmark definitions cannot be deleted.")


def _reject_policy_benchmark_definition_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject collector deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Policy-benchmark definitions cannot be deleted.")


pre_delete.connect(
    _reject_policy_benchmark_definition_delete,
    sender=PortfolioPolicyBenchmarkDefinitionModel,
    dispatch_uid="reject_portfolio_policy_benchmark_definition_delete",
    weak=False,
)


__all__ = ["PortfolioPolicyBenchmarkDefinitionModel"]
