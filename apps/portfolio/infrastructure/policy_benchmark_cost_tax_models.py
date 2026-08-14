"""Append-only model for Portfolio benchmark cost/tax methodologies."""

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
_ACTIVE_COST_TAX_UOW: ContextVar[object | None] = ContextVar(
    "active_portfolio_cost_tax_uow", default=None
)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_COST_TAX_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_portfolio_cost_tax_claim", default=None
)


@contextmanager
def _activate_cost_tax_uow(token: object) -> Iterator[None]:
    """Activate this ledger's private unit-of-work token."""

    reset = _ACTIVE_COST_TAX_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_COST_TAX_UOW.reset(reset)


@contextmanager
def _claim_cost_tax_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact repository-controlled insert."""

    if _ACTIVE_COST_TAX_UOW.get() is not token:
        raise ValidationError("Cost/tax insert requires its private UOW.")
    reset = _ACTIVE_COST_TAX_CLAIM.set(
        _InsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_COST_TAX_CLAIM.reset(reset)


class CostTaxQuerySet(AppendOnlyQuerySet[_ModelT]):
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
        raise ValidationError("Cost/tax methodologies require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Cost/tax methodologies cannot be updated.")

    def _raw_delete(self, using: str) -> NoReturn:
        raise ValidationError("Cost/tax methodologies cannot be deleted.")


class CostTaxManager(AppendOnlyManager[_ModelT]):
    """Expose append-only guards through every manager path."""

    def get_queryset(self) -> CostTaxQuerySet[_ModelT]:
        return CostTaxQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Cost/tax methodologies require exact repository appends.")


class PortfolioPolicyBenchmarkCostTaxModel(models.Model):
    """One immutable benchmark cost/tax methodology first winner."""

    objects: CostTaxManager[models.Model] = CostTaxManager()
    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=96)
    permission = models.CharField(max_length=32)
    methodology_id = models.CharField(max_length=192)
    methodology_version = models.CharField(max_length=192)
    source_count = models.PositiveIntegerField()
    fee_source_count = models.PositiveIntegerField()
    tax_source_count = models.PositiveIntegerField()
    sources_hash = models.CharField(max_length=64)
    charge_rule_count = models.PositiveIntegerField()
    fee_rule_count = models.PositiveIntegerField()
    tax_rule_count = models.PositiveIntegerField()
    charge_rules_hash = models.CharField(max_length=64)
    business_date_policy = models.CharField(max_length=64)
    currency_basis_policy = models.CharField(max_length=64)
    currency_conversion_policy = models.CharField(max_length=64)
    missing_fx_policy = models.CharField(max_length=32)
    unknown_asset_policy = models.CharField(max_length=32)
    unknown_fee_policy = models.CharField(max_length=32)
    unknown_tax_policy = models.CharField(max_length=32)
    missing_source_policy = models.CharField(max_length=32)
    source_failure_policy = models.CharField(max_length=32)
    estimation_policy = models.CharField(max_length=32)
    silent_zero_policy = models.CharField(max_length=32)
    duplicate_charge_policy = models.CharField(max_length=32)
    cash_dividend_charge_policy = models.CharField(max_length=32)
    cash_dividend_payment_policy = models.CharField(max_length=48)
    corporate_action_charge_policy = models.CharField(max_length=32)
    already_net_amount_policy = models.CharField(max_length=32)
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    persisted_at = models.DateTimeField()
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)

    class Meta:
        app_label = "portfolio"
        db_table = "portfolio_policy_benchmark_cost_tax"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("methodology_id", "methodology_version", "recorded_at"),
                name="port_bench_costtax_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("methodology_id", "methodology_version"),
                name="port_bench_costtax_id_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(owner="portfolio")
                    & models.Q(artifact_type="cost_tax_methodology")
                    & models.Q(schema="portfolio-policy-benchmark-cost-tax.v1")
                    & models.Q(permission="methodology_definition_only")
                    & models.Q(business_date_policy="benchmark_trading_calendar_date")
                    & models.Q(currency_basis_policy="event_gross_currency")
                    & models.Q(currency_conversion_policy="exact_benchmark_fx_fixing_only")
                    & models.Q(missing_fx_policy="fail_closed")
                    & models.Q(unknown_asset_policy="fail_closed")
                    & models.Q(unknown_fee_policy="fail_closed")
                    & models.Q(unknown_tax_policy="fail_closed")
                    & models.Q(missing_source_policy="fail_closed")
                    & models.Q(source_failure_policy="block")
                    & models.Q(estimation_policy="prohibited")
                    & models.Q(silent_zero_policy="prohibited")
                    & models.Q(duplicate_charge_policy="block")
                    & models.Q(cash_dividend_charge_policy="entitlement_once")
                    & models.Q(cash_dividend_payment_policy="settlement_only_no_second_charge")
                    & models.Q(corporate_action_charge_policy="exact_event_once")
                    & models.Q(already_net_amount_policy="block")
                ),
                name="port_bench_costtax_owner_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(source_count__gte=2)
                    & models.Q(fee_source_count__gt=0)
                    & models.Q(tax_source_count__gt=0)
                    & models.Q(source_count=models.F("charge_rule_count"))
                    & models.Q(fee_source_count=models.F("fee_rule_count"))
                    & models.Q(tax_source_count=models.F("tax_rule_count"))
                ),
                name="port_bench_costtax_shape_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(persisted_at=models.F("recorded_at"))
                    & models.Q(recorded_at__lt=models.F("valid_until"))
                ),
                name="port_bench_costtax_clock_ck",
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
            raise ValidationError("Cost/tax methodologies are append-only.")
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
            raise ValidationError("Cost/tax methodologies are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_COST_TAX_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_COST_TAX_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Cost/tax methodology requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Cost/tax methodologies cannot be deleted.")


def _reject_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject collector deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Cost/tax methodologies cannot be deleted.")


pre_delete.connect(
    _reject_delete,
    sender=PortfolioPolicyBenchmarkCostTaxModel,
    dispatch_uid="reject_portfolio_policy_benchmark_cost_tax_delete",
    weak=False,
)

__all__ = ["PortfolioPolicyBenchmarkCostTaxModel"]
