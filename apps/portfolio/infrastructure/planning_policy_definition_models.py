"""Append-only storage model for Portfolio planning-policy definitions."""

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
_ACTIVE_PLANNING_POLICY_DEFINITION_UOW: ContextVar[object | None] = ContextVar(
    "active_portfolio_planning_policy_definition_uow", default=None
)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_PLANNING_POLICY_DEFINITION_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_portfolio_planning_policy_definition_claim", default=None
)


@contextmanager
def _activate_planning_policy_definition_uow(token: object) -> Iterator[None]:
    """Activate this ledger's private unit-of-work token."""

    reset = _ACTIVE_PLANNING_POLICY_DEFINITION_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_PLANNING_POLICY_DEFINITION_UOW.reset(reset)


@contextmanager
def _claim_planning_policy_definition_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact repository-controlled insert."""

    if _ACTIVE_PLANNING_POLICY_DEFINITION_UOW.get() is not token:
        raise ValidationError("Planning-policy definition insert requires its private UOW.")
    reset = _ACTIVE_PLANNING_POLICY_DEFINITION_CLAIM.set(
        _InsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_PLANNING_POLICY_DEFINITION_CLAIM.reset(reset)


class PlanningPolicyDefinitionQuerySet(AppendOnlyQuerySet[_ModelT]):
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
        raise ValidationError("Planning-policy definitions require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Planning-policy definitions cannot be updated.")

    def _raw_delete(self, using: str) -> NoReturn:
        raise ValidationError("Planning-policy definitions cannot be deleted.")


class PlanningPolicyDefinitionManager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> PlanningPolicyDefinitionQuerySet[_ModelT]:
        return PlanningPolicyDefinitionQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Planning-policy definitions require exact repository appends.")


class PortfolioPlanningPolicyDefinitionModel(models.Model):
    """One immutable Portfolio planning-policy definition first winner."""

    objects: PlanningPolicyDefinitionManager[models.Model] = PlanningPolicyDefinitionManager()

    owner = models.CharField(max_length=32)
    artifact_type = models.CharField(max_length=64)
    schema = models.CharField(max_length=64)
    permission = models.CharField(max_length=32)
    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    buy_lot_size = models.PositiveIntegerField()
    fee_rate = models.CharField(max_length=192)
    slippage_rate = models.CharField(max_length=192)
    min_rebalance_value = models.CharField(max_length=192)
    max_asset_weight = models.CharField(max_length=192)
    max_volume_participation = models.CharField(max_length=192)
    valid_until = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField(db_index=True)
    persisted_at = models.DateTimeField()
    canonical_payload = models.JSONField()
    identity_hash = models.CharField(max_length=64, unique=True)
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)

    class Meta:
        app_label = "portfolio"
        db_table = "portfolio_planning_policy_definition"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("policy_id", "policy_version", "recorded_at"),
                name="portfolio_plan_pol_def_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("policy_id", "policy_version"),
                name="portfolio_plan_pol_def_id_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="portfolio",
                    artifact_type="planning_policy_definition",
                    schema="portfolio-planning-policy-definition.v1",
                    permission="definition_only",
                ),
                name="portfolio_plan_pol_def_owner_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    recorded_at__lt=models.F("valid_until"),
                    persisted_at=models.F("recorded_at"),
                ),
                name="portfolio_plan_pol_def_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(buy_lot_size__gt=0),
                name="portfolio_plan_pol_def_lot_ck",
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
            raise ValidationError("Planning-policy definitions are append-only.")
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
            raise ValidationError("Planning-policy definitions are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_PLANNING_POLICY_DEFINITION_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_PLANNING_POLICY_DEFINITION_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError("Planning-policy definition requires an exact insert claim.")

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Planning-policy definitions cannot be deleted.")


def _reject_planning_policy_definition_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject collector deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Planning-policy definitions cannot be deleted.")


pre_delete.connect(
    _reject_planning_policy_definition_delete,
    sender=PortfolioPlanningPolicyDefinitionModel,
    dispatch_uid="reject_portfolio_planning_policy_definition_delete",
    weak=False,
)


__all__ = ["PortfolioPlanningPolicyDefinitionModel"]
