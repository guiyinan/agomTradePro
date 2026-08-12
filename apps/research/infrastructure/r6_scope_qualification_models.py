"""Append-only ORM boundary for canonical R6 scope-qualification bindings."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, cast

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_UOW: ContextVar[object | None] = ContextVar("r6_scope_binding_uow", default=None)
_ACTIVE_CLAIM: ContextVar[_InsertClaim | None] = ContextVar("r6_scope_binding_claim", default=None)


@contextmanager
def _activate_r6_scope_binding_uow(token: object) -> Iterator[None]:
    reset = _ACTIVE_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_UOW.reset(reset)


@contextmanager
def _claim_r6_scope_binding_insert(
    *, token: object, expected_values: Mapping[str, object]
) -> Iterator[None]:
    if _ACTIVE_UOW.get() is not token:
        raise ValidationError("R6 scope binding insert requires its unit of work.")
    reset = _ACTIVE_CLAIM.set(
        _InsertClaim(
            token=token,
            expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
        )
    )
    try:
        yield
    finally:
        _ACTIVE_CLAIM.reset(reset)


def _require_claim(model: models.Model) -> None:
    claim = _ACTIVE_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_UOW.get()
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("R6 scope binding requires an exact insert claim.")


class R6ScopeQualificationQuerySet(AppendOnlyQuerySet["R6ScopeQualificationRegistryModel"]):
    """Reject every public ORM mutation shortcut."""

    def get_or_create(
        self, defaults: Mapping[str, object] | None = None, **kwargs: object
    ) -> NoReturn:
        raise ValidationError("R6 scope binding get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R6 scope binding update_or_create is forbidden.")

    def bulk_create(
        self,
        objs: Iterable[R6ScopeQualificationRegistryModel],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Iterable[str] | None = None,
        unique_fields: Iterable[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R6 scope bindings require exact repository appends.")

    def _update(self, values: object) -> NoReturn:
        raise ValidationError("R6 scope bindings cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("R6 scope bindings cannot be deleted.")

    def _insert(
        self,
        objs: Iterable[R6ScopeQualificationRegistryModel],
        fields: Iterable[object],
        returning_fields: Iterable[object] | None = None,
        raw: bool = False,
        using: str | None = None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> list[tuple[object, ...]]:
        """Allow only Model.save's exact claimed first insert."""

        items = list(objs)
        if (
            not items
            or raw
            or on_conflict is not None
            or update_fields is not None
            or unique_fields is not None
            or (using is not None and using != self.db)
        ):
            raise ValidationError("R6 scope binding private insert is forbidden.")
        for item in items:
            _require_claim(item)
        insert = cast(
            Callable[..., list[tuple[object, ...]]],
            getattr(super(), "_insert"),  # noqa: B009 - typed Django boundary
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
        objs: list[R6ScopeQualificationRegistryModel],
        fields: list[object],
        batch_size: int | None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> NoReturn:
        raise ValidationError("R6 scope binding private bulk insert is forbidden.")


class R6ScopeQualificationManager(AppendOnlyManager["R6ScopeQualificationRegistryModel"]):
    """Expose the same guards through default and base managers."""

    def get_queryset(self) -> R6ScopeQualificationQuerySet:
        return R6ScopeQualificationQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[R6ScopeQualificationRegistryModel],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Iterable[str] | None = None,
        unique_fields: Iterable[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("R6 scope bindings require exact repository appends.")

    def get_or_create(
        self, defaults: Mapping[str, object] | None = None, **kwargs: object
    ) -> NoReturn:
        raise ValidationError("R6 scope binding get_or_create is forbidden.")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("R6 scope binding update_or_create is forbidden.")


class R6ScopeQualificationRegistryModel(models.Model):
    """Immutable definition/source row with no public create authority."""

    objects = R6ScopeQualificationManager()

    binding_id = models.CharField(max_length=300)
    binding_version = models.CharField(max_length=128)
    definition_version = models.CharField(max_length=128)
    definition_hash = models.CharField(max_length=64, unique=True)
    scope_id = models.CharField(max_length=300, db_index=True)
    scope_version = models.CharField(max_length=128)
    scope_hash = models.CharField(max_length=64, unique=True)
    qualification_id = models.CharField(max_length=300, db_index=True)
    qualification_hash = models.CharField(max_length=64)
    source_receipt_id = models.CharField(max_length=300)
    source_receipt_version = models.CharField(max_length=128)
    source_receipt_hash = models.CharField(max_length=64, unique=True)
    effective_at = models.DateTimeField()
    definition_valid_until = models.DateTimeField()
    source_available_at = models.DateTimeField()
    source_valid_until = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    definition_payload = models.JSONField()
    source_payload = models.JSONField()
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_replace_regime = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)

    class Meta:
        db_table = "research_r6_scope_qualification_registry"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=("scope_id", "ledger_recorded_at"),
                name="res_r6_scope_bind_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("binding_id", "binding_version"),
                name="res_r6_scope_bind_id_uq",
            ),
            models.UniqueConstraint(
                fields=("scope_id", "scope_version"),
                name="res_r6_scope_bind_scope_uq",
            ),
            models.UniqueConstraint(
                fields=("source_receipt_id", "source_receipt_version"),
                name="res_r6_scope_bind_src_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(effective_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(source_available_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(ledger_recorded_at__lt=models.F("definition_valid_until"))
                    & models.Q(ledger_recorded_at__lt=models.F("source_valid_until"))
                ),
                name="res_r6_scope_bind_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    definition_version=("research-r6-scope-qualification-definition.v1"),
                    source_receipt_version=("research-r6-scope-qualification-source.v1"),
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_replace_regime=True,
                    must_not_execute=True,
                ),
                name="res_r6_scope_bind_safe_ck",
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
            raise ValidationError("R6 scope bindings are append-only.")
        _require_claim(self)
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
            raise ValidationError("R6 scope bindings are append-only.")
        _require_claim(self)
        super().save_base(
            raw=False,
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("R6 scope bindings cannot be deleted.")


@receiver(
    pre_delete,
    sender=R6ScopeQualificationRegistryModel,
    dispatch_uid="reject_research_r6_scope_qualification_delete",
    weak=False,
)
def _reject_r6_scope_qualification_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("R6 scope bindings cannot be deleted.")


__all__ = ["R6ScopeQualificationRegistryModel"]
