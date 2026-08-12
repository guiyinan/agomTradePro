"""Append-only ORM model for authoritative R3 macro-factor runner specs."""

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

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_R3_SPEC_UOW: ContextVar[object | None] = ContextVar(
    "active_r3_macro_factor_runner_spec_uow",
    default=None,
)


@dataclass(frozen=True)
class _R3SpecInsertClaim:
    token: object
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_R3_SPEC_CLAIM: ContextVar[_R3SpecInsertClaim | None] = ContextVar(
    "active_r3_macro_factor_runner_spec_claim",
    default=None,
)


def _require_active_r3_macro_factor_runner_spec_uow() -> object:
    """Require the repository-owned transaction before owner rereads."""

    token = _ACTIVE_R3_SPEC_UOW.get()
    if token is None:
        raise ValidationError("R3 runner-spec owner query requires an active unit of work.")
    return token


@contextmanager
def _activate_r3_macro_factor_runner_spec_uow(token: object) -> Iterator[None]:
    reset = _ACTIVE_R3_SPEC_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_R3_SPEC_UOW.reset(reset)


@contextmanager
def _claim_r3_macro_factor_runner_spec_insert(
    *,
    token: object,
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    if _ACTIVE_R3_SPEC_UOW.get() is not token:
        raise ValidationError("R3 runner-spec insert requires its repository unit of work.")
    claim = _R3SpecInsertClaim(
        token=token,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset = _ACTIVE_R3_SPEC_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_R3_SPEC_CLAIM.reset(reset)


class R3MacroFactorRunnerSpecQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject all mutation and all unclaimed bulk insert paths."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R3 runner specs require exact repository appends.")

    def _update(self, values: object) -> NoReturn:
        raise ValidationError("R3 runner-spec evidence cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("R3 runner-spec evidence cannot be deleted.")

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
        items = list(objs)
        if (
            not items
            or raw
            or on_conflict is not None
            or update_fields is not None
            or unique_fields is not None
            or (using is not None and using != self.db)
        ):
            raise ValidationError("R3 runner-spec private insert is forbidden.")
        for item in items:
            _require_r3_macro_factor_runner_spec_insert_claim(item)
        insert = cast(
            Callable[..., list[tuple[object, ...]]],
            getattr(super(), "_insert"),  # noqa: B009 -- private Django typed boundary
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
        raise ValidationError("R3 runner-spec private bulk insert is forbidden.")


class R3MacroFactorRunnerSpecManager(AppendOnlyManager[_ModelT]):
    """Expose identical guards through default and base managers."""

    def get_queryset(self) -> R3MacroFactorRunnerSpecQuerySet[_ModelT]:
        return R3MacroFactorRunnerSpecQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R3 runner specs require exact repository appends.")


class R3MacroFactorRunnerSpecModel(models.Model):
    """Canonical complete runner spec and Research server knowledge seal."""

    objects = R3MacroFactorRunnerSpecManager()

    spec_id = models.CharField(max_length=192)
    spec_version = models.PositiveIntegerField()
    factor_version = models.CharField(max_length=192)
    target_code = models.CharField(max_length=192, db_index=True)
    expected_manifest_content_hash = models.CharField(max_length=64)
    spec_registered_at = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    first_selection_at = models.DateTimeField()
    last_evaluation_at = models.DateTimeField()
    calculated_at = models.DateTimeField()
    canonical_payload = models.JSONField()
    spec_content_hash = models.CharField(max_length=64, unique=True)
    record_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_r3_macro_factor_runner_spec"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["spec_id", "spec_version"],
                name="res_r3_spec_identity_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(spec_version__gt=0)
                    & models.Q(spec_registered_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(ledger_recorded_at__lt=models.F("first_selection_at"))
                    & models.Q(first_selection_at__lt=models.F("last_evaluation_at"))
                    & models.Q(last_evaluation_at__lte=models.F("calculated_at"))
                ),
                name="res_r3_spec_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r3_spec_safety_ck",
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
            raise ValidationError("R3 runner-spec evidence is append-only.")
        _require_r3_macro_factor_runner_spec_insert_claim(self)
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
            raise ValidationError("R3 runner-spec evidence is append-only.")
        _require_r3_macro_factor_runner_spec_insert_claim(self)
        super().save_base(
            raw=False,
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("R3 runner-spec evidence cannot be deleted.")


def _require_r3_macro_factor_runner_spec_insert_claim(model: models.Model) -> None:
    claim = _ACTIVE_R3_SPEC_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_R3_SPEC_UOW.get()
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("R3 runner spec requires an exact insert claim.")


@receiver(pre_delete, sender=R3MacroFactorRunnerSpecModel, weak=False)
def _reject_r3_macro_factor_runner_spec_collector_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject Django Collector and cascade deletion paths."""

    raise ValidationError("R3 runner-spec evidence cannot be deleted.")


__all__ = ["R3MacroFactorRunnerSpecModel"]
