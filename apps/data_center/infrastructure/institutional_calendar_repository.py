"""Django persistence for exact immutable institutional-calendar versions."""

from __future__ import annotations

from django.db import IntegrityError, transaction

from apps.data_center.application.institutional_calendar import (
    InstitutionalEventRepositoryPort,
)
from apps.data_center.application.institutional_calendar_query import (
    InstitutionalCalendarQueryRepositoryPort,
)
from apps.data_center.domain.institutional_calendar import (
    EventLifecycle,
    EvidenceGrade,
    InstitutionalEvent,
)
from apps.data_center.infrastructure.institutional_calendar_models import (
    InstitutionalCalendarEventModel,
)
from core.exceptions import DataValidationError


class DjangoInstitutionalCalendarRepository(
    InstitutionalEventRepositoryPort,
    InstitutionalCalendarQueryRepositoryPort,
):
    """Append event versions and restore exact domain facts without latest shortcuts."""

    def __init__(self, *, using: str = "default") -> None:
        """Bind an explicit database alias for isolated or composed reads and writes."""

        if not isinstance(using, str) or not using:
            raise DataValidationError(
                "Institutional-calendar database alias is invalid.",
                code="INSTITUTIONAL_EVENT_DATABASE_ALIAS_INVALID",
            )
        self._using = using

    def append(self, event: InstitutionalEvent) -> InstitutionalEvent:
        """Append one contiguous version or return an exact idempotent winner."""

        if type(event) is not InstitutionalEvent:
            raise DataValidationError(
                "Institutional event input must be typed.",
                code="INSTITUTIONAL_EVENT_INPUT_INVALID",
            )
        values = _event_values(event)
        with transaction.atomic(using=self._using):
            rows = tuple(
                InstitutionalCalendarEventModel._default_manager.using(self._using)
                .select_for_update()
                .filter(event_id=event.event_id)
                .order_by("revision")
            )
            existing = next((row for row in rows if row.revision == event.revision), None)
            if existing is not None:
                return _resolve_existing(existing, event)
            if rows:
                latest = rows[-1]
                if event.revision != latest.revision + 1:
                    raise DataValidationError(
                        "Institutional event revisions must be contiguous.",
                        code="INSTITUTIONAL_EVENT_REVISION_GAP",
                    )
                if event.supersedes_event_id != event.event_id:
                    raise DataValidationError(
                        "Institutional event successor must supersede the same event identity.",
                        code="INSTITUTIONAL_EVENT_SUPERSESSION_INVALID",
                    )
            elif event.revision != 1:
                raise DataValidationError(
                    "Institutional event history must start at revision one.",
                    code="INSTITUTIONAL_EVENT_REVISION_GAP",
                )
            try:
                with transaction.atomic(using=self._using):
                    created = InstitutionalCalendarEventModel._default_manager.using(
                        self._using
                    ).create(**values)
            except IntegrityError as error:
                concurrent = (
                    InstitutionalCalendarEventModel._default_manager.using(self._using)
                    .select_for_update()
                    .filter(event_id=event.event_id, revision=event.revision)
                    .first()
                )
                if concurrent is None:
                    raise DataValidationError(
                        "Institutional event append violated a storage constraint.",
                        code="INSTITUTIONAL_EVENT_WRITE_CONFLICT",
                    ) from error
                return _resolve_existing(concurrent, event)
            return _to_domain(created)

    def get_version(self, event_id: str, revision: int) -> InstitutionalEvent | None:
        """Return one exact event version without inferring freshness or currency."""

        _validate_read_identity(event_id, revision)
        model = (
            InstitutionalCalendarEventModel._default_manager.using(self._using)
            .filter(event_id=event_id, revision=revision)
            .first()
        )
        return None if model is None else _to_domain(model)

    def list_versions(self) -> tuple[InstitutionalEvent, ...]:
        """Return every immutable version in deterministic event/revision order."""

        rows = (
            InstitutionalCalendarEventModel._default_manager.using(self._using)
            .all()
            .order_by("event_id", "revision")
        )
        return tuple(_to_domain(row) for row in rows)


def _event_values(event: InstitutionalEvent) -> dict[str, object]:
    """Convert a validated domain event into exact ORM column values."""

    return {
        "event_id": event.event_id,
        "source_id": event.source_id,
        "source_event_id": event.source_event_id,
        "event_type": event.event_type,
        "title": event.title,
        "evidence": event.evidence.value,
        "lifecycle": event.lifecycle.value,
        "revision": event.revision,
        "scheduled_at": event.scheduled_at,
        "effective_on": event.effective_on,
        "source_published_at": event.source_published_at,
        "source_published_on": event.source_published_on,
        "available_at": event.available_at,
        "first_seen_at": event.first_seen_at,
        "recorded_at": event.recorded_at,
        "original_sha256": event.original_sha256,
        "supersedes_event_id": event.supersedes_event_id,
    }


def _to_domain(model: InstitutionalCalendarEventModel) -> InstitutionalEvent:
    """Restore one typed domain event and reject corrupt persisted state."""

    try:
        return InstitutionalEvent(
            event_id=model.event_id,
            source_id=model.source_id,
            source_event_id=model.source_event_id,
            event_type=model.event_type,
            title=model.title,
            evidence=EvidenceGrade(model.evidence),
            lifecycle=EventLifecycle(model.lifecycle),
            revision=model.revision,
            scheduled_at=model.scheduled_at,
            effective_on=model.effective_on,
            source_published_at=model.source_published_at,
            source_published_on=model.source_published_on,
            available_at=model.available_at,
            first_seen_at=model.first_seen_at,
            recorded_at=model.recorded_at,
            original_sha256=model.original_sha256,
            supersedes_event_id=model.supersedes_event_id,
        )
    except (TypeError, ValueError) as error:
        raise DataValidationError(
            "Stored institutional event is invalid.",
            code="INSTITUTIONAL_EVENT_STORAGE_INVALID",
        ) from error


def _resolve_existing(
    model: InstitutionalCalendarEventModel,
    event: InstitutionalEvent,
) -> InstitutionalEvent:
    """Return an exact replay or reject reuse of an event version identity."""

    persisted = _to_domain(model)
    if persisted != event:
        raise DataValidationError(
            "Institutional event version identity already has different content.",
            code="INSTITUTIONAL_EVENT_IDENTITY_CONFLICT",
        )
    return persisted


def _validate_read_identity(event_id: str, revision: int) -> None:
    """Require canonical event identity and a positive integer revision."""

    if (
        not isinstance(event_id, str)
        or not event_id
        or event_id != event_id.strip()
        or len(event_id) > 240
        or any(character.isspace() for character in event_id)
        or type(revision) is not int
        or revision < 1
    ):
        raise DataValidationError(
            "Institutional event read identity is invalid.",
            code="INSTITUTIONAL_EVENT_READ_INPUT_INVALID",
        )


__all__ = ["DjangoInstitutionalCalendarRepository"]
