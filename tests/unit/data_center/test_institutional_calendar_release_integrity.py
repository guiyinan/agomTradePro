"""Actual publication requires results, actual dates and the source reference period."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from apps.data_center.infrastructure.nbs_institutional_calendar_parser import (
    parse_nbs_actual_release,
)
from core.exceptions import DataFetchError
from tests.unit.data_center.test_nbs_institutional_calendar_parser import (
    _fixture,
    _schedule,
    _schedule_input,
)


@pytest.mark.parametrize("tail", ("暂缓发布", "尚未发布", "发布预告", "同比上涨0.7%（预测）"))
def test_nonrelease_titles_do_not_confirm_actual_occurrence(tail: str) -> None:
    body = _fixture("nbs_cpi_20261109.html").decode().replace("同比上涨0.7%", tail)
    with pytest.raises(DataFetchError):
        parse_nbs_actual_release(body.encode(), source_timezone="Asia/Shanghai")


@pytest.mark.parametrize(
    "body_text", ("统计结果尚未发布。", "2026年10月份，全国居民消费价格同比上涨0.8%。")
)
def test_actual_release_requires_a_matching_result_paragraph(body_text: str) -> None:
    body = (
        _fixture("nbs_cpi_20261109.html")
        .decode()
        .replace("<p>2026年10月份，全国居民消费价格同比上涨0.7%。</p>", "<p>" + body_text + "</p>")
    )
    with pytest.raises(DataFetchError):
        parse_nbs_actual_release(body.encode(), source_timezone="Asia/Shanghai")


def test_delayed_release_keeps_plan_but_uses_actual_local_publication_date() -> None:
    schedule = _schedule_input(_schedule())
    body = _fixture("nbs_cpi_20261109.html").replace(b"2026/11/09 09:30", b"2026/11/10 09:30")
    release = parse_nbs_actual_release(body, source_timezone="Asia/Shanghai")
    event = release.to_input(
        schedule,
        first_seen_at=datetime(2026, 11, 10, 2, tzinfo=UTC),
        recorded_at=datetime(2026, 11, 10, 2, 1, tzinfo=UTC),
    ).to_event(schedule.to_event())
    assert event.scheduled_at == schedule.scheduled_at
    assert event.effective_on == date(2026, 11, 10)


@pytest.mark.parametrize("content_title", ("工业生产者出厂价格指数月度报告", "其他统计月度报告"))
def test_cpi_actual_cannot_confirm_another_schedule_row_even_at_the_same_time(
    content_title: str,
) -> None:
    entry = next(entry for entry in _schedule().entries if entry.scheduled_month == 11)
    foreign = replace(entry, content_title=content_title).to_input(
        event_id="other-release",
        source_id="nbs",
        source_event_id="other-2026-11",
        event_type="other_release",
        title=content_title,
        first_seen_at=datetime(2026, 11, 9, 2, tzinfo=UTC),
        recorded_at=datetime(2026, 11, 9, 2, 1, tzinfo=UTC),
    )
    actual = parse_nbs_actual_release(
        _fixture("nbs_cpi_20261109.html"), source_timezone="Asia/Shanghai"
    )
    with pytest.raises(DataFetchError) as caught:
        actual.to_input(
            foreign,
            first_seen_at=datetime(2026, 11, 9, 2, tzinfo=UTC),
            recorded_at=datetime(2026, 11, 9, 2, 1, tzinfo=UTC),
        )
    assert caught.value.code == "NBS_ACTUAL_EVENT_CLASS_MISMATCH"


def test_public_actual_cannot_be_recorded_as_occurred_before_its_publication() -> None:
    schedule = _schedule_input(_schedule())
    actual = parse_nbs_actual_release(
        _fixture("nbs_cpi_20261109.html"), source_timezone="Asia/Shanghai"
    )
    normalized = actual.to_input(
        schedule,
        first_seen_at=datetime(2026, 11, 9, 1, 29, tzinfo=UTC),
        recorded_at=datetime(2026, 11, 9, 1, 29, 1, tzinfo=UTC),
    )
    with pytest.raises(DataFetchError) as caught:
        normalized.to_event(schedule.to_event())
    assert caught.value.code == "NBS_ACTUAL_NOT_AVAILABLE_AT_FIRST_SEEN"
