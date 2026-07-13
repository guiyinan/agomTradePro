"""Governed Audit capability handlers."""

from __future__ import annotations

import math
from typing import Any


def generate_attribution_report(
    backtest_id: int,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Preview or generate one canonical Audit attribution report."""

    from agomtradepro import AgomTradeProClient

    try:
        normalized_backtest_id = int(backtest_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("backtest_id must be a positive integer") from exc
    if normalized_backtest_id < 1:
        raise ValueError("backtest_id must be a positive integer")

    payload = {"backtest_id": normalized_backtest_id}
    client = AgomTradeProClient()
    if preview_only:
        response = client.audit.preview_report_generation(payload)
        preview = response.get("preview", response)
        return {
            "success": True,
            "preview_only": True,
            "preview": preview,
            "summary": {
                "backtest": preview.get("backtest", {}),
                "existing_report_count": preview.get("existing_report_count", 0),
                "external_reads": preview.get("external_reads", []),
                "writes": preview.get("writes", []),
                "duplicate_reports_allowed": preview.get("duplicate_reports_allowed", True),
                "partial_write_possible": preview.get("partial_write_possible", True),
            },
            "message": (
                "Preview generated without fetching prices, running attribution, or writing "
                "Audit records. Confirm to generate the report synchronously."
            ),
        }
    return client.audit.generate_report(payload)


def start_threshold_validation(
    start_date: str,
    end_date: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Preview or execute the canonical threshold-validation workflow."""

    from datetime import date

    from agomtradepro import AgomTradeProClient

    try:
        parsed_start = date.fromisoformat(str(start_date or "").strip())
        parsed_end = date.fromisoformat(str(end_date or "").strip())
    except ValueError as exc:
        raise ValueError("start_date and end_date must use YYYY-MM-DD format") from exc
    if parsed_start > parsed_end:
        raise ValueError("start_date must not be after end_date")
    if (parsed_end - parsed_start).days > 3660:
        raise ValueError("validation range must not exceed 3660 days")

    payload = {
        "start_date": parsed_start.isoformat(),
        "end_date": parsed_end.isoformat(),
    }
    client = AgomTradeProClient()
    if preview_only:
        response = client.audit.preview_validation(payload)
        preview = response.get("preview", response)
        return {
            "success": True,
            "preview_only": True,
            "preview": preview,
            "summary": {
                "start_date": payload["start_date"],
                "end_date": payload["end_date"],
                "active_indicator_count": preview.get("active_indicator_count", 0),
                "writes": preview.get("writes", []),
                "synchronous_execution": True,
                "partial_indicator_failure_possible": True,
            },
            "message": (
                "Preview generated without running validation or writing audit records. "
                "Confirm to execute the synchronous threshold validation workflow."
            ),
        }
    return client.audit.run_validation(payload)


def update_threshold_levels(
    indicator_code: str,
    level_low: float,
    level_high: float,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Preview or apply one canonical Audit threshold-level update."""

    from agomtradepro import AgomTradeProClient

    normalized_code = str(indicator_code or "").strip()
    if not normalized_code:
        raise ValueError("indicator_code is required")
    try:
        normalized_low = float(level_low)
        normalized_high = float(level_high)
    except (TypeError, ValueError) as exc:
        raise ValueError("level_low and level_high must be numbers") from exc
    if not math.isfinite(normalized_low) or not math.isfinite(normalized_high):
        raise ValueError("threshold levels must be finite numbers")
    if normalized_low >= normalized_high:
        raise ValueError("level_low must be less than level_high")

    payload = {
        "indicator_code": normalized_code,
        "level_low": normalized_low,
        "level_high": normalized_high,
    }
    client = AgomTradeProClient()
    if preview_only:
        response = client.audit.preview_threshold_update(payload)
        preview = response.get("preview", response)
        return {
            "success": True,
            "preview_only": True,
            "preview": preview,
            "summary": {
                "indicator_code": normalized_code,
                "current": preview.get("current", {}),
                "target": preview.get("target", {}),
                "changed_fields": preview.get("changed_fields", []),
                "writes": preview.get("writes", []),
            },
            "message": (
                "Preview generated without updating threshold configuration. "
                "Confirm to apply the canonical threshold-level update."
            ),
        }
    return client.audit.update_threshold(payload)
