"""Public institutional-calendar composition binds exact-version read ports."""

from datetime import UTC, date, datetime

import pytest

import apps.data_center.institutional_calendar_composition as composition
from apps.data_center.domain.institutional_calendar import (
    EventLifecycle,
    EvidenceGrade,
    InstitutionalEvent,
    KnowledgeMode,
)


class _Repository:
    """Return exact event versions without exposing any write or ORM API."""

    def list_versions(self) -> tuple[InstitutionalEvent, ...]:
        """Return one scheduled event for the composed public query."""

        return (
            InstitutionalEvent(
                event_id="nbs-cpi-2026-10",
                source_id="nbs_official",
                source_event_id="2026-schedule-cpi-october",
                event_type="macro_release",
                title="2026年10月份居民消费价格",
                evidence=EvidenceGrade.TENTATIVE,
                lifecycle=EventLifecycle.SCHEDULED,
                revision=1,
                scheduled_at=datetime(2026, 11, 9, 16, 0, tzinfo=UTC),
                effective_on=None,
                source_published_at=datetime(2025, 12, 25, 1, 30, tzinfo=UTC),
                source_published_on=None,
                available_at=datetime(2025, 12, 25, 1, 30, tzinfo=UTC),
                first_seen_at=datetime(2026, 1, 2, tzinfo=UTC),
                recorded_at=datetime(2026, 1, 2, 0, 1, tzinfo=UTC),
                original_sha256="a" * 64,
                supersedes_event_id=None,
            ),
        )


def test_public_reader_binds_alias_timezone_and_exact_version_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The composed reader uses the requested alias and local calendar date."""

    aliases: list[str] = []

    def repository_factory(*, using: str = "default") -> _Repository:
        aliases.append(using)
        return _Repository()

    monkeypatch.setattr(composition, "DjangoInstitutionalCalendarRepository", repository_factory)
    query = composition.make_institutional_calendar_query(
        using="calendar_read", timezone_name="Asia/Shanghai"
    )

    entries = query.execute(
        date(2026, 11, 10),
        date(2026, 11, 10),
        known_at=datetime(2026, 11, 10, 2, 0, tzinfo=UTC),
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )

    assert aliases == ["calendar_read"]
    assert [entry.event_on for entry in entries] == [date(2026, 11, 10)]
    assert [entry.event.event_id for entry in entries] == ["nbs-cpi-2026-10"]
