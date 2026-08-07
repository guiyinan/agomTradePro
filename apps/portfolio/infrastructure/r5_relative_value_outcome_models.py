"""Strict append-only ORM ledger for Portfolio-owned R5 outcomes."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_R5_OUTCOME_UNIT_OF_WORK: ContextVar[object | None] = ContextVar(
    "active_portfolio_r5_outcome_unit_of_work",
    default=None,
)


@dataclass(frozen=True)
class _R5OutcomeInsertClaim:
    unit_of_work_token: object
    command_hash: str
    draft_hash: str
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_R5_OUTCOME_INSERT_CLAIM: ContextVar[_R5OutcomeInsertClaim | None] = ContextVar(
    "active_portfolio_r5_outcome_insert_claim",
    default=None,
)


@contextmanager
def _activate_r5_outcome_unit_of_work(token: object) -> Iterator[None]:
    """Activate one private composition-root persistence boundary."""

    reset_token = _ACTIVE_R5_OUTCOME_UNIT_OF_WORK.set(token)
    try:
        yield
    finally:
        _ACTIVE_R5_OUTCOME_UNIT_OF_WORK.reset(reset_token)


@contextmanager
def _claim_r5_outcome_insert(
    *,
    token: object,
    command_hash: str,
    draft_hash: str,
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Authorize exactly one immutable outcome/value append."""

    if _ACTIVE_R5_OUTCOME_UNIT_OF_WORK.get() is not token:
        raise ValidationError("R5 outcome insert requires its repository unit of work.")
    claim = _R5OutcomeInsertClaim(
        unit_of_work_token=token,
        command_hash=command_hash,
        draft_hash=draft_hash,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset_token = _ACTIVE_R5_OUTCOME_INSERT_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_R5_OUTCOME_INSERT_CLAIM.reset(reset_token)


class R5OutcomeAppendOnlyQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject bulk insertion shortcuts for exact R5 outcome evidence."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject plain and conflict-aware bulk insertion."""

        raise ValidationError("R5 Portfolio outcome evidence requires exact appends.")


class R5OutcomeAppendOnlyManager(AppendOnlyManager[_ModelT]):
    """Expose identical guards through default and base managers."""

    def get_queryset(self) -> R5OutcomeAppendOnlyQuerySet[_ModelT]:
        """Return the R5 outcome-specific guarded QuerySet."""

        return R5OutcomeAppendOnlyQuerySet(self.model, using=self._db)

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

        raise ValidationError("R5 Portfolio outcome evidence requires exact appends.")


class R5OutcomeAppendOnlyModel(models.Model):
    """Permit only a claimed database-assigned-primary-key insert."""

    objects = R5OutcomeAppendOnlyManager()

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
        """Reject every unclaimed insert and every update path."""

        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("R5 Portfolio outcome evidence is append-only.")
        self._require_exact_insert_claim()
        super().save(force_insert=force_insert, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Guard raw and direct instance ``save_base`` mutation paths."""

        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("R5 Portfolio outcome evidence is append-only.")
        self._require_exact_insert_claim()
        super().save_base(
            raw=False,
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def _require_exact_insert_claim(self) -> None:
        """Fail unless the active claim matches this exact payload."""

        claim = _ACTIVE_R5_OUTCOME_INSERT_CLAIM.get()
        if (
            claim is None
            or claim.unit_of_work_token is not _ACTIVE_R5_OUTCOME_UNIT_OF_WORK.get()
            or getattr(self, "command_hash", None) != claim.command_hash
            or getattr(self, "draft_hash", None) != claim.draft_hash
            or any(
                getattr(self, field_name) != value for field_name, value in claim.expected_values
            )
        ):
            raise ValidationError(
                "R5 Portfolio outcome evidence requires an exact repository insert claim."
            )

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion of audit evidence."""

        raise ValidationError("R5 Portfolio outcome evidence cannot be deleted.")


class PortfolioR5RelativeValueOutcomeModel(R5OutcomeAppendOnlyModel):
    """One immutable realized outcome with string-only cross-owner references."""

    outcome_id = models.CharField(max_length=192)
    outcome_version = models.CharField(max_length=96)
    owner = models.CharField(max_length=32, default="portfolio")
    owner_record_id = models.CharField(max_length=300)
    owner_record_version = models.CharField(max_length=300)
    owner_record_hash = models.CharField(max_length=64)
    observation_id = models.CharField(max_length=300)
    fixed_income_result_id = models.CharField(max_length=192)
    fixed_income_result_version = models.CharField(max_length=96)
    fixed_income_result_record_hash = models.CharField(max_length=64)
    fixed_income_owner_seal_hash = models.CharField(max_length=64)
    selection_as_of = models.DateTimeField(db_index=True)
    outcome_observed_at = models.DateTimeField(db_index=True)
    outcome_available_at = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    target_gross_return = models.DecimalField(max_digits=38, decimal_places=18)
    target_cost = models.DecimalField(max_digits=38, decimal_places=18)
    benchmark_gross_return = models.DecimalField(max_digits=38, decimal_places=18)
    benchmark_cost = models.DecimalField(max_digits=38, decimal_places=18)
    target_maximum_drawdown = models.DecimalField(max_digits=38, decimal_places=18)
    benchmark_maximum_drawdown = models.DecimalField(max_digits=38, decimal_places=18)
    capacity_utilization = models.DecimalField(max_digits=38, decimal_places=18)
    liquidity_breached = models.BooleanField()
    realized_credit_loss = models.DecimalField(max_digits=38, decimal_places=18)
    command_hash = models.CharField(max_length=64)
    draft_hash = models.CharField(max_length=64)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "portfolio"
        db_table = "portfolio_r5_relative_value_outcome"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["outcome_id", "outcome_version"],
                name="pf_r5_outcome_identity_uq",
            ),
            models.UniqueConstraint(
                fields=["owner_record_id", "owner_record_version"],
                name="pf_r5_outcome_owner_uq",
            ),
            models.UniqueConstraint(
                fields=["observation_id"],
                name="pf_r5_outcome_observation_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(outcome_observed_at__gt=models.F("selection_as_of"))
                    & models.Q(outcome_available_at__gte=models.F("outcome_observed_at"))
                    & models.Q(recorded_at__gte=models.F("outcome_available_at"))
                    & models.Q(valid_until__gt=models.F("recorded_at"))
                ),
                name="pf_r5_outcome_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="portfolio",
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="pf_r5_outcome_safety_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(target_cost__gte=0)
                    & models.Q(benchmark_cost__gte=0)
                    & models.Q(capacity_utilization__gte=0)
                    & models.Q(realized_credit_loss__gte=0)
                ),
                name="pf_r5_outcome_nonneg_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(target_maximum_drawdown__gte=0)
                    & models.Q(target_maximum_drawdown__lte=1)
                    & models.Q(benchmark_maximum_drawdown__gte=0)
                    & models.Q(benchmark_maximum_drawdown__lte=1)
                ),
                name="pf_r5_outcome_drawdown_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["owner_record_id", "owner_record_version"],
                name="pf_r5_outcome_owner_idx",
            ),
            models.Index(
                fields=["fixed_income_result_id", "fixed_income_result_version"],
                name="pf_r5_outcome_fi_idx",
            ),
        ]


__all__ = ["PortfolioR5RelativeValueOutcomeModel"]
