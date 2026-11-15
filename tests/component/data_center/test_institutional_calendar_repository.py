"""Migrated database contracts for append-only institutional event persistence."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, connection, transaction

from apps.data_center.application.institutional_calendar_query import (
    QueryInstitutionalCalendarUseCase,
)
from apps.data_center.domain.institutional_calendar import (
    EventLifecycle,
    EvidenceGrade,
    InstitutionalEvent,
    KnowledgeMode,
)
from apps.data_center.infrastructure.institutional_calendar_models import (
    InstitutionalCalendarEventModel,
)
from apps.data_center.infrastructure.institutional_calendar_repository import (
    DjangoInstitutionalCalendarRepository,
)
from core.exceptions import DataValidationError

pytestmark = pytest.mark.django_db

KNOWN_AT = datetime(2026, 11, 10, 2, 0, tzinfo=UTC)


def _event(**overrides: object) -> InstitutionalEvent:
    """Return a valid scheduled event with independently mutable versions."""

    values: dict[str, object] = {
        "event_id": "nbs-cpi-2026-10",
        "source_id": "nbs_official",
        "source_event_id": "2026-schedule-cpi-october",
        "event_type": "macro_release",
        "title": "2026年10月份居民消费价格",
        "evidence": EvidenceGrade.TENTATIVE,
        "lifecycle": EventLifecycle.SCHEDULED,
        "revision": 1,
        "scheduled_at": datetime(2026, 11, 9, 1, 30, tzinfo=UTC),
        "effective_on": None,
        "source_published_at": datetime(2025, 12, 25, 1, 30, tzinfo=UTC),
        "source_published_on": None,
        "available_at": datetime(2025, 12, 25, 1, 30, tzinfo=UTC),
        "first_seen_at": datetime(2026, 1, 2, tzinfo=UTC),
        "recorded_at": datetime(2026, 1, 2, 0, 1, tzinfo=UTC),
        "original_sha256": "a" * 64,
        "supersedes_event_id": None,
    }
    values.update(overrides)
    return InstitutionalEvent(**values)  # type: ignore[arg-type]


def _successor(**overrides: object) -> InstitutionalEvent:
    """Return a confirmed actual-release successor with explicit clocks."""

    values: dict[str, object] = {
        "evidence": EvidenceGrade.CONFIRMED,
        "lifecycle": EventLifecycle.OCCURRED,
        "revision": 2,
        "effective_on": date(2026, 11, 9),
        "source_published_at": datetime(2026, 11, 9, 1, 30, tzinfo=UTC),
        "available_at": datetime(2026, 11, 9, 1, 30, tzinfo=UTC),
        "first_seen_at": datetime(2026, 11, 9, 2, 0, tzinfo=UTC),
        "recorded_at": datetime(2026, 11, 9, 2, 1, tzinfo=UTC),
        "original_sha256": "b" * 64,
        "supersedes_event_id": "nbs-cpi-2026-10",
    }
    values.update(overrides)
    return _event(**values)


def test_migrated_database_roundtrip_preserves_exact_event_versions() -> None:
    assert connection.vendor in {"sqlite", "postgresql"}
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM django_migrations WHERE app=%s AND name=%s",
            ["data_center", "0113_institutional_calendar"],
        )
        assert cursor.fetchone() == (1,)

    repository = DjangoInstitutionalCalendarRepository()
    schedule = _event()
    actual = _successor()

    assert repository.append(schedule) == schedule
    assert repository.append(actual) == actual
    assert repository.get_version(schedule.event_id, 1) == schedule
    assert repository.get_version(actual.event_id, 2) == actual
    assert repository.get_version(actual.event_id, 3) is None
    assert repository.list_versions() == (schedule, actual)
    assert InstitutionalCalendarEventModel.objects.count() == 2


def test_exact_replay_is_idempotent_but_identity_reuse_fails_closed() -> None:
    repository = DjangoInstitutionalCalendarRepository()
    schedule = _event()

    assert repository.append(schedule) == schedule
    assert repository.append(schedule) == schedule
    assert InstitutionalCalendarEventModel.objects.count() == 1

    with pytest.raises(DataValidationError) as caught:
        repository.append(replace(schedule, title="Conflicting title"))
    assert caught.value.code == "INSTITUTIONAL_EVENT_IDENTITY_CONFLICT"
    assert InstitutionalCalendarEventModel.objects.count() == 1
    assert repository.get_version(schedule.event_id, 1) == schedule


def test_revision_gaps_and_false_supersession_are_rejected() -> None:
    repository = DjangoInstitutionalCalendarRepository()

    with pytest.raises(DataValidationError) as caught:
        repository.append(_successor())
    assert caught.value.code == "INSTITUTIONAL_EVENT_REVISION_GAP"

    repository.append(_event())
    with pytest.raises(DataValidationError) as caught:
        repository.append(_successor(supersedes_event_id="another-event"))
    assert caught.value.code == "INSTITUTIONAL_EVENT_SUPERSESSION_INVALID"

    with pytest.raises(DataValidationError) as caught:
        repository.append(_successor(revision=3))
    assert caught.value.code == "INSTITUTIONAL_EVENT_REVISION_GAP"

    repository.append(_successor())
    with pytest.raises(DataValidationError) as caught:
        repository.append(
            _successor(
                revision=4,
                original_sha256="c" * 64,
                first_seen_at=datetime(2026, 11, 10, tzinfo=UTC),
                recorded_at=datetime(2026, 11, 10, 0, 1, tzinfo=UTC),
            )
        )
    assert caught.value.code == "INSTITUTIONAL_EVENT_REVISION_GAP"
    assert InstitutionalCalendarEventModel.objects.count() == 2


def test_model_and_queryset_reject_updates_and_deletes() -> None:
    repository = DjangoInstitutionalCalendarRepository()
    repository.append(_event())
    row = InstitutionalCalendarEventModel.objects.get()

    with pytest.raises(DjangoValidationError):
        row.save()
    with pytest.raises(DjangoValidationError):
        row.save_base()
    with pytest.raises(DjangoValidationError):
        row.delete()
    with pytest.raises(DjangoValidationError):
        InstitutionalCalendarEventModel.objects.filter(pk=row.pk).update(title="changed")
    with pytest.raises(DjangoValidationError):
        InstitutionalCalendarEventModel.objects.all().delete()

    assert repository.get_version(row.event_id, row.revision) == _event()


def test_real_repository_drives_pit_query_and_cancellation() -> None:
    repository = DjangoInstitutionalCalendarRepository()
    schedule = _event()
    actual = _successor()
    cancelled = _successor(
        revision=3,
        lifecycle=EventLifecycle.CANCELLED,
        effective_on=None,
        source_published_at=datetime(2026, 11, 10, 1, 30, tzinfo=UTC),
        available_at=datetime(2026, 11, 10, 1, 30, tzinfo=UTC),
        first_seen_at=datetime(2026, 11, 10, 2, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 11, 10, 2, 1, tzinfo=UTC),
        original_sha256="c" * 64,
    )
    for event in (schedule, actual, cancelled):
        repository.append(event)
    query = QueryInstitutionalCalendarUseCase(repository, timezone_name="Asia/Shanghai")

    before_actual = query.execute(
        date(2026, 11, 9),
        date(2026, 11, 9),
        known_at=actual.available_at,
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )
    after_actual = query.execute(
        date(2026, 11, 9),
        date(2026, 11, 9),
        known_at=KNOWN_AT,
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )
    after_cancel = query.execute(
        date(2026, 11, 9),
        date(2026, 11, 9),
        known_at=cancelled.recorded_at,
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )
    occurred_after_cancel = query.execute(
        date(2026, 11, 9),
        date(2026, 11, 9),
        known_at=cancelled.recorded_at,
        mode=KnowledgeMode.SYSTEM_KNOWN,
        lifecycle=EventLifecycle.OCCURRED,
    )

    assert [entry.event.revision for entry in before_actual] == [1]
    assert [entry.event.revision for entry in after_actual] == [2]
    assert [entry.event.revision for entry in after_cancel] == [3]
    assert after_cancel[0].event.lifecycle is EventLifecycle.CANCELLED
    assert occurred_after_cancel == ()


def test_date_only_source_precision_survives_storage_roundtrip() -> None:
    event = _event(
        source_published_at=None,
        source_published_on=date(2025, 12, 25),
    )
    repository = DjangoInstitutionalCalendarRepository()

    repository.append(event)

    assert repository.get_version(event.event_id, 1) == event
    assert repository.list_versions() == (event,)


def test_repository_validates_input_identity_and_revision() -> None:
    repository = DjangoInstitutionalCalendarRepository()

    with pytest.raises(DataValidationError) as caught:
        repository.append(object())  # type: ignore[arg-type]
    assert caught.value.code == "INSTITUTIONAL_EVENT_INPUT_INVALID"

    for event_id, revision in (("bad identity", 1), ("", 1), ("event", 0)):
        with pytest.raises(DataValidationError) as caught:
            repository.get_version(event_id, revision)
        assert caught.value.code == "INSTITUTIONAL_EVENT_READ_INPUT_INVALID"


@pytest.mark.parametrize("method", ("save", "save_base"))
def test_new_instance_with_existing_primary_key_cannot_rewrite_a_version(method: str) -> None:
    repository = DjangoInstitutionalCalendarRepository()
    repository.append(_event())
    original = InstitutionalCalendarEventModel.objects.get()
    values = {field.attname: getattr(original, field.attname) for field in original._meta.fields}
    clone = InstitutionalCalendarEventModel(**values)
    clone.title = "Primary-key clone must not replace historical content"
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            getattr(clone, method)()
    assert repository.get_version(original.event_id, original.revision) == _event()


@pytest.mark.parametrize("via_queryset", (False, True))
def test_bulk_conflict_update_cannot_rewrite_an_immutable_version(via_queryset: bool) -> None:
    repository = DjangoInstitutionalCalendarRepository()
    repository.append(_event())
    original = InstitutionalCalendarEventModel.objects.get()
    values = {
        field.attname: getattr(original, field.attname)
        for field in original._meta.fields
        if not field.primary_key
    }
    clone = InstitutionalCalendarEventModel(**values)
    clone.title = "Conflict update must not replace historical content"
    writer = (
        InstitutionalCalendarEventModel.objects.all()
        if via_queryset
        else InstitutionalCalendarEventModel.objects
    )
    with pytest.raises(DjangoValidationError):
        writer.bulk_create(
            [clone],
            update_conflicts=True,
            update_fields=["title"],
            unique_fields=["event_id", "revision"],
        )
    assert repository.get_version(original.event_id, original.revision) == _event()
