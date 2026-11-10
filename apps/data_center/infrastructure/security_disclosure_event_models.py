"""Append-only ORM storage for official exchange disclosure event revisions."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, Self, TypeVar, cast

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
)
from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_MODEL_T = TypeVar("_MODEL_T", bound=models.Model)
_ACTIVE_UOW: ContextVar[object | None] = ContextVar(
    "data_center_security_disclosure_event_uow", default=None
)


@dataclass(frozen=True, slots=True)
class _InsertClaim:
    """Private capability for one exact repository-controlled source-fact insert."""

    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "data_center_security_disclosure_event_insert_claim", default=None
)


@contextmanager
def _activate_security_disclosure_event_uow() -> Iterator[object]:
    """Activate one non-nestable append capability for a source event insert."""

    if _ACTIVE_UOW.get() is not None:
        raise ValidationError("Security disclosure event UOWs may not be nested.")
    token = object()
    reset = _ACTIVE_UOW.set(token)
    try:
        yield token
    finally:
        _ACTIVE_UOW.reset(reset)


@contextmanager
def _claim_security_disclosure_event_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Claim one exact new event row inside the active repository UOW."""

    if _ACTIVE_UOW.get() is not token:
        raise ValidationError("Security disclosure event insert requires its private UOW.")
    if _ACTIVE_CLAIM.get() is not None:
        raise ValidationError("Security disclosure event insert claims may not be nested.")
    claim = _InsertClaim(
        token=token,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items())),
    )
    reset = _ACTIVE_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_CLAIM.reset(reset)


def _require_insert_claim(model: models.Model) -> None:
    """Require the exact values claimed by the active repository transaction."""

    claim = _ACTIVE_CLAIM.get()
    actual_values = tuple(
        sorted(
            (field.attname, getattr(model, field.attname))
            for field in model._meta.concrete_fields
            if not field.primary_key
        )
    )
    if (
        claim is None
        or claim.token is not _ACTIVE_UOW.get()
        or claim.model_type is not type(model)
        or claim.expected_values != actual_values
    ):
        raise ValidationError("Security disclosure event insert requires an exact append claim.")


class _SecurityDisclosureEventQuerySet(AppendOnlyQuerySet[_MODEL_T]):
    """Reject mutations, deletion, and insert shortcuts around the event repository."""

    def bulk_create(
        self,
        objs: Iterable[_MODEL_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Require every event insert to pass native identity checks."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("Security disclosure events require repository persistence.")

    def _update(self, values: object) -> NoReturn:
        """Block Django's internal bulk update path."""

        del values
        raise ValidationError("Security disclosure events are append-only.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        """Block direct SQL deletion through Django's raw queryset path."""

        del using
        raise ValidationError("Security disclosure events are append-only.")

    def _insert(
        self,
        objs: Iterable[_MODEL_T],
        fields: Iterable[object],
        returning_fields: Iterable[object] | None = None,
        raw: bool = False,
        using: str | None = None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> list[tuple[object, ...]]:
        """Allow only one exact model.save insert claimed by the repository."""

        items = list(objs)
        if (
            len(items) != 1
            or raw
            or on_conflict is not None
            or update_fields is not None
            or unique_fields is not None
            or (using is not None and using != self.db)
        ):
            raise ValidationError("Security disclosure event private insert is forbidden.")
        for item in items:
            _require_insert_claim(item)
        insert = cast(
            Callable[..., list[tuple[object, ...]]],
            getattr(super(), "_insert"),  # noqa: B009 -- typed Django private boundary
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
        objs: list[_MODEL_T],
        fields: list[object],
        batch_size: int | None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> NoReturn:
        """Block Django's batch insert path, including one-row shortcuts."""

        del objs, fields, batch_size, on_conflict, update_fields, unique_fields
        raise ValidationError("Security disclosure event bulk insertion is forbidden.")


class _SecurityDisclosureEventManager(AppendOnlyManager[_MODEL_T]):
    """Expose guarded reads and reject manager-level write shortcuts."""

    def get_queryset(self) -> _SecurityDisclosureEventQuerySet[_MODEL_T]:
        """Return an immutable queryset bound to this manager's database."""

        return _SecurityDisclosureEventQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_MODEL_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject manager-level insertion around the repository boundary."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("Security disclosure events require repository persistence.")

    def bulk_update(
        self,
        objs: Iterable[_MODEL_T],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> NoReturn:
        """Reject manager-level evidence mutation."""

        del objs, fields, batch_size
        raise ValidationError("Security disclosure events are append-only.")


class SecurityDisclosureEventModel(models.Model):
    """One source disclosure revision, retained independently from event dispatch."""

    SOURCE_CHOICES = tuple((item.value, item.name) for item in SecurityDisclosureSource)
    EXCHANGE_CHOICES = tuple((item.value, item.name) for item in SecurityDisclosureExchange)
    EVENT_TYPE_CHOICES = tuple((item.value, item.value) for item in SecurityDisclosureEventType)

    source = models.CharField(max_length=32, choices=SOURCE_CHOICES)
    exchange = models.CharField(max_length=8, choices=EXCHANGE_CHOICES)
    asset_code = models.CharField(max_length=20, db_index=True)
    source_security_code = models.CharField(max_length=40)
    source_event_id = models.CharField(max_length=200)
    source_revision_id = models.CharField(max_length=200)
    raw_event_type = models.CharField(max_length=120)
    event_type = models.CharField(max_length=32, choices=EVENT_TYPE_CHOICES, db_index=True)
    source_url = models.URLField(max_length=2048)
    source_body_sha256 = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64)
    announced_at = models.DateTimeField(null=True, blank=True)
    announced_on = models.DateField(null=True, blank=True)
    source_available_at = models.DateTimeField(null=True, blank=True)
    source_available_on = models.DateField(null=True, blank=True)
    available_at = models.DateTimeField(db_index=True)
    first_seen_at = models.DateTimeField()
    effective_at = models.DateTimeField(null=True, blank=True)
    effective_on = models.DateField(null=True, blank=True)
    supersedes_source_event_id = models.CharField(max_length=200, blank=True)
    supersedes_source_revision_id = models.CharField(max_length=200, blank=True)
    recorded_at = models.DateTimeField(db_index=True)

    objects: _SecurityDisclosureEventManager[Self] = _SecurityDisclosureEventManager()

    class Meta:
        db_table = "data_center_security_disclosure_event"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = [
            "available_at",
            "exchange",
            "asset_code",
            "source_event_id",
            "source_revision_id",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "source",
                    "exchange",
                    "asset_code",
                    "source_event_id",
                    "source_revision_id",
                ),
                name="dc_sec_disc_native_rev_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(announced_at__isnull=True, announced_on__isnull=True)
                    | models.Q(announced_at__isnull=False, announced_on__isnull=True)
                    | models.Q(announced_at__isnull=True, announced_on__isnull=False)
                ),
                name="dc_sec_disc_announce_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(source_available_at__isnull=True, source_available_on__isnull=True)
                    | models.Q(source_available_at__isnull=False, source_available_on__isnull=True)
                    | models.Q(source_available_at__isnull=True, source_available_on__isnull=False)
                ),
                name="dc_sec_disc_source_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(effective_at__isnull=True, effective_on__isnull=True)
                    | models.Q(effective_at__isnull=False, effective_on__isnull=True)
                    | models.Q(effective_at__isnull=True, effective_on__isnull=False)
                ),
                name="dc_sec_disc_effect_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(supersedes_source_event_id="", supersedes_source_revision_id="")
                    | (
                        ~models.Q(supersedes_source_event_id="")
                        & ~models.Q(supersedes_source_revision_id="")
                    )
                ),
                name="dc_sec_disc_supersedes_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(recorded_at__gte=models.F("first_seen_at"))
                    & models.Q(available_at=models.F("first_seen_at"))
                ),
                name="dc_sec_disc_recorded_clock_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("exchange", "asset_code", "available_at"),
                name="dc_sec_disc_security_avail_ix",
            ),
            models.Index(
                fields=("source_event_id", "source_revision_id"),
                name="dc_sec_disc_revision_ix",
            ),
        ]

    def save(
        self,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Permit only one exact claimed insert; existing facts are immutable."""

        del force_insert
        if force_update or update_fields is not None or not self._state.adding:
            raise ValidationError("Security disclosure events are append-only.")
        _require_insert_claim(self)
        super().save(force_insert=True, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Guard direct calls to Django's lower-level persistence method."""

        del force_insert
        if raw or force_update or update_fields is not None or not self._state.adding:
            raise ValidationError("Security disclosure events are append-only.")
        _require_insert_claim(self)
        super().save_base(
            raw=False,
            force_insert=True,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Preserve every captured source revision."""

        del using, keep_parents
        raise ValidationError("Security disclosure events are append-only.")

    def __str__(self) -> str:
        """Expose stable event and revision identity for diagnostics."""

        return (
            f"SecurityDisclosureEvent({self.exchange}:{self.asset_code}:"
            f"{self.source_event_id}:{self.source_revision_id})"
        )


__all__ = [
    "SecurityDisclosureEventModel",
    "_activate_security_disclosure_event_uow",
    "_claim_security_disclosure_event_insert",
]
