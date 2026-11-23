"""Read retained SSE closure notices for the early, retrospective CAL-03 snapshot."""

from __future__ import annotations

import hashlib
import json
import re
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

REVIEW_SHA256 = "e4a5bd7732991c153dadecd5e104c771da39620c218347e6db8cd388dcf19bef"
_DAY = re.compile(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日")
_CLAUSE = re.compile(r"[（(][一二三四五六七][）)]([^。；：:]{1,15})[：:]([^。；]*?照常开市)")
_HOLIDAYS = {"元旦", "春节", "清明节", "劳动节", "端午节", "中秋节", "国庆节"}


@dataclass(frozen=True)
class Closure:
    """One announced closure episode, including jointly scheduled holidays."""

    name: str
    start: date
    reopens: date
    notice: str
    published: date


@dataclass(frozen=True)
class HolidayMarker:
    """The second observed trading session strictly before the closure starts."""

    origin: date
    closure: Closure


@dataclass(frozen=True)
class HolidayPanel:
    """Markers, checked coverage, and the retained official sources."""

    start: date
    end: date
    markers: tuple[HolidayMarker, ...]
    sources: dict[str, dict[str, str]]


def notice_closures(text: str, key: str, published: date) -> tuple[Closure, ...]:
    """Parse start and reopening dates, including explicit cross-year dates."""
    plain = "".join(text.split())
    year = int(key[:4])
    if key == "2015_special_closure":
        match = re.search(r"一、休市安排[：:]([^。]+?照常开市)", plain)
        clauses = [("抗战胜利纪念日", match[1])] if match else []
    else:
        clauses = _CLAUSE.findall(plain)
    if not clauses:
        raise ValueError(f"No closure clauses in {key}")
    events = []
    for name, clause in clauses:
        parts = _DAY.findall(clause)
        if len(parts) not in (2, 3) or not _DAY.match(clause):
            raise ValueError(f"Invalid closure dates in {key}/{name}")
        dates = [date(int(y or year), int(m), int(d)) for y, m, d in parts]
        if not dates[0] < dates[-1] or dates != sorted(dates):
            raise ValueError(f"Invalid reopening in {key}/{name}")
        events.append(Closure(name, dates[0], dates[-1], key, published))
    return tuple(events)


def mark_holidays(
    closures: tuple[Closure, ...], sessions: tuple[date, ...], start: date, end: date
) -> tuple[HolidayMarker, ...]:
    """Project T-2 onto sessions and reconcile every covered closed weekday."""
    if (
        not sessions
        or sessions != tuple(sorted(set(sessions)))
        or not sessions[0] <= start <= end <= sessions[-1]
    ):
        raise ValueError("Incomplete session axis for event coverage")
    closed: set[date] = set()
    markers = []
    for c in closures:
        if c.reopens <= start or c.start > sessions[-1]:
            continue
        idx = bisect_left(sessions, c.start)
        if idx >= len(sessions) or sessions[idx] != c.reopens:
            raise ValueError(f"Notice reopening disagrees with calendar for {c.notice}/{c.name}")
        weekdays = {
            c.start + timedelta(days=i)
            for i in range((c.reopens - c.start).days)
            if (c.start + timedelta(days=i)).weekday() < 5
        }
        if closed & weekdays:
            raise ValueError("Closure intervals double-count the same weekday")
        closed.update(weekdays)
        # A named holiday confined to the normal weekend is not an extra closure.
        if not weekdays or idx < 2 or not start <= sessions[idx - 2] <= end:
            continue
        origin = sessions[idx - 2]
        if c.published >= origin:
            raise ValueError(f"Notice publication too late for {c.notice}/{c.name}")
        markers.append(HolidayMarker(origin, c))
    trading = set(sessions)
    for i in range((end - start).days + 1):
        day = start + timedelta(days=i)
        if day.weekday() < 5 and day not in closed and day not in trading:
            raise ValueError(f"Calendar has unexplained closed weekday: {day}")
    return tuple(sorted(markers, key=lambda m: m.origin))


def load_holiday_panel(
    archive: Path, sessions: tuple[date, ...], start: date, end: date
) -> HolidayPanel:
    """Verify the pinned publication review and all applicable early notice originals."""
    review = (archive / "calendar-publication-review.json").read_bytes()
    if hashlib.sha256(review).hexdigest() != REVIEW_SHA256:
        raise ValueError("SHA-256 mismatch for holiday publication review")
    records = {r["key"]: r for r in json.loads(review)["records"]}
    # The following New Year may mark T-2 in December of the preceding year.
    keys = [str(y) for y in range(start.year, end.year + 2)] + ["2015_special_closure"]
    sources = {}
    closures: list[Closure] = []
    for key in keys:
        r = records[key]
        raw = (archive / "calendar-originals" / f"{key}.html").read_bytes()
        if hashlib.sha256(raw).hexdigest() != r["sha256"]:
            raise ValueError(f"SHA-256 mismatch for holiday notice {key}")
        if r["publisher_precision"] != "DAY" or r["publication_metadata_conflict"]:
            raise ValueError(f"Unresolved publication date for {key}")
        text = BeautifulSoup(raw, "html.parser", from_encoding="utf-8").get_text()
        events = notice_closures(text, key, date.fromisoformat(r["publisher_declared_day"]))
        if key.isdecimal():
            names = [name for e in events for name in e.name.split("、")]
            if sorted(names) != sorted(_HOLIDAYS):
                raise ValueError(f"Annual holiday inventory incomplete for {key}")
        closures.extend(events)
        sources[key] = {k: r[k] for k in ("url", "sha256", "publisher_declared_day")}
    next_year = next(c for c in closures if c.notice == str(end.year + 1) and c.name == "元旦")
    axis = sessions[: bisect_left(sessions, next_year.reopens) + 1]
    return HolidayPanel(start, end, mark_holidays(tuple(closures), axis, start, end), sources)
