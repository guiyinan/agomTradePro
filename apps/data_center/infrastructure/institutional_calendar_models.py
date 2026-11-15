"""Append-only ORM storage for institutional-calendar event versions."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import NoReturn, Self, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

from apps.data_center.domain.institutional_calendar import EventLifecycle, EvidenceGrade
from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_EventModelT = TypeVar("_EventModelT", bound=models.Model)


class _InstitutionalCalendarQuerySet(AppendOnlyQuerySet[_EventModelT]):
    """Keep insertion batches from entering Django's conflict-update path."""

    def bulk_create(
        self,
        objs: Iterable[_EventModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[_EventModelT]:
        """Permit insert-only batches and reject conflict updates before any SQL."""
        if update_conflicts:
            raise ValidationError("Institutional calendar versions cannot be conflict-updated.")
        return super().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=False,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )


class _InstitutionalCalendarManager(AppendOnlyManager[_EventModelT]):
    """Expose the local insertion guard through manager and queryset entry points."""

    def get_queryset(self) -> _InstitutionalCalendarQuerySet[_EventModelT]:
        """Preserve the requested database alias and every inherited mutation guard."""
        return _InstitutionalCalendarQuerySet(self.model, using=self._db)


class InstitutionalCalendarEventModel(models.Model):
    """One immutable institutional event revision with source and system clocks."""

    EVIDENCE_CHOICES = tuple((item.value, item.value) for item in EvidenceGrade)
    LIFECYCLE_CHOICES = tuple((item.value, item.value) for item in EventLifecycle)

    event_id = models.CharField(max_length=240)
    source_id = models.CharField(max_length=240)
    source_event_id = models.CharField(max_length=240)
    event_type = models.CharField(max_length=240)
    title = models.CharField(max_length=240)
    evidence = models.CharField(max_length=16, choices=EVIDENCE_CHOICES)
    lifecycle = models.CharField(max_length=16, choices=LIFECYCLE_CHOICES)
    revision = models.PositiveIntegerField()
    scheduled_at = models.DateTimeField(null=True)
    effective_on = models.DateField(null=True)
    source_published_at = models.DateTimeField(null=True)
    source_published_on = models.DateField(null=True)
    available_at = models.DateTimeField()
    first_seen_at = models.DateTimeField()
    recorded_at = models.DateTimeField()
    original_sha256 = models.CharField(max_length=64)
    supersedes_event_id = models.CharField(max_length=240, null=True)

    objects: _InstitutionalCalendarManager[Self] = _InstitutionalCalendarManager()

    class Meta:
        db_table = "data_center_institutional_calendar_event"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["event_id", "revision"]
        constraints = [
            models.UniqueConstraint(
                fields=("event_id", "revision"),
                name="dc_inst_cal_rev_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(revision__gte=1),
                name="dc_inst_cal_revision_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(original_sha256__regex=r"^[0-9a-f]{64}$"),
                name="dc_inst_cal_hash_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        source_published_at__isnull=False,
                        source_published_on__isnull=True,
                    )
                    | models.Q(
                        source_published_at__isnull=True,
                        source_published_on__isnull=False,
                    )
                ),
                name="dc_inst_cal_source_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(source_published_at__isnull=True)
                    | models.Q(available_at__gte=models.F("source_published_at"))
                ),
                name="dc_inst_cal_available_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(recorded_at__gte=models.F("first_seen_at")),
                name="dc_inst_cal_recorded_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(revision=1, supersedes_event_id__isnull=True)
                    | models.Q(revision__gt=1, supersedes_event_id__isnull=False)
                ),
                name="dc_inst_cal_supersedes_ck",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(
                        lifecycle__in=(
                            EventLifecycle.OCCURRED.value,
                            EventLifecycle.CANCELLED.value,
                        )
                    )
                    | models.Q(
                        evidence=EvidenceGrade.CONFIRMED.value,
                        source_published_at__isnull=False,
                    )
                ),
                name="dc_inst_cal_occurrence_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("available_at",), name="dc_inst_cal_avail_ix"),
            models.Index(fields=("recorded_at",), name="dc_inst_cal_recorded_ix"),
            models.Index(
                fields=("event_type", "lifecycle"),
                name="dc_inst_cal_type_state_ix",
            ),
        ]

    def save(
        self,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Allow inserts but reject every mutation of an existing event version."""

        if force_update or update_fields is not None or not self._state.adding:
            raise ValidationError("Institutional calendar events are append-only.")
        super().save(force_insert=True, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Reject raw fixtures and lower-level updates of immutable versions."""

        if raw or force_update or update_fields is not None or not self._state.adding:
            raise ValidationError("Institutional calendar events are append-only.")
        super().save_base(
            raw=False,
            force_insert=True,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def delete(self, using: object | None = None, keep_parents: bool = False) -> NoReturn:
        """Retain every event revision."""

        del using, keep_parents
        raise ValidationError("Institutional calendar events are append-only.")

    def __str__(self) -> str:
        """Expose exact event version identity for diagnostics."""

        return f"InstitutionalCalendarEvent({self.event_id}:r{self.revision})"


__all__ = ["InstitutionalCalendarEventModel"]
