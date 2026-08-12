"""Append-only ORM ledger for Research-owned R2 trial policies."""

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

from shared.infrastructure.django_append_only import (
    AppendOnlyManager,
    AppendOnlyQuerySet,
)

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_R2_POLICY_UOW: ContextVar[object | None] = ContextVar(
    "active_r2_trial_policy_registry_uow",
    default=None,
)


@dataclass(frozen=True)
class _R2PolicyInsertClaim:
    token: object
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_R2_POLICY_CLAIM: ContextVar[_R2PolicyInsertClaim | None] = ContextVar(
    "active_r2_trial_policy_registry_claim",
    default=None,
)


def _require_active_r2_trial_policy_uow() -> object:
    """Require the repository transaction before any owner reread."""

    token = _ACTIVE_R2_POLICY_UOW.get()
    if token is None:
        raise ValidationError("R2 trial-policy owner read requires an active unit of work.")
    return token


@contextmanager
def _activate_r2_trial_policy_uow(token: object) -> Iterator[None]:
    reset = _ACTIVE_R2_POLICY_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_R2_POLICY_UOW.reset(reset)


@contextmanager
def _claim_r2_trial_policy_insert(
    *,
    token: object,
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Authorize exactly one repository-shaped insert inside its UoW."""

    if _ACTIVE_R2_POLICY_UOW.get() is not token:
        raise ValidationError("R2 trial-policy insert requires its repository UoW.")
    claim = _R2PolicyInsertClaim(
        token=token,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset = _ACTIVE_R2_POLICY_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_R2_POLICY_CLAIM.reset(reset)


class R2TrialPolicyQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject every public mutation and unclaimed insert route."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R2 trial policies require exact repository appends.")

    def _update(self, values: object) -> NoReturn:
        raise ValidationError("R2 trial-policy evidence cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("R2 trial-policy evidence cannot be deleted.")

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
            raise ValidationError("R2 trial-policy private insert is forbidden.")
        for item in items:
            _require_r2_trial_policy_insert_claim(item)
        insert = cast(
            Callable[..., list[tuple[object, ...]]],
            getattr(super(), "_insert"),  # noqa: B009 -- private Django boundary
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
        raise ValidationError("R2 trial-policy private bulk insert is forbidden.")


class R2TrialPolicyManager(AppendOnlyManager[_ModelT]):
    """Expose the same guards through default and base managers."""

    def get_queryset(self) -> R2TrialPolicyQuerySet[_ModelT]:
        return R2TrialPolicyQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R2 trial policies require exact repository appends.")


class R2MarketStructureTrialPolicyLedgerModel(models.Model):
    """Complete canonical Phase-A policy with a trusted ledger knowledge time."""

    objects = R2TrialPolicyManager()

    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    taxonomy_publication_id = models.CharField(max_length=192)
    taxonomy_publication_version = models.CharField(max_length=192)
    taxonomy_publication_hash = models.CharField(max_length=64)
    taxonomy_artifact_hash = models.CharField(max_length=64)
    calendar_publication_id = models.CharField(max_length=192)
    calendar_publication_version = models.CharField(max_length=192)
    calendar_publication_hash = models.CharField(max_length=64)
    calendar_artifact_hash = models.CharField(max_length=64)
    policy_registered_at = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    selection_as_of = models.DateTimeField()
    active_from = models.DateTimeField()
    active_until = models.DateTimeField()
    canonical_payload = models.JSONField()
    policy_content_hash = models.CharField(max_length=64, unique=True)
    record_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_r2_trial_policy_registry"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("policy_id", "policy_version", "ledger_recorded_at"),
                name="res_r2_pol_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("policy_id", "policy_version"),
                name="res_r2_pol_ident_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(policy_registered_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(ledger_recorded_at__lt=models.F("selection_as_of"))
                    & models.Q(active_from__lte=models.F("selection_as_of"))
                    & models.Q(selection_as_of__lt=models.F("active_until"))
                ),
                name="res_r2_pol_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r2_pol_safe_ck",
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
        """Allow only an exact repository-claimed first insert."""

        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("R2 trial-policy evidence is append-only.")
        _require_r2_trial_policy_insert_claim(self)
        super().save(force_insert=force_insert, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Reject raw, public, and update-shaped save_base bypasses."""

        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("R2 trial-policy evidence is append-only.")
        _require_r2_trial_policy_insert_claim(self)
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
        """Reject instance deletion."""

        raise ValidationError("R2 trial-policy evidence cannot be deleted.")


def _require_r2_trial_policy_insert_claim(model: models.Model) -> None:
    claim = _ACTIVE_R2_POLICY_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_R2_POLICY_UOW.get()
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("R2 trial policy requires an exact insert claim.")


@receiver(pre_delete, sender=R2MarketStructureTrialPolicyLedgerModel, weak=False)
def _reject_r2_trial_policy_collector_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject Django Collector and cascade deletion paths."""

    raise ValidationError("R2 trial-policy evidence cannot be deleted.")


__all__ = [
    "R2MarketStructureTrialPolicyLedgerModel",
    "_activate_r2_trial_policy_uow",
    "_claim_r2_trial_policy_insert",
    "_require_active_r2_trial_policy_uow",
]
