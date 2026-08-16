"""Append-only model for Portfolio benchmark corporate-action methodologies."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, Self, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_CORPORATE_ACTION_UOW: ContextVar[object | None] = ContextVar(
    "active_portfolio_corporate_action_uow", default=None
)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_CORPORATE_ACTION_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_portfolio_corporate_action_claim", default=None
)


@contextmanager
def _activate_corporate_action_uow(token: object) -> Iterator[None]:
    """Activate this ledger's private unit-of-work token."""

    reset = _ACTIVE_CORPORATE_ACTION_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_CORPORATE_ACTION_UOW.reset(reset)


@contextmanager
def _claim_corporate_action_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact repository-controlled insert."""

    if _ACTIVE_CORPORATE_ACTION_UOW.get() is not token:
        raise ValidationError("Corporate-action insert requires its private UOW.")
    reset = _ACTIVE_CORPORATE_ACTION_CLAIM.set(
        _InsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_CORPORATE_ACTION_CLAIM.reset(reset)


class CorporateActionQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject bulk insertion, mutation, and deletion shortcuts."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Corporate-action methodologies require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Corporate-action methodologies cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("Corporate-action methodologies cannot be deleted.")


class CorporateActionManager(AppendOnlyManager[_ModelT]):
    """Expose append-only guards through every manager path."""

    def get_queryset(self) -> CorporateActionQuerySet[_ModelT]:
        return CorporateActionQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Corporate-action methodologies require exact repository appends.")


class PortfolioPolicyBenchmarkCorporateActionModel(models.Model):
    """One immutable corporate-action methodology first winner."""

    objects: CorporateActionManager[Self] = CorporateActionManager()
    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=96)
    permission = models.CharField(max_length=32)
    methodology_id = models.CharField(max_length=192)
    methodology_version = models.CharField(max_length=192)
    security_identifier_namespace = models.CharField(max_length=192)
    timezone_name = models.CharField(max_length=192)
    business_date_cutoff_local = models.CharField(max_length=32)
    business_date_policy = models.CharField(max_length=64)
    non_business_date_policy = models.CharField(max_length=32)
    source_count = models.PositiveIntegerField()
    sources_hash = models.CharField(max_length=64)
    event_rule_count = models.PositiveIntegerField()
    event_rules_hash = models.CharField(max_length=64)
    source_failure_policy = models.CharField(max_length=32)
    missing_action_policy = models.CharField(max_length=32)
    unknown_event_type_policy = models.CharField(max_length=32)
    price_input_adjustment_basis = models.CharField(max_length=32)
    adjustment_application_policy = models.CharField(max_length=32)
    duplicate_event_policy = models.CharField(max_length=32)
    pre_adjusted_input_policy = models.CharField(max_length=32)
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    persisted_at = models.DateTimeField()
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)

    class Meta:
        app_label = "portfolio"
        db_table = "portfolio_policy_benchmark_corporate_action"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("methodology_id", "methodology_version", "recorded_at"),
                name="port_bench_corpact_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("methodology_id", "methodology_version"),
                name="portfolio_bench_corpact_id_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(owner="portfolio")
                    & models.Q(artifact_type="corporate_action_methodology")
                    & models.Q(schema="portfolio-policy-benchmark-corporate-action.v1")
                    & models.Q(permission="methodology_definition_only")
                    & models.Q(business_date_policy="issuer_market_local_date")
                    & models.Q(non_business_date_policy="block")
                    & models.Q(source_count__gt=0)
                    & models.Q(event_rule_count=5)
                    & models.Q(source_failure_policy="block")
                    & models.Q(missing_action_policy="fail_closed")
                    & models.Q(unknown_event_type_policy="fail_closed")
                    & models.Q(price_input_adjustment_basis="unadjusted")
                    & models.Q(adjustment_application_policy="exact_event_once")
                    & models.Q(duplicate_event_policy="block")
                    & models.Q(pre_adjusted_input_policy="block")
                ),
                name="portfolio_bench_corpact_owner_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(persisted_at=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="portfolio_bench_corpact_clock_ck",
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
            raise ValidationError("Corporate-action methodologies are append-only.")
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
            raise ValidationError("Corporate-action methodologies are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_CORPORATE_ACTION_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_CORPORATE_ACTION_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Corporate-action methodology requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Corporate-action methodologies cannot be deleted.")


def _reject_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject collector deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Corporate-action methodologies cannot be deleted.")


pre_delete.connect(
    _reject_delete,
    sender=PortfolioPolicyBenchmarkCorporateActionModel,
    dispatch_uid="reject_portfolio_policy_benchmark_corporate_action_delete",
    weak=False,
)

__all__ = ["PortfolioPolicyBenchmarkCorporateActionModel"]
