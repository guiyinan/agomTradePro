"""Real migrated storage, original-body integrity and source-bound public task."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.data_center.domain.institutional_calendar import (
    EventLifecycle,
    EvidenceGrade,
    KnowledgeMode,
)
from apps.data_center.infrastructure.institutional_calendar_originals import (
    DjangoInstitutionalOriginalRepository,
)
from apps.data_center.infrastructure.institutional_calendar_repository import (
    DjangoInstitutionalCalendarRepository,
)
from apps.data_center.infrastructure.models import ProviderConfigModel, RawPayloadModel
from apps.data_center.institutional_calendar_import import import_nbs_calendar_originals
from apps.data_center.institutional_calendar_task_composition import (
    make_institutional_calendar_task,
)
from core.exceptions import DataValidationError
from tests.support.institutional_calendar_world import retained_originals

pytestmark = pytest.mark.django_db


def test_exact_originals_roundtrip_and_real_confirmed_release_are_bound() -> None:
    schedule, actual = retained_originals()
    events = import_nbs_calendar_originals(
        schedule=schedule,
        actual=actual,
        content_title="居民消费价格指数月度报告",
        event_id_prefix="nbs-cpi",
    )
    assert len(events) == 13
    originals = DjangoInstitutionalOriginalRepository()
    assert originals.read(schedule.sha256) == schedule
    assert originals.read(actual.sha256) == actual
    assert RawPayloadModel.objects.count() == 2
    assert (
        import_nbs_calendar_originals(
            schedule=schedule,
            actual=actual,
            content_title="居民消费价格指数月度报告",
            event_id_prefix="nbs-cpi",
        )
        == events
    )
    assert len(DjangoInstitutionalCalendarRepository().list_versions()) == 13
    task = make_institutional_calendar_task()
    result = task.execute(
        date(2026, 11, 1),
        date(2026, 12, 31),
        known_at=actual.recorded_at,
        checked_at=datetime.now(UTC),
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )
    assert len(result.windows) == 12
    confirmed = next(
        item for item in result.events if item.event.lifecycle is EventLifecycle.OCCURRED
    )
    assert confirmed.event.evidence is EvidenceGrade.CONFIRMED and confirmed.event.revision == 2
    assert confirmed.original == actual and confirmed.source_gap is None
    future = next(item for item in result.events if item.event_on.month == 12)
    assert future.event.lifecycle is EventLifecycle.SCHEDULED
    assert future.event.evidence is EvidenceGrade.TENTATIVE
    # Market reconstruction and actual system replay have distinct receipt clocks.
    past = task.execute(
        date(2026, 11, 1),
        date(2026, 11, 30),
        known_at=datetime(2026, 11, 9, 1, 29, tzinfo=UTC),
        checked_at=datetime.now(UTC),
        mode=KnowledgeMode.MARKET_AVAILABLE,
    )
    assert [item.event.revision for item in past.events] == [1]
    replay = task.execute(
        date(2026, 11, 1),
        date(2026, 11, 30),
        known_at=datetime(2026, 11, 10, 4, tzinfo=UTC),
        checked_at=datetime.now(UTC),
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )
    assert replay.events == ()


@pytest.mark.parametrize("tamper", ("html", "clock", "delete"))
def test_missing_or_changed_original_never_publishes_a_verified_event(tamper: str) -> None:
    schedule, actual = retained_originals()
    import_nbs_calendar_originals(
        schedule=schedule,
        actual=actual,
        content_title="居民消费价格指数月度报告",
        event_id_prefix="nbs-cpi",
    )
    row = RawPayloadModel.objects.get(request_params__original_sha256=actual.sha256)
    if tamper == "delete":
        row.delete()
    else:
        envelope = dict(row.payload)
        envelope["html" if tamper == "html" else "first_seen_at"] = "tampered"
        RawPayloadModel.objects.filter(pk=row.pk).update(payload=envelope)
    result = make_institutional_calendar_task().execute(
        date(2026, 11, 1),
        date(2026, 11, 30),
        known_at=actual.recorded_at,
        checked_at=datetime.now(UTC),
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )
    assert result.events[0].original is None
    assert result.events[0].source_gap == (
        "ORIGINAL_UNAVAILABLE" if tamper == "delete" else "ORIGINAL_INVALID"
    )


def test_source_expiry_unknown_configuration_and_future_cutoff_are_explicit() -> None:
    schedule, actual = retained_originals()
    import_nbs_calendar_originals(
        schedule=schedule,
        actual=actual,
        content_title="居民消费价格指数月度报告",
        event_id_prefix="nbs-cpi",
    )
    task = make_institutional_calendar_task()
    expired = make_institutional_calendar_task(clock=lambda: actual.policy.valid_until).execute(
        date(2026, 11, 1),
        date(2026, 11, 30),
        known_at=actual.recorded_at,
        checked_at=actual.policy.valid_until,
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )
    assert "SOURCE_POLICY_EXPIRED" in expired.gaps
    assert expired.events[0].source_gap == "SOURCE_POLICY_EXPIRED"
    with pytest.raises(DataValidationError):
        task.execute(
            date(2026, 11, 1),
            date(2026, 11, 30),
            known_at=actual.recorded_at + timedelta(days=1),
            checked_at=actual.recorded_at,
            mode=KnowledgeMode.SYSTEM_KNOWN,
        )
    ProviderConfigModel.objects.filter(name=schedule.policy.source_id).update(is_active=False)
    unknown = make_institutional_calendar_task().execute(
        date(2026, 11, 1),
        date(2026, 11, 30),
        known_at=actual.recorded_at,
        checked_at=datetime.now(UTC),
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )
    assert "SOURCE_POLICY_UNAVAILABLE" in unknown.gaps
    assert unknown.windows == ()
    assert unknown.events[0].source_gap == "SOURCE_POLICY_UNAVAILABLE"


def test_original_identity_conflict_and_unapproved_permalink_are_rejected() -> None:
    schedule, _ = retained_originals()
    originals = DjangoInstitutionalOriginalRepository()
    originals.append(schedule)
    with pytest.raises(DataValidationError):
        originals.append(replace(schedule, recorded_at=schedule.recorded_at + timedelta(seconds=1)))
    with pytest.raises(DataValidationError):
        replace(schedule, url="https://example.invalid/unapproved")
    assert originals.read(schedule.sha256) == schedule


def test_schedule_hash_and_valid_metadata_cannot_forge_actual_occurrence() -> None:
    schedule, _ = retained_originals()
    events = import_nbs_calendar_originals(
        schedule=schedule,
        actual=None,
        content_title="居民消费价格指数月度报告",
        event_id_prefix="nbs-cpi",
    )
    first = next(event for event in events if event.scheduled_at.month == 11)
    forged = replace(
        first,
        evidence=EvidenceGrade.CONFIRMED,
        lifecycle=EventLifecycle.OCCURRED,
        revision=2,
        effective_on=date(2026, 11, 9),
        source_published_at=first.scheduled_at,
        available_at=first.scheduled_at,
        supersedes_event_id=first.event_id,
    )
    DjangoInstitutionalCalendarRepository().append(forged)
    # Valid digest and receipt clocks alone do not prove an actual CPI publication.
    schedule.validate_event(forged)
    result = make_institutional_calendar_task().execute(
        date(2026, 11, 1),
        date(2026, 11, 30),
        known_at=schedule.recorded_at,
        checked_at=datetime.now(UTC),
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )
    assert result.events[0].original is None
    assert result.events[0].source_gap == "ORIGINAL_INVALID"


def test_provider_identity_overflow_is_blocked_before_any_writes() -> None:
    schedule, _ = retained_originals()
    oversized = replace(schedule, policy=replace(schedule.policy, source_id="x" * 101))
    with pytest.raises(DataValidationError):
        import_nbs_calendar_originals(
            schedule=oversized,
            actual=None,
            content_title="居民消费价格指数月度报告",
            event_id_prefix="oversized",
        )
    with pytest.raises(DataValidationError):
        DjangoInstitutionalOriginalRepository().append(oversized)
    assert RawPayloadModel.objects.count() == 0
    assert ProviderConfigModel.objects.count() == 0
