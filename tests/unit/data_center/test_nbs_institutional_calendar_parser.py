"""NBS retained HTML becomes exact schedule and actual-release inputs."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.data_center.application.institutional_calendar import NbsScheduleInput
from apps.data_center.domain.institutional_calendar import EventLifecycle, EvidenceGrade
from apps.data_center.infrastructure.nbs_institutional_calendar_parser import (
    NbsScheduleDocument,
    parse_nbs_actual_release,
    parse_nbs_schedule,
)
from core.exceptions import DataFetchError

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "data_center" / "institutional_calendar"
_CONTENT_TITLE = "居民消费价格指数月度报告"


def _fixture(name: str) -> bytes:
    return (Path(_FIXTURES) / name).read_bytes()


def _schedule() -> NbsScheduleDocument:
    return parse_nbs_schedule(
        _fixture("nbs_2026_schedule_cpi.html"),
        content_title=_CONTENT_TITLE,
        source_timezone="Asia/Shanghai",
    )


def _schedule_input(document: NbsScheduleDocument) -> NbsScheduleInput:
    entry = next(item for item in document.entries if item.scheduled_month == 11)
    return entry.to_input(
        event_id="nbs-cpi-2026-10",
        source_id="nbs_official",
        source_event_id="2026-schedule-cpi-october",
        event_type="macro_release",
        title="2026年10月份居民消费价格",
        first_seen_at=datetime(2026, 1, 2, tzinfo=UTC),
        recorded_at=datetime(2026, 1, 2, 0, 1, tzinfo=UTC),
    )


def test_real_schedule_rowspans_and_actual_release_form_a_revision_chain() -> None:
    schedule_body = _fixture("nbs_2026_schedule_cpi.html")
    document = _schedule()

    assert document.title == "2026年国家统计局主要统计信息发布日程表"
    assert document.source_published_at == datetime(2025, 12, 25, 1, 30, tzinfo=UTC)
    assert document.original_sha256 == hashlib.sha256(schedule_body).hexdigest()
    assert len(document.entries) == 12
    assert document.entries[0].scheduled_at == datetime(2026, 1, 9, 1, 30, tzinfo=UTC)
    assert document.entries[-1].scheduled_at == datetime(2026, 12, 9, 1, 30, tzinfo=UTC)

    schedule_input = _schedule_input(document)
    schedule = schedule_input.to_event()
    actual_body = _fixture("nbs_cpi_20261109.html")
    parsed_actual = parse_nbs_actual_release(actual_body, source_timezone="Asia/Shanghai")
    actual_input = parsed_actual.to_input(
        schedule_input,
        first_seen_at=datetime(2026, 11, 9, 1, 31, tzinfo=UTC),
        recorded_at=datetime(2026, 11, 9, 1, 32, tzinfo=UTC),
    )
    actual = actual_input.to_event(schedule)

    assert parsed_actual.title == "2026年10月份居民消费价格同比上涨0.7%"
    assert parsed_actual.original_sha256 == hashlib.sha256(actual_body).hexdigest()
    assert schedule.lifecycle is EventLifecycle.SCHEDULED
    assert schedule.evidence is EvidenceGrade.TENTATIVE
    assert actual.lifecycle is EventLifecycle.OCCURRED
    assert actual.evidence is EvidenceGrade.CONFIRMED
    assert actual.revision == 2
    assert actual.effective_on == schedule.scheduled_at.date()
    assert actual.original_sha256 != schedule.original_sha256


def test_conflicting_desktop_and_mobile_schedule_copies_fail_closed() -> None:
    body = _fixture("nbs_2026_schedule_cpi.html")
    needle = "<td>9/一</td><td>9/三</td>".encode()
    first = body.index(needle)
    second = body.index(needle, first + len(needle))
    conflict = "<td>10/二</td><td>9/三</td>".encode()
    changed = body[:second] + conflict + body[second + len(needle) :]

    with pytest.raises(DataFetchError) as caught:
        parse_nbs_schedule(
            changed,
            content_title=_CONTENT_TITLE,
            source_timezone="Asia/Shanghai",
        )

    assert caught.value.code == "NBS_SCHEDULE_DUPLICATE_CONFLICT"


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        ('name="PubDate"', 'name="PublicationDate"', "NBS_METADATA_MISSING"),
        (
            '<meta name="ArticleTitle" content="2026年国家统计局主要统计信息发布日程表">',
            '<meta name="ArticleTitle" content="2026年国家统计局主要统计信息发布日程表"><meta name="ArticleTitle" content="duplicate">',
            "NBS_METADATA_AMBIGUOUS",
        ),
        ("2025/12/25 09:30", "2025/12/25 09:30:00", "NBS_PUBLICATION_TIME_INVALID"),
        ("<td>9/五</td>", "<td>10/五</td>", "NBS_SCHEDULE_WEEKDAY_MISMATCH"),
        ("<td>9:30</td>", "<td>……</td>", "NBS_SCHEDULE_TIME_INVALID"),
        ("<td>9:30</td>", "", "NBS_SCHEDULE_TABLE_INVALID"),
        (_CONTENT_TITLE, "其他报告", "NBS_SCHEDULE_CONTENT_NOT_FOUND"),
    ],
)
def test_invalid_schedule_metadata_and_cells_are_rejected(old: str, new: str, code: str) -> None:
    body = _fixture("nbs_2026_schedule_cpi.html").decode()
    changed = body.replace(old, new, 1).encode()

    with pytest.raises(DataFetchError) as caught:
        parse_nbs_schedule(
            changed,
            content_title=_CONTENT_TITLE,
            source_timezone="Asia/Shanghai",
        )

    assert caught.value.code == code


def test_unknown_timezone_and_non_utf8_originals_are_rejected() -> None:
    with pytest.raises(DataFetchError) as caught:
        parse_nbs_schedule(
            _fixture("nbs_2026_schedule_cpi.html"),
            content_title=_CONTENT_TITLE,
            source_timezone="Mars/Olympus",
        )
    assert caught.value.code == "NBS_SOURCE_TIMEZONE_INVALID"

    with pytest.raises(DataFetchError) as caught:
        parse_nbs_actual_release(b"\xff\xfe", source_timezone="Asia/Shanghai")
    assert caught.value.code == "NBS_HTML_ENCODING_INVALID"


def test_actual_release_rejects_wrong_period_or_early_publication() -> None:
    schedule_input = _schedule_input(_schedule())
    actual = parse_nbs_actual_release(
        _fixture("nbs_cpi_20261109.html"), source_timezone="Asia/Shanghai"
    )

    with pytest.raises(DataFetchError) as caught:
        replace(actual, reference_month=9).to_input(
            schedule_input,
            first_seen_at=datetime(2026, 11, 9, 1, 31, tzinfo=UTC),
            recorded_at=datetime(2026, 11, 9, 1, 32, tzinfo=UTC),
        )
    assert caught.value.code == "NBS_ACTUAL_REFERENCE_PERIOD_MISMATCH"

    with pytest.raises(DataFetchError) as caught:
        replace(actual, source_published_at=schedule_input.scheduled_at).to_input(
            replace(
                schedule_input,
                scheduled_at=datetime(2026, 11, 9, 2, 0, tzinfo=UTC),
            ),
            first_seen_at=datetime(2026, 11, 9, 1, 31, tzinfo=UTC),
            recorded_at=datetime(2026, 11, 9, 1, 32, tzinfo=UTC),
        )
    assert caught.value.code == "NBS_ACTUAL_SCHEDULE_MISMATCH"


def test_actual_release_requires_exact_title_and_minute_publication_metadata() -> None:
    body = _fixture("nbs_cpi_20261109.html").decode()
    missing_title = body.replace('name="ArticleTitle"', 'name="Title"', 1).encode()
    with pytest.raises(DataFetchError) as caught:
        parse_nbs_actual_release(missing_title, source_timezone="Asia/Shanghai")
    assert caught.value.code == "NBS_METADATA_MISSING"

    unsupported_period = body.replace("2026年10月份居民消费价格", "居民消费价格", 1).encode()
    with pytest.raises(DataFetchError) as caught:
        parse_nbs_actual_release(unsupported_period, source_timezone="Asia/Shanghai")
    assert caught.value.code == "NBS_ACTUAL_TITLE_INVALID"
