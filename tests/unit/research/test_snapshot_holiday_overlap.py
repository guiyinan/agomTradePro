"""Historical close-notice parsing and same-prediction overlap contrasts."""

import hashlib
import json
from datetime import date

import pytest

from apps.research.infrastructure import sse_holiday_overlap as overlap
from apps.research.infrastructure.sse_holiday_overlap import Closure, mark_holidays, notice_closures


def test_combined_holiday_keeps_one_identity_and_explicit_year():
    content = "（一）中秋节、国庆节：10月1日（星期日）至10月8日（星期日）休市，10月9日（星期一）起照常开市。"
    events = notice_closures(content, "2017", date(2016, 12, 22))
    assert [(r.name, r.start, r.reopens) for r in events] == [
        ("中秋节、国庆节", date(2017, 10, 1), date(2017, 10, 9))
    ]
    cross = "（一）元旦：2018年12月30日（星期日）至2019年1月1日（星期二）休市，1月2日（星期三）起照常开市。"
    assert notice_closures(cross, "2019", date(2018, 12, 20))[0].start == date(2018, 12, 30)


def test_reopening_revision_after_t2_changes_only_realized_reopening(tmp_path, monkeypatch):
    notice = Closure("春节", date(2020, 1, 24), date(2020, 1, 31), "2020", date(2019, 12, 20))
    folder = tmp_path / "later-closure-amendments"
    folder.mkdir()
    original = b"test revision"
    source = folder / "revision.html"
    source.write_bytes(original)
    change = {
        "key": "revision",
        "url": "test",
        "sha256": hashlib.sha256(original).hexdigest(),
        "publisher_declared_day": "2020-01-27",
        "annual": "2020",
        "name": "春节",
        "start": "2020-01-24",
        "previous_reopens": "2020-01-31",
        "reopens": "2020-02-03",
    }
    raw = json.dumps([change]).encode()
    (folder / "review.json").write_bytes(raw)
    monkeypatch.setattr(overlap, "AMENDMENTS_SHA256", hashlib.sha256(raw).hexdigest())
    days = (date(2020, 1, 22), date(2020, 1, 23), date(2020, 2, 3))
    sources = {}
    revised = overlap._apply_reopenings(tmp_path, [notice], sources, days[0], days[-1])
    (marker,) = mark_holidays(tuple(revised), days, days[0], days[-1])
    assert marker.origin == days[0] and marker.closure.published == notice.published
    assert (
        marker.closure.reopens == days[-1]
        and sources["revision"]["publisher_declared_day"] == "2020-01-27"
    )
    with pytest.raises(ValueError, match="original notice"):
        overlap._apply_reopenings(tmp_path, revised, {}, days[0], days[-1])
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA-256"):
        overlap._apply_reopenings(tmp_path, [notice], {}, days[0], days[-1])


def test_mark_uses_two_actual_sessions_and_detects_unexplained_gap():
    days = tuple(date(2018, 9, d) for d in (19, 20, 21, 25, 26, 27, 28))
    notice = Closure("中秋节", date(2018, 9, 22), date(2018, 9, 25), "2018", date(2017, 12, 22))
    marks = mark_holidays((notice,), days, days[0], days[-1])
    assert [m.origin for m in marks] == [date(2018, 9, 20)]
    with pytest.raises(ValueError, match="unexplained"):
        mark_holidays((notice,), days[:-2] + days[-1:], days[0], days[-1])
    with pytest.raises(ValueError, match="reopening"):
        mark_holidays((notice,), days[:3] + (date(2018, 9, 24),) + days[3:], days[0], days[-1])


def test_late_publication_and_incomplete_notice_rejected():
    c = Closure("中秋节", date(2018, 9, 22), date(2018, 9, 25), "2018", date(2018, 9, 20))
    days = tuple(date(2018, 9, d) for d in (19, 20, 21, 25))
    with pytest.raises(ValueError, match="publication"):
        mark_holidays((c,), days, days[0], days[-1])
    with pytest.raises(ValueError):
        notice_closures("（一）元旦：休市。", "2018", date(2017, 12, 22))


def test_weekend_only_and_joint_window_boundaries():
    from apps.research.infrastructure.sse_holiday_overlap import HolidayMarker, HolidayPanel
    from scripts.run_cal03_snapshot_walk_forward import _selections

    days = tuple(date(2017, 9, d) for d in (19, 20, 21, 22, 25, 26, 27, 28, 29))
    weekend = Closure("周末", date(2017, 9, 23), date(2017, 9, 25), "test", date(2016, 12, 22))
    assert not mark_holidays((weekend,), days, days[0], days[-1])
    holiday = Closure(
        "中秋节、国庆节", date(2017, 10, 1), date(2017, 10, 9), "2017", date(2016, 12, 22)
    )
    panel = HolidayPanel(days[0], days[-1], (HolidayMarker(date(2017, 9, 28), holiday),), {})
    _, selected = _selections(days, panel)
    assert selected["all"] - selected["single_event"] == {7}
    assert selected["all"] - selected["exclusive_window"] == {5, 6, 7, 8}


def test_notice_published_midwindow_excludes_whole_window_only_in_retrospective_view():
    from apps.research.infrastructure.sse_holiday_overlap import HolidayMarker, HolidayPanel
    from scripts.run_cal03_snapshot_walk_forward import _selections

    days = tuple(date(2010, 12, d) for d in (24, 27, 28, 29, 30, 31))
    closure = Closure("元旦", date(2011, 1, 1), date(2011, 1, 4), "2011", date(2010, 12, 27))
    panel = HolidayPanel(days[0], days[-1], (HolidayMarker(days[-2], closure),), {})
    _, selected = _selections(days, panel)
    assert selected["single_event"] == {0, 1, 2, 3, 5}
    assert selected["exclusive_window"] == {0}


def test_unverified_notice_archive_does_not_yield_empty_event_set(tmp_path):
    from apps.research.infrastructure.sse_holiday_overlap import load_holiday_panel

    (tmp_path / "calendar-publication-review.json").write_text("{}")
    with pytest.raises(ValueError, match="SHA-256"):
        load_holiday_panel(tmp_path, (), date(2010, 1, 4), date(2018, 12, 31))
