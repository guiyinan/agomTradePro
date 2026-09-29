"""Typed provider-boundary contracts and normalization for A-share universe data."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any, NotRequired, Protocol, TypedDict, cast

from core.exceptions import DataFetchError


class AShareCodeNameRow(TypedDict):
    """One provider row with optional normalized listing-date evidence."""

    code: str
    name: str
    list_date: NotRequired[str | None]
    list_date_status: NotRequired[str]
    list_date_source: NotRequired[str]


class AShareUniverseSyncError(DataFetchError):
    """Stable, redacted error for an A-share universe refresh failure."""

    default_message = "A-share universe refresh could not establish a current scope"
    default_code = "A_SHARE_UNIVERSE_SYNC_FAILED"

    def __init__(
        self,
        code: str,
        *,
        category: str,
        source: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        error_details: dict[str, Any] = {"category": category, "source": source}
        error_details.update(details or {})
        super().__init__(self.default_message, code=code, details=error_details)


class _Frame(Protocol):
    """Narrow the DataFrame surface used at provider boundaries."""

    empty: bool
    columns: object

    def to_dict(self, orient: str) -> object: ...


class AShareCodeNameProvider(Protocol):
    """Provider contract for current A-share code-name rows."""

    def load_code_names(self) -> list[AShareCodeNameRow]:
        """Return rows with canonicalizable identity and optional listing metadata."""


class _EmptyProviderSegment(ValueError):
    """Retryable indication that one required provider category had no rows."""


def _provider_text(value: object) -> str:
    """Convert a provider scalar to text while rejecting null-like values."""

    if value is None or isinstance(value, bool):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "nat", "none", "null", "<na>"} else text


def _normalize_provider_listing_date(
    value: object,
    *,
    source: str,
    segment: str,
    row_index: int,
) -> tuple[str | None, str]:
    """Normalize listing dates, treating placeholders and malformed data as unverified."""

    del source, segment, row_index
    if value is None or isinstance(value, bool):
        return None, "unknown"
    if isinstance(value, datetime):
        parsed_date = value.date()
    elif isinstance(value, date):
        parsed_date = value
    else:
        raw_value = _provider_text(value)
        if not raw_value:
            return None, "unknown"
        try:
            if len(raw_value) == 8 and raw_value.isascii() and raw_value.isdigit():
                parsed_date = datetime.strptime(raw_value, "%Y%m%d").date()
            else:
                parsed_date = date.fromisoformat(raw_value[:10])
        except ValueError:
            return None, "invalid"
    if parsed_date == date(1970, 1, 1):
        return None, "placeholder"
    return parsed_date.isoformat(), "verified"


def _parse_provider_frame(
    frame: _Frame,
    *,
    source: str,
    segment: str,
    code_column: str,
    name_column: str,
    expected_exchange: str | None = None,
    include_list_date: bool = False,
) -> list[AShareCodeNameRow]:
    """Validate native provider columns and return normalized row fields."""

    columns = {str(column) for column in cast(Iterable[object], frame.columns)}
    required = {code_column, name_column}
    if expected_exchange is not None:
        required.update({"exchange", "list_status"})
    if include_list_date:
        required.add("list_date")
    if not required.issubset(columns):
        raise AShareUniverseSyncError(
            "A_SHARE_UNIVERSE_PROVIDER_SCHEMA_INVALID",
            category="provider_schema",
            source=source,
            details={"segment": segment, "missing_columns": sorted(required - columns)},
        )

    records = cast(list[object], frame.to_dict("records"))
    parsed_records: list[AShareCodeNameRow] = []
    for index, raw_record in enumerate(records):
        if not isinstance(raw_record, Mapping):
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_PROVIDER_SCHEMA_INVALID",
                category="provider_schema",
                source=source,
                details={"segment": segment, "row_index": index},
            )
        record = cast(Mapping[str, object], raw_record)
        raw_code = _provider_text(record.get(code_column))
        raw_name = _provider_text(record.get(name_column))
        if not raw_code or not raw_name:
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_PROVIDER_SCHEMA_INVALID",
                category="provider_schema",
                source=source,
                details={"segment": segment, "row_index": index, "invalid_fields": True},
            )
        if expected_exchange is not None:
            exchange = _provider_text(record.get("exchange"))
            listing_status = _provider_text(record.get("list_status"))
            if exchange != expected_exchange or listing_status != "L":
                raise AShareUniverseSyncError(
                    "A_SHARE_UNIVERSE_PROVIDER_SCOPE_INVALID",
                    category="provider_scope",
                    source=source,
                    details={"segment": segment, "row_index": index},
                )
        parsed_row: AShareCodeNameRow = {"code": raw_code, "name": raw_name}
        if include_list_date:
            list_date_value, list_date_status = _normalize_provider_listing_date(
                record.get("list_date"),
                source=source,
                segment=segment,
                row_index=index,
            )
            parsed_row["list_date"] = list_date_value
            parsed_row["list_date_status"] = list_date_status
            parsed_row["list_date_source"] = f"{source}.list_date"
        parsed_records.append(parsed_row)
    return parsed_records
