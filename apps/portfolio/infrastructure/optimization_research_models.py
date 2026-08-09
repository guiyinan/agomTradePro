"""Append-only ORM tables for governed optimization results and lifecycle."""

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
_ACTIVE_OPTIMIZATION_RESEARCH_UOW: ContextVar[object | None] = ContextVar(
    "active_governed_optimization_research_uow",
    default=None,
)


@dataclass(frozen=True)
class _OptimizationInsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_OPTIMIZATION_INSERT_CLAIM: ContextVar[_OptimizationInsertClaim | None] = ContextVar(
    "active_governed_optimization_insert_claim", default=None
)


@contextmanager
def _activate_governed_optimization_uow(token: object) -> Iterator[None]:
    """Activate one composition-owned transaction boundary."""

    reset = _ACTIVE_OPTIMIZATION_RESEARCH_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_OPTIMIZATION_RESEARCH_UOW.reset(reset)


def _require_active_governed_optimization_uow() -> object:
    """Require an active shared transaction before an authoritative read."""

    token = _ACTIVE_OPTIMIZATION_RESEARCH_UOW.get()
    if token is None:
        raise ValidationError("Governed optimization evidence requires an active unit of work.")
    return token


@contextmanager
def _claim_governed_optimization_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Authorize one exact model/value insert inside the shared UoW."""

    if _ACTIVE_OPTIMIZATION_RESEARCH_UOW.get() is not token:
        raise ValidationError("Governed optimization insert requires its unit of work.")
    claim = _OptimizationInsertClaim(
        token=token,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset = _ACTIVE_OPTIMIZATION_INSERT_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_OPTIMIZATION_INSERT_CLAIM.reset(reset)


class OptimizationAppendOnlyQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject bulk and private ORM shortcuts around exact claimed inserts."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject every bulk insertion route, including related managers."""

        raise ValidationError("Optimization research evidence requires exact appends.")

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        """Reject lookup-or-write paths even when an existing row would be returned."""

        raise ValidationError("Optimization research get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        """Reject every update-or-insert shortcut."""

        raise ValidationError("Optimization research update_or_create is forbidden.")

    def _update(self, values: object) -> NoReturn:
        """Reject Django's private SQL update entry point."""

        raise ValidationError("Optimization research evidence cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        """Reject Django's private fast-delete entry point."""

        raise ValidationError("Optimization research evidence cannot be deleted.")

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
        """Allow only the one exact insert already claimed by the repository."""

        items = list(objs)
        if (
            len(items) != 1
            or raw
            or on_conflict is not None
            or update_fields is not None
            or unique_fields is not None
            or (using is not None and using != self.db)
        ):
            raise ValidationError("Optimization research private insert is forbidden.")
        _require_exact_optimization_insert_claim(items[0])
        insert = cast(
            Callable[..., list[tuple[object, ...]]],
            getattr(super(), "_insert"),  # noqa: B009 - private Django typed boundary
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

        raise ValidationError("Optimization research private bulk insert is forbidden.")


class OptimizationAppendOnlyManager(AppendOnlyManager[_ModelT]):
    """Expose guarded optimization QuerySets for every manager path."""

    def get_queryset(self) -> OptimizationAppendOnlyQuerySet[_ModelT]:
        """Return a guarded QuerySet for this database alias."""

        return OptimizationAppendOnlyQuerySet(self.model, using=self._db)

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

        raise ValidationError("Optimization research evidence requires exact appends.")

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        """Reject manager-level lookup-or-write shortcuts."""

        raise ValidationError("Optimization research get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        """Reject manager-level update-or-insert shortcuts."""

        raise ValidationError("Optimization research update_or_create is forbidden.")

    def raw(
        self,
        raw_query: str,
        params: Iterable[object] = (),
        translations: Mapping[str, str] | None = None,
        using: str | None = None,
    ) -> NoReturn:
        """Reject raw manager SQL that could bypass immutable model hooks."""

        raise ValidationError("Optimization research raw manager queries are forbidden.")


class OptimizationAppendOnlyModel(models.Model):
    """Reject instance and manager mutation of evidentiary rows."""

    objects = OptimizationAppendOnlyManager()

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
        """Allow only one claimed initial append."""

        if force_update or update_fields is not None or not self._state.adding:
            raise ValidationError("Optimization research evidence is append-only.")
        _require_exact_optimization_insert_claim(self)
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
        """Guard raw fixtures and direct ``save_base`` mutation paths."""

        if raw or force_update or update_fields is not None or not self._state.adding:
            raise ValidationError("Optimization research evidence is append-only.")
        _require_exact_optimization_insert_claim(self)
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

        raise ValidationError("Optimization research evidence is append-only.")


def _require_exact_optimization_insert_claim(model: models.Model) -> None:
    claim = _ACTIVE_OPTIMIZATION_INSERT_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_OPTIMIZATION_RESEARCH_UOW.get()
        or type(model) is not claim.model_type
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("Optimization research evidence requires an exact insert claim.")


class GovernedOptimizationInputReceiptModel(OptimizationAppendOnlyModel):
    """Independent canonical receipt for all thirteen governed optimizer inputs."""

    receipt_id = models.CharField(max_length=64, primary_key=True)
    receipt_version = models.CharField(max_length=80)
    owner = models.CharField(max_length=32, default="portfolio")
    input_set_id = models.CharField(max_length=192, unique=True)
    input_set_version = models.CharField(max_length=128)
    contract_version = models.CharField(max_length=128)
    input_set_hash = models.CharField(max_length=64, unique=True)
    portfolio_snapshot_id = models.CharField(max_length=192)
    portfolio_snapshot_hash = models.CharField(max_length=64)
    universe_hash = models.CharField(max_length=64)
    evidence_graph_hash = models.CharField(max_length=64)
    pit_manifest_set_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    payload_count = models.PositiveSmallIntegerField()
    owner_binding_count = models.PositiveSmallIntegerField()
    promotion_count = models.PositiveSmallIntegerField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "portfolio"
        db_table = "portfolio_governed_optimization_input_receipt"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(recorded_at__gte=models.F("created_at"))
                    & models.Q(valid_until__gt=models.F("recorded_at"))
                ),
                name="pf_opt_receipt_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="portfolio",
                    payload_count=13,
                    owner_binding_count=13,
                    promotion_count=3,
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="pf_opt_receipt_safety_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["input_set_id", "recorded_at", "valid_until"],
                name="pf_opt_receipt_pit_idx",
            ),
        ]


class GovernedOptimizationResearchResultModel(OptimizationAppendOnlyModel):
    """Immutable four-candidate research comparison result."""

    result_id = models.CharField(max_length=80, primary_key=True)
    input_receipt = models.ForeignKey(
        GovernedOptimizationInputReceiptModel,
        on_delete=models.PROTECT,
        related_name="research_results",
        null=True,
        blank=True,
    )
    result_version = models.CharField(max_length=128)
    run_key = models.CharField(max_length=160)
    run_version = models.CharField(max_length=128)
    assembly_hash = models.CharField(max_length=64)
    problem_id = models.CharField(max_length=192, db_index=True)
    problem_hash = models.CharField(max_length=64)
    input_set_id = models.CharField(max_length=192, db_index=True)
    input_set_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=[("blocked", "Blocked"), ("completed", "Completed")],
        db_index=True,
    )
    selected_candidate = models.CharField(max_length=32, blank=True, default="")
    candidates = models.JSONField(default=list, blank=True)
    problem_blockers = models.JSONField(default=list, blank=True)
    evaluated_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    content_hash = models.CharField(max_length=64, unique=True)
    canonical_payload = models.JSONField()
    research_only = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "portfolio"
        db_table = "portfolio_governed_optimization_result"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["run_key", "run_version"],
                name="pf_opt_result_run_ver_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_until__gt=models.F("evaluated_at")),
                name="pf_opt_result_valid_eval_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_execute=True,
                    must_not_use_for_decision=True,
                ),
                name="pf_opt_result_research_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "-evaluated_at"],
                name="pf_opt_result_status_eval_idx",
            ),
        ]


class OptimizationResearchLifecycleEventModel(OptimizationAppendOnlyModel):
    """Immutable hash-chain event for one governed result."""

    event_id = models.CharField(max_length=80, primary_key=True)
    result = models.ForeignKey(
        GovernedOptimizationResearchResultModel,
        on_delete=models.PROTECT,
        related_name="lifecycle_events",
    )
    result_hash = models.CharField(max_length=64)
    event_type = models.CharField(
        max_length=24,
        choices=[
            ("recorded", "Recorded"),
            ("promotion_attested", "Promotion attested"),
            ("retired", "Retired"),
            ("rolled_back", "Rolled back"),
        ],
        db_index=True,
    )
    sequence = models.PositiveIntegerField()
    occurred_at = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField()
    reason_codes = models.JSONField(default=list, blank=True)
    previous_event_hash = models.CharField(max_length=64, null=True, blank=True)
    promotion_attestation = models.JSONField(null=True, blank=True)
    owner_attestation = models.JSONField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, unique=True)
    canonical_payload = models.JSONField()
    research_only = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "portfolio"
        db_table = "portfolio_optimization_lifecycle_event"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["result", "sequence"],
                name="pf_opt_lc_result_seq_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gte=1),
                name="pf_opt_lc_seq_pos_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(recorded_at__gte=models.F("occurred_at")),
                name="pf_opt_lc_record_time_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        event_type="recorded",
                        sequence=1,
                        previous_event_hash__isnull=True,
                        promotion_attestation__isnull=True,
                        owner_attestation__isnull=True,
                    )
                    | models.Q(
                        event_type="promotion_attested",
                        sequence__gt=1,
                        previous_event_hash__isnull=False,
                        promotion_attestation__isnull=False,
                        owner_attestation__isnull=True,
                    )
                    | models.Q(
                        event_type__in=["retired", "rolled_back"],
                        sequence__gt=1,
                        previous_event_hash__isnull=False,
                        promotion_attestation__isnull=True,
                        owner_attestation__isnull=False,
                    )
                ),
                name="pf_opt_lc_shape_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_execute=True,
                    must_not_use_for_decision=True,
                ),
                name="pf_opt_lc_research_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["result", "sequence"],
                name="pf_opt_lc_result_seq_idx",
            ),
        ]


@receiver(pre_delete, sender=GovernedOptimizationInputReceiptModel, weak=False)
@receiver(pre_delete, sender=GovernedOptimizationResearchResultModel, weak=False)
@receiver(pre_delete, sender=OptimizationResearchLifecycleEventModel, weak=False)
def _reject_governed_optimization_collector_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject Django Collector, cascade, and direct signal-aware deletion."""

    raise ValidationError("Optimization research evidence cannot be deleted.")


__all__ = [
    "GovernedOptimizationInputReceiptModel",
    "GovernedOptimizationResearchResultModel",
    "OptimizationResearchLifecycleEventModel",
]
