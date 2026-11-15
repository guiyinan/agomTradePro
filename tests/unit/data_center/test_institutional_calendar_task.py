"""Calendar task boundaries without Django database or source-network access."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.data_center.application.institutional_calendar_query import (
    QueryInstitutionalCalendarUseCase,
)
from apps.data_center.application.institutional_calendar_sources import (
    InstitutionalSourcePolicy,
    RetainedInstitutionalOriginal,
)
from apps.data_center.application.institutional_calendar_task import ReadInstitutionalCalendarTask
from apps.data_center.domain.institutional_calendar import InstitutionalEvent, KnowledgeMode
from core.exceptions import DataValidationError
from tests.component.data_center.test_institutional_calendar_repository import _event
from tests.support.institutional_calendar_world import retained_originals


@dataclass
class Sources:
    original: RetainedInstitutionalOriginal
    qualified: bool = True
    verified: bool = True
    clock_at: datetime | None = None
    after_verify_clock: datetime | None = None
    revoke_after_verify: bool = False

    def read_policy(self) -> InstitutionalSourcePolicy | None:
        return self.original.policy if self.qualified else None

    def read(self, sha256: str) -> RetainedInstitutionalOriginal | None:
        return self.original if sha256 == self.original.sha256 else None

    def verify_event(
        self, event: InstitutionalEvent, original: RetainedInstitutionalOriginal
    ) -> bool:
        if self.after_verify_clock is not None:
            self.clock_at = self.after_verify_clock
        if self.revoke_after_verify:
            self.qualified = False
        return self.verified

    def now(self) -> datetime:
        return datetime.now(UTC) if self.clock_at is None else self.clock_at


@dataclass
class Versions:
    event: InstitutionalEvent

    def list_versions(self) -> tuple[InstitutionalEvent, ...]:
        return (self.event,)


def task_world(
    *, qualified: bool = True
) -> tuple[ReadInstitutionalCalendarTask, Sources, datetime]:
    schedule, _ = retained_originals()
    event = _event(
        source_id=schedule.policy.source_id,
        event_type=schedule.policy.event_type,
        original_sha256=schedule.sha256,
        first_seen_at=schedule.first_seen_at,
        recorded_at=schedule.recorded_at,
    )
    sources = Sources(schedule, qualified=qualified)
    query = QueryInstitutionalCalendarUseCase(
        Versions(event), timezone_name=schedule.policy.timezone_name
    )
    return (
        ReadInstitutionalCalendarTask(
            query, sources, sources, policy=sources.read_policy(), clock=sources.now
        ),
        sources,
        schedule.recorded_at,
    )


@pytest.mark.parametrize("kind", ("unknown", "expired", "unverified"))
def test_source_qualification_integrity_and_expiry_remain_distinct_gaps(kind: str) -> None:
    task, sources, cutoff = task_world(qualified=kind != "unknown")
    if kind == "unverified":
        sources.verified = False
    checked_at = sources.original.policy.valid_until if kind == "expired" else datetime.now(UTC)
    sources.clock_at = checked_at
    result = task.execute(
        date(2026, 11, 1),
        date(2026, 11, 30),
        known_at=cutoff,
        checked_at=checked_at,
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )
    assert (
        result.events[0].source_gap
        == {
            "unknown": "SOURCE_POLICY_UNAVAILABLE",
            "expired": "SOURCE_POLICY_EXPIRED",
            "unverified": "ORIGINAL_INVALID",
        }[kind]
    )
    assert "EVENT_STUDY_NOT_COMPLETED" in result.gaps


@pytest.mark.parametrize("kind", ("future", "naive", "inverted", "unbounded"))
def test_invalid_knowledge_time_or_date_range_never_reaches_a_view(kind: str) -> None:
    task, _, cutoff = task_world()
    start, end = date(2026, 11, 1), date(2026, 11, 30)
    known_at = (
        cutoff + timedelta(days=1)
        if kind == "future"
        else cutoff.replace(tzinfo=None) if kind == "naive" else cutoff
    )
    if kind == "inverted":
        start, end = end, start
    if kind == "unbounded":
        end = date(2028, 1, 1)
    with pytest.raises(DataValidationError):
        task.execute(
            start, end, known_at=known_at, checked_at=cutoff, mode=KnowledgeMode.SYSTEM_KNOWN
        )


@pytest.mark.parametrize("change", ("expiry", "policy"))
def test_source_lease_and_policy_are_rechecked_after_original_verification(change: str) -> None:
    task, sources, cutoff = task_world()
    if change == "expiry":
        sources.after_verify_clock = sources.original.policy.valid_until
    else:
        sources.revoke_after_verify = True
    result = task.execute(
        date(2026, 11, 1),
        date(2026, 11, 30),
        known_at=cutoff,
        checked_at=cutoff,
        mode=KnowledgeMode.SYSTEM_KNOWN,
    )
    expected = "SOURCE_POLICY_EXPIRED" if change == "expiry" else "SOURCE_POLICY_CHANGED"
    assert expected in result.gaps
    assert result.events[0].source_gap == expected
    assert result.policy == sources.original.policy
