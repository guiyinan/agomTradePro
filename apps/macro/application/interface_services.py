"""Interface-facing helpers for macro views and APIs."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.macro.application.data_management import (
    GetDataManagementSummaryUseCase,
    ScheduleDataFetchUseCase,
)
from apps.macro.application.indicator_service import IndicatorService, UnitDisplayService
from apps.macro.application.repository_provider import (
    get_macro_read_repository,
    get_macro_repository,
)
from apps.macro.application.use_cases import build_sync_macro_data_use_case

TABLE_SORT_FIELDS = {
    "code": "code",
    "-code": "-code",
    "value": "value",
    "-value": "-value",
    "source": "source",
    "-source": "-source",
    "period_type": "period_type",
    "-period_type": "-period_type",
    "reporting_period": "reporting_period",
    "-reporting_period": "-reporting_period",
    "revision_number": "revision_number",
    "-revision_number": "-revision_number",
    "published_at": "published_at",
    "-published_at": "-published_at",
}

_UNSET = object()


def get_supported_macro_indicators(*, source: str = "akshare") -> list[dict[str, Any]]:
    """Return the supported macro indicator definitions for the requested source."""

    sync_use_case = build_sync_macro_data_use_case(source=source)
    for adapter in sync_use_case.adapters.values():
        supported_indicators = getattr(adapter, "SUPPORTED_INDICATORS", None)
        if isinstance(supported_indicators, dict):
            indicators = [
                {"code": code, "name": name}
                for code, name in supported_indicators.items()
            ]
            indicators.sort(key=lambda item: item["code"])
            return indicators
    return []


def _format_indicator_row_for_display(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a repository row into the legacy table API payload."""

    storage_value = float(row["value"])
    storage_unit = str(row.get("unit") or "")
    original_unit = str(row.get("original_unit") or storage_unit)
    display_value, display_unit = UnitDisplayService.convert_for_display(
        storage_value,
        storage_unit,
        original_unit,
    )
    reporting_period = row["reporting_period"]
    observed_at = row.get("observed_at") or reporting_period
    published_at = row.get("published_at")

    return {
        "id": row["id"],
        "code": row["code"],
        "value": display_value,
        "unit": display_unit,
        "storage_value": storage_value,
        "storage_unit": storage_unit,
        "reporting_period": reporting_period.isoformat(),
        "period_type": row["period_type"],
        "period_type_display": row["period_type_display"],
        "observed_at": observed_at.isoformat(),
        "published_at": published_at.isoformat() if published_at else None,
        "source": row["source"],
        "revision_number": row["revision_number"],
        "publication_lag_days": row["publication_lag_days"],
    }


def get_macro_data_page_snapshot(*, selected_indicator: str = "") -> dict[str, Any]:
    """Return view-model data for the macro data management page."""

    read_repository = get_macro_read_repository()
    indicators = sorted(
        IndicatorService.get_available_indicators(include_stats=False),
        key=lambda item: item["code"],
    )

    indicator_map = {
        item["code"]: {
            "code": item["code"],
            "name": item["name"],
            "latest_value": item["latest_value"],
            "latest_period": item["latest_date"][:7],
            "unit": item["unit"] or "-",
        }
        for item in indicators
    }

    resolved_selected_indicator = selected_indicator
    if resolved_selected_indicator not in indicator_map:
        resolved_selected_indicator = next(iter(indicator_map), "")

    history_rows: list[dict[str, Any]] = []
    if resolved_selected_indicator:
        history_rows = read_repository.get_indicator_rows(
            code=resolved_selected_indicator,
            ascending=True,
        )

    summary = read_repository.get_storage_summary()
    return {
        "indicator_map": indicator_map,
        "selected_indicator": resolved_selected_indicator,
        "history": [_format_indicator_row_for_display(row) for row in history_rows],
        "stats": {
            "total_indicators": summary["total_indicators"],
            "total_records": summary["total_records"],
            "latest_date": summary["latest_date"],
        },
        "min_date": summary["min_date"],
        "max_date": summary["max_date"],
    }


def get_macro_data_controller_context() -> dict[str, Any]:
    """Return view-model data for the unified macro data controller page."""

    repository = get_macro_repository()
    read_repository = get_macro_read_repository()
    summary_use_case = GetDataManagementSummaryUseCase(repository)
    schedule_use_case = ScheduleDataFetchUseCase(repository)

    return {
        "summary": summary_use_case.execute(),
        "scheduled_indicators": schedule_use_case.get_scheduled_indicators(),
        "all_indicators": read_repository.list_indicator_rollups(),
        "sources": read_repository.list_source_rollups(),
    }


def get_macro_indicator_data(
    *,
    code: str,
    limit: int = 500,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    """Return one indicator's serialized time-series rows for the API."""

    read_repository = get_macro_read_repository()
    rows = read_repository.get_indicator_rows(
        code=code,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        ascending=True,
    )
    return [_format_indicator_row_for_display(row) for row in rows]


def get_macro_table_page(
    *,
    page: int = 1,
    page_size: int = 50,
    code_filter: str = "",
    source_filter: str = "",
    period_type_filter: str = "",
    start_date: date | None = None,
    end_date: date | None = None,
    sort_field: str = "-reporting_period",
) -> dict[str, Any]:
    """Return paginated table data for the macro record API."""

    normalized_page = max(page, 1)
    normalized_page_size = min(max(page_size, 1), 500)
    normalized_sort_field = TABLE_SORT_FIELDS.get(sort_field, "-reporting_period")
    offset = (normalized_page - 1) * normalized_page_size

    read_repository = get_macro_read_repository()
    total = read_repository.count_table_rows(
        code_filter=code_filter,
        source_filter=source_filter,
        period_type_filter=period_type_filter,
        start_date=start_date,
        end_date=end_date,
    )
    rows = read_repository.get_table_rows(
        code_filter=code_filter,
        source_filter=source_filter,
        period_type_filter=period_type_filter,
        start_date=start_date,
        end_date=end_date,
        sort_field=normalized_sort_field,
        offset=offset,
        limit=normalized_page_size,
    )

    return {
        "data": [_format_indicator_row_for_display(row) for row in rows],
        "total": total,
        "page": normalized_page,
        "page_size": normalized_page_size,
        "total_pages": (total + normalized_page_size - 1) // normalized_page_size,
    }


def create_macro_record(
    *,
    code: str,
    value: float,
    reporting_period: date,
    period_type: str = "D",
    published_at: date | None = None,
    source: str = "manual",
    revision_number: int = 1,
) -> dict[str, Any]:
    """Create one macro record and return the serialized API payload."""

    repository = get_macro_repository()
    row = repository.create_record(
        code=code,
        value=value,
        reporting_period=reporting_period,
        period_type=period_type,
        published_at=published_at,
        source=source,
        revision_number=revision_number,
    )
    return _format_indicator_row_for_display(row)


def update_macro_record(
    record_id: int,
    *,
    code: str | None | object = _UNSET,
    value: float | None | object = _UNSET,
    reporting_period: date | None | object = _UNSET,
    period_type: str | None | object = _UNSET,
    published_at: date | None | object = _UNSET,
    source: str | None | object = _UNSET,
    revision_number: int | None | object = _UNSET,
) -> dict[str, Any] | None:
    """Update one macro record and return the serialized API payload."""

    updates: dict[str, Any] = {}
    if code is not _UNSET:
        updates["code"] = code
    if value is not _UNSET:
        updates["value"] = value
    if reporting_period is not _UNSET:
        updates["reporting_period"] = reporting_period
    if period_type is not _UNSET:
        updates["period_type"] = period_type
    if published_at is not _UNSET:
        updates["published_at"] = published_at
    if source is not _UNSET:
        updates["source"] = source
    if revision_number is not _UNSET:
        updates["revision_number"] = revision_number

    repository = get_macro_repository()
    row = repository.update_record(record_id, **updates)
    if row is None:
        return None
    return _format_indicator_row_for_display(row)


def delete_macro_record(record_id: int) -> bool:
    """Delete one macro record by primary key."""

    return get_macro_repository().delete_record_by_id(record_id)


def batch_delete_macro_records(record_ids: list[int]) -> int:
    """Delete multiple macro records by primary key list."""

    return get_macro_repository().delete_records_by_ids(record_ids)
