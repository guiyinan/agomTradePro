"""Append-only ORM ledger for complete R7 research evidence/result packets."""

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

from apps.research.infrastructure.r7_sample_policy_models import R7SamplePolicyModel
from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_R7_RESULT_UOW: ContextVar[object | None] = ContextVar(
    "active_r7_research_result_uow",
    default=None,
)


@dataclass(frozen=True)
class _R7ResultInsertClaim:
    token: object
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_R7_RESULT_CLAIM: ContextVar[_R7ResultInsertClaim | None] = ContextVar(
    "active_r7_research_result_claim",
    default=None,
)


def _require_active_r7_research_result_uow() -> object:
    """Require the composition-owned transaction before owner rereads."""

    token = _ACTIVE_R7_RESULT_UOW.get()
    if token is None:
        raise ValidationError("R7 research evidence query requires an active unit of work.")
    return token


@contextmanager
def _activate_r7_research_result_uow(token: object) -> Iterator[None]:
    reset = _ACTIVE_R7_RESULT_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_R7_RESULT_UOW.reset(reset)


@contextmanager
def _claim_r7_research_result_insert(
    *,
    token: object,
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    if _ACTIVE_R7_RESULT_UOW.get() is not token:
        raise ValidationError("R7 research result insert requires its repository unit of work.")
    claim = _R7ResultInsertClaim(
        token=token,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset = _ACTIVE_R7_RESULT_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_R7_RESULT_CLAIM.reset(reset)


class R7ResearchResultQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject every bulk insert shortcut for complete evidence graphs."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R7 research results require exact repository appends.")

    def _update(self, values: object) -> NoReturn:
        """Reject Django's private SQL update entry point."""

        raise ValidationError("R7 research result evidence cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        """Reject Django's private fast-delete entry point."""

        raise ValidationError("R7 research result evidence cannot be deleted.")

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
        """Allow only the exact claimed insert used by ``Model.save()``."""

        items = list(objs)
        if (
            not items
            or raw
            or on_conflict is not None
            or update_fields is not None
            or unique_fields is not None
            or (using is not None and using != self.db)
        ):
            raise ValidationError("R7 research result private insert is forbidden.")
        for item in items:
            _require_r7_research_result_insert_claim(item)
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
        """Reject the private bulk-insert path even when called directly."""

        raise ValidationError("R7 research result private bulk insert is forbidden.")


class R7ResearchResultManager(AppendOnlyManager[_ModelT]):
    """Expose identical append-only guards on all manager paths."""

    def get_queryset(self) -> R7ResearchResultQuerySet[_ModelT]:
        return R7ResearchResultQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R7 research results require exact repository appends.")


class R7ResearchResultModel(models.Model):
    """Canonical complete R7 evidence graph and deterministic result packet."""

    objects = R7ResearchResultManager()

    sample_policy = models.ForeignKey(
        R7SamplePolicyModel,
        on_delete=models.PROTECT,
        related_name="research_results",
    )
    result_id = models.CharField(max_length=192)
    result_version = models.CharField(max_length=192)
    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    policy_record_hash = models.CharField(max_length=64)
    scope_content_hash = models.CharField(max_length=64, db_index=True)
    evaluated_at = models.DateTimeField(db_index=True)
    evidence_graph_hash = models.CharField(max_length=64)
    input_receipt_hash = models.CharField(max_length=64, unique=True)
    calibration_hash = models.CharField(max_length=64)
    historical_analogy_hash = models.CharField(max_length=64)
    path_research_hash = models.CharField(max_length=64)
    analogy_evidence_hash = models.CharField(max_length=64, null=True)
    path_evidence_hash = models.CharField(max_length=64, null=True)
    forecast_observation_count = models.PositiveIntegerField()
    recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    trains_probability_model = models.BooleanField(default=False)
    publishes_model_probability = models.BooleanField(default=False)
    produces_decision = models.BooleanField(default=False)
    executes_orders = models.BooleanField(default=False)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    content_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_r7_research_result"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=["scope_content_hash", "evaluated_at"],
                name="res_r7_result_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["result_id", "result_version"],
                name="res_r7_result_identity_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(evaluated_at__lte=models.F("recorded_at")),
                name="res_r7_result_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    trains_probability_model=False,
                    publishes_model_probability=False,
                    produces_decision=False,
                    executes_orders=False,
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r7_result_safety_ck",
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
        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("R7 research result evidence is append-only.")
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
        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("R7 research result evidence is append-only.")
        self._require_claim()
        super().save_base(
            raw=False,
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def _require_claim(self) -> None:
        _require_r7_research_result_insert_claim(self)

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("R7 research result evidence cannot be deleted.")


def _require_r7_research_result_insert_claim(model: models.Model) -> None:
    claim = _ACTIVE_R7_RESULT_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_R7_RESULT_UOW.get()
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("R7 research result requires an exact insert claim.")


@receiver(pre_delete, sender=R7ResearchResultModel, weak=False)
def _reject_r7_research_result_collector_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject Django Collector and cascade deletion paths."""

    raise ValidationError("R7 research result evidence cannot be deleted.")


__all__ = ["R7ResearchResultModel"]
