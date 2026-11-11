"""Strict offline normalization of retained NBS schedule and actual-release HTML."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.data_center.application.institutional_calendar import (
    NbsActualReleaseInput,
    NbsScheduleInput,
)
from core.exceptions import DataFetchError

_SCHEDULE_TITLE_RE = re.compile(r"^(?P<year>[0-9]{4})年国家统计局主要统计信息发布日程表$")
_ACTUAL_TITLE_RE = re.compile(r"^(?P<year>[0-9]{4})年(?P<month>1[0-2]|[1-9])月份居民消费价格\S+$")
_PUBLICATION_TIME_RE = re.compile(r"^[0-9]{4}/[0-9]{2}/[0-9]{2} [0-9]{2}:[0-9]{2}$")
_SCHEDULE_DAY_RE = re.compile(r"^(?P<day>[1-9]|[12][0-9]|3[01])/(?P<weekday>[一二三四五六日])$")
_SCHEDULE_TIME_RE = re.compile(r"^(?P<hour>[01]?[0-9]|2[0-3]):(?P<minute>[0-5][0-9])$")
_SPAN_RE = re.compile(r"^[1-9][0-9]*$")
_SCHEDULE_HEADER = ("序号", "内容", *(f"{month}月" for month in range(1, 13)))
_WEEKDAYS = ("一", "二", "三", "四", "五", "六", "日")


@dataclass(frozen=True, slots=True)
class NbsScheduleEntry:
    """One source-normalized scheduled publication with exact original evidence."""

    content_title: str
    scheduled_month: int
    scheduled_at: datetime
    source_published_at: datetime
    original_sha256: str

    def to_input(
        self,
        *,
        event_id: str,
        source_id: str,
        source_event_id: str,
        event_type: str,
        title: str,
        first_seen_at: datetime,
        recorded_at: datetime,
    ) -> NbsScheduleInput:
        """Bind parsed evidence to caller-owned identity, type, and system clocks."""

        return NbsScheduleInput(
            event_id=event_id,
            source_id=source_id,
            source_event_id=source_event_id,
            event_type=event_type,
            title=title,
            scheduled_at=self.scheduled_at,
            source_published_at=self.source_published_at,
            first_seen_at=first_seen_at,
            recorded_at=recorded_at,
            original_sha256=self.original_sha256,
        )


@dataclass(frozen=True, slots=True)
class NbsScheduleDocument:
    """One exact NBS schedule document and its non-duplicated typed entries."""

    title: str
    source_published_at: datetime
    original_sha256: str
    entries: tuple[NbsScheduleEntry, ...]


@dataclass(frozen=True, slots=True)
class NbsActualRelease:
    """One exact NBS CPI publication with its source-derived reference period."""

    title: str
    reference_year: int
    reference_month: int
    source_published_at: datetime
    source_timezone: str
    original_sha256: str

    def to_input(
        self,
        schedule: NbsScheduleInput,
        *,
        first_seen_at: datetime,
        recorded_at: datetime,
    ) -> NbsActualReleaseInput:
        """Match an actual CPI release to its schedule without changing event identity."""

        if not isinstance(schedule, NbsScheduleInput):
            raise DataFetchError(
                "NBS actual release requires a typed schedule",
                code="NBS_ACTUAL_SCHEDULE_MISMATCH",
            )
        schedule.to_event()
        if self.source_published_at < schedule.scheduled_at:
            raise DataFetchError(
                "NBS actual publication precedes its scheduled release",
                code="NBS_ACTUAL_SCHEDULE_MISMATCH",
            )
        try:
            zone = ZoneInfo(self.source_timezone)
        except ZoneInfoNotFoundError as exc:
            raise DataFetchError(
                "NBS actual source timezone is unknown",
                code="NBS_SOURCE_TIMEZONE_INVALID",
            ) from exc
        local_schedule = schedule.scheduled_at.astimezone(zone)
        expected_year = local_schedule.year
        expected_month = local_schedule.month - 1
        if expected_month == 0:
            expected_year -= 1
            expected_month = 12
        if (self.reference_year, self.reference_month) != (expected_year, expected_month):
            raise DataFetchError(
                "NBS actual release reference period does not match its schedule",
                code="NBS_ACTUAL_REFERENCE_PERIOD_MISMATCH",
            )
        return NbsActualReleaseInput(
            source_id=schedule.source_id,
            source_event_id=schedule.source_event_id,
            event_type=schedule.event_type,
            title=schedule.title,
            scheduled_at=schedule.scheduled_at,
            source_published_at=self.source_published_at,
            first_seen_at=first_seen_at,
            recorded_at=recorded_at,
            original_sha256=self.original_sha256,
        )


@dataclass(slots=True)
class _RawCell:
    tag: str
    rowspan: int
    colspan: int
    parts: list[str] = field(default_factory=list)
    text: str = ""


@dataclass(slots=True)
class _RawRow:
    cells: list[_RawCell] = field(default_factory=list)


@dataclass(slots=True)
class _RawTable:
    rows: list[_RawRow] = field(default_factory=list)


class _NbsHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metadata: dict[str, list[str]] = {}
        self.tables: list[_RawTable] = []
        self._table: _RawTable | None = None
        self._row: _RawRow | None = None
        self._cell: _RawCell | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = _attributes(attrs)
        if tag == "meta":
            name = attributes.get("name")
            if name is not None:
                self.metadata.setdefault(name, []).append(attributes.get("content") or "")
            return
        if tag == "table":
            if self._table is not None:
                raise DataFetchError(
                    "Nested NBS tables are unsupported",
                    code="NBS_HTML_STRUCTURE_INVALID",
                )
            self._table = _RawTable()
            return
        if tag == "br" and self._cell is not None:
            self._cell.parts.append("\n")
            return
        if self._table is None:
            return
        if tag == "tr":
            if self._row is not None or self._cell is not None:
                raise DataFetchError(
                    "NBS table row structure is invalid",
                    code="NBS_HTML_STRUCTURE_INVALID",
                )
            self._row = _RawRow()
            return
        if tag in {"td", "th"}:
            if self._row is None or self._cell is not None:
                raise DataFetchError(
                    "NBS table cell structure is invalid",
                    code="NBS_HTML_STRUCTURE_INVALID",
                )
            self._cell = _RawCell(
                tag=tag,
                rowspan=_span(attributes.get("rowspan")),
                colspan=_span(attributes.get("colspan")),
            )

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._table is not None:
            if self._cell is None or self._row is None or self._cell.tag != tag:
                raise DataFetchError(
                    "NBS table cell is not closed consistently",
                    code="NBS_HTML_STRUCTURE_INVALID",
                )
            self._cell.text = " ".join("".join(self._cell.parts).split())
            self._row.cells.append(self._cell)
            self._cell = None
            return
        if tag == "tr" and self._table is not None:
            if self._row is None or self._cell is not None:
                raise DataFetchError(
                    "NBS table row is not closed consistently",
                    code="NBS_HTML_STRUCTURE_INVALID",
                )
            self._table.rows.append(self._row)
            self._row = None
            return
        if tag == "table":
            if self._table is None or self._row is not None or self._cell is not None:
                raise DataFetchError(
                    "NBS table is not closed consistently",
                    code="NBS_HTML_STRUCTURE_INVALID",
                )
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.parts.append(data)

    def validate_closed(self) -> None:
        if self._table is not None or self._row is not None or self._cell is not None:
            raise DataFetchError(
                "NBS table document is incomplete",
                code="NBS_HTML_STRUCTURE_INVALID",
            )


def parse_nbs_schedule(
    body: bytes, *, content_title: str, source_timezone: str
) -> NbsScheduleDocument:
    """Parse one named schedule row from exact retained NBS HTML bytes."""

    zone = _source_timezone(source_timezone)
    parser = _parse_html(body)
    title = _metadata(parser, "ArticleTitle")
    title_match = _SCHEDULE_TITLE_RE.fullmatch(title)
    if title_match is None:
        raise DataFetchError(
            "NBS schedule document title is unsupported",
            code="NBS_SCHEDULE_TITLE_INVALID",
        )
    year = int(title_match.group("year"))
    source_published_at = _publication_time(_metadata(parser, "PubDate"), zone)
    tables = [table for table in parser.tables if _has_schedule_header(table)]
    if not tables:
        raise DataFetchError(
            "NBS schedule table is missing",
            code="NBS_SCHEDULE_TABLE_NOT_FOUND",
        )
    original_sha256 = hashlib.sha256(body).hexdigest()
    entries_by_month: dict[int, NbsScheduleEntry] = {}
    for table in tables:
        rows = _expand_table(table)
        if not rows or rows[0] != _SCHEDULE_HEADER:
            raise DataFetchError(
                "NBS schedule table header is invalid",
                code="NBS_SCHEDULE_TABLE_INVALID",
            )
        matching_rows = [index for index, row in enumerate(rows) if row[1] == content_title]
        paired_rows = [
            index
            for index in matching_rows
            if index + 1 < len(rows) and rows[index + 1][:2] == rows[index][:2]
        ]
        if not paired_rows:
            raise DataFetchError(
                "NBS schedule content or its time row is missing",
                code=(
                    "NBS_SCHEDULE_TABLE_INVALID"
                    if matching_rows
                    else "NBS_SCHEDULE_CONTENT_NOT_FOUND"
                ),
            )
        if len(paired_rows) != 1:
            raise DataFetchError(
                "NBS schedule content must occur exactly once per table",
                code="NBS_SCHEDULE_CONTENT_AMBIGUOUS",
            )
        row_index = paired_rows[0]
        for month in range(1, 13):
            scheduled_at = _schedule_datetime(
                year,
                month,
                rows[row_index][month + 1],
                rows[row_index + 1][month + 1],
                zone,
            )
            if scheduled_at is None:
                continue
            entry = NbsScheduleEntry(
                content_title=content_title,
                scheduled_month=month,
                scheduled_at=scheduled_at,
                source_published_at=source_published_at,
                original_sha256=original_sha256,
            )
            previous = entries_by_month.get(month)
            if previous is not None and previous != entry:
                raise DataFetchError(
                    "NBS desktop and mobile schedules disagree",
                    code="NBS_SCHEDULE_DUPLICATE_CONFLICT",
                )
            entries_by_month[month] = entry
    if not entries_by_month:
        raise DataFetchError(
            "NBS schedule content has no dated releases",
            code="NBS_SCHEDULE_CONTENT_NOT_FOUND",
        )
    return NbsScheduleDocument(
        title=title,
        source_published_at=source_published_at,
        original_sha256=original_sha256,
        entries=tuple(entries_by_month[month] for month in sorted(entries_by_month)),
    )


def parse_nbs_actual_release(body: bytes, *, source_timezone: str) -> NbsActualRelease:
    """Parse exact NBS CPI actual-release metadata from retained HTML bytes."""

    zone = _source_timezone(source_timezone)
    parser = _parse_html(body)
    title = _metadata(parser, "ArticleTitle")
    title_match = _ACTUAL_TITLE_RE.fullmatch(title)
    if title_match is None:
        raise DataFetchError(
            "NBS actual CPI title or reference period is unsupported",
            code="NBS_ACTUAL_TITLE_INVALID",
        )
    return NbsActualRelease(
        title=title,
        reference_year=int(title_match.group("year")),
        reference_month=int(title_match.group("month")),
        source_published_at=_publication_time(_metadata(parser, "PubDate"), zone),
        source_timezone=source_timezone,
        original_sha256=hashlib.sha256(body).hexdigest(),
    )


def _parse_html(body: bytes) -> _NbsHTMLParser:
    if type(body) is not bytes or not body:
        raise DataFetchError(
            "NBS original must be non-empty bytes",
            code="NBS_HTML_ENCODING_INVALID",
        )
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DataFetchError(
            "NBS retained HTML must be exact UTF-8 bytes",
            code="NBS_HTML_ENCODING_INVALID",
        ) from exc
    parser = _NbsHTMLParser()
    try:
        parser.feed(text)
        parser.close()
    except (ValueError, AssertionError) as exc:
        raise DataFetchError(
            "NBS HTML cannot be parsed safely",
            code="NBS_HTML_STRUCTURE_INVALID",
        ) from exc
    parser.validate_closed()
    return parser


def _attributes(attrs: list[tuple[str, str | None]]) -> dict[str, str | None]:
    attributes: dict[str, str | None] = {}
    for name, value in attrs:
        if name in attributes:
            raise DataFetchError(
                "NBS HTML contains duplicate attributes",
                code="NBS_HTML_STRUCTURE_INVALID",
            )
        attributes[name] = value
    return attributes


def _span(value: str | None) -> int:
    if value is None:
        return 1
    if _SPAN_RE.fullmatch(value) is None or int(value) > 100:
        raise DataFetchError(
            "NBS table span is invalid",
            code="NBS_SCHEDULE_TABLE_INVALID",
        )
    return int(value)


def _metadata(parser: _NbsHTMLParser, name: str) -> str:
    values = parser.metadata.get(name, [])
    if not values:
        raise DataFetchError(
            f"NBS metadata {name} is missing",
            code="NBS_METADATA_MISSING",
        )
    if len(values) != 1:
        raise DataFetchError(
            f"NBS metadata {name} is ambiguous",
            code="NBS_METADATA_AMBIGUOUS",
        )
    value = values[0].strip()
    if not value:
        raise DataFetchError(
            f"NBS metadata {name} is empty",
            code="NBS_METADATA_MISSING",
        )
    return value


def _source_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, TypeError) as exc:
        raise DataFetchError(
            "NBS source timezone is unknown",
            code="NBS_SOURCE_TIMEZONE_INVALID",
        ) from exc


def _publication_time(value: str, zone: ZoneInfo) -> datetime:
    if _PUBLICATION_TIME_RE.fullmatch(value) is None:
        raise DataFetchError(
            "NBS publication time must have exact minute precision",
            code="NBS_PUBLICATION_TIME_INVALID",
        )
    try:
        local = datetime.strptime(value, "%Y/%m/%d %H:%M")
    except ValueError as exc:
        raise DataFetchError(
            "NBS publication time is invalid",
            code="NBS_PUBLICATION_TIME_INVALID",
        ) from exc
    return local.replace(tzinfo=zone).astimezone(UTC)


def _has_schedule_header(table: _RawTable) -> bool:
    return bool(table.rows) and tuple(cell.text for cell in table.rows[0].cells) == _SCHEDULE_HEADER


def _expand_table(table: _RawTable) -> tuple[tuple[str, ...], ...]:
    rows: list[dict[int, str]] = []
    carried: dict[tuple[int, int], str] = {}
    for row_index, raw_row in enumerate(table.rows):
        values = {
            column: text
            for (carried_row, column), text in carried.items()
            if carried_row == row_index
        }
        column = 0
        for cell in raw_row.cells:
            while column in values:
                column += 1
            for offset in range(cell.colspan):
                target = column + offset
                if target in values:
                    raise DataFetchError(
                        "NBS table cells overlap",
                        code="NBS_SCHEDULE_TABLE_INVALID",
                    )
                values[target] = cell.text
                for future_row in range(row_index + 1, row_index + cell.rowspan):
                    key = (future_row, target)
                    if key in carried:
                        raise DataFetchError(
                            "NBS table rowspans overlap",
                            code="NBS_SCHEDULE_TABLE_INVALID",
                        )
                    carried[key] = cell.text
            column += cell.colspan
        rows.append(values)
    if not rows or any(row_index >= len(rows) for row_index, _ in carried):
        raise DataFetchError(
            "NBS table is empty or has unterminated rowspans",
            code="NBS_SCHEDULE_TABLE_INVALID",
        )
    width = len(rows[0])
    expected_columns = set(range(width))
    if any(set(row) != expected_columns for row in rows):
        raise DataFetchError(
            "NBS table rows do not form a complete rectangle",
            code="NBS_SCHEDULE_TABLE_INVALID",
        )
    return tuple(tuple(row[column] for column in range(width)) for row in rows)


def _schedule_datetime(
    year: int, month: int, date_text: str, time_text: str, zone: ZoneInfo
) -> datetime | None:
    if date_text == "……" or time_text == "……":
        if date_text == time_text:
            return None
        raise DataFetchError(
            "NBS schedule date and time must either both exist or both be absent",
            code="NBS_SCHEDULE_TIME_INVALID",
        )
    day_match = _SCHEDULE_DAY_RE.fullmatch(date_text)
    if day_match is None:
        raise DataFetchError(
            "NBS schedule day or weekday is unsupported",
            code="NBS_SCHEDULE_DATE_INVALID",
        )
    try:
        scheduled_date = date(year, month, int(day_match.group("day")))
    except ValueError as exc:
        raise DataFetchError(
            "NBS schedule date does not exist",
            code="NBS_SCHEDULE_DATE_INVALID",
        ) from exc
    if day_match.group("weekday") != _WEEKDAYS[scheduled_date.weekday()]:
        raise DataFetchError(
            "NBS schedule weekday differs from its calendar date",
            code="NBS_SCHEDULE_WEEKDAY_MISMATCH",
        )
    time_match = _SCHEDULE_TIME_RE.fullmatch(time_text)
    if time_match is None:
        raise DataFetchError(
            "NBS schedule time must have exact minute precision",
            code="NBS_SCHEDULE_TIME_INVALID",
        )
    return datetime(
        year,
        month,
        scheduled_date.day,
        int(time_match.group("hour")),
        int(time_match.group("minute")),
        tzinfo=zone,
    ).astimezone(UTC)


__all__ = [
    "NbsActualRelease",
    "NbsScheduleDocument",
    "NbsScheduleEntry",
    "parse_nbs_actual_release",
    "parse_nbs_schedule",
]
