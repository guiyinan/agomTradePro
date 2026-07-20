"""Core workflow for personal readiness window validation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from django.conf import settings

from apps.operational_readiness.application.status_services import (
    count_scheduler_clean_suffix_days,
)
from apps.operational_readiness.infrastructure.readiness_window_validation_calendar import (
    _is_trading_day,
    _next_trading_day,
    _previous_trading_day,
    _resolve_trading_calendar,
    _TradingCalendar,
)
from apps.operational_readiness.infrastructure.readiness_window_validation_evidence import (
    _build_accepted_evidence_manifest,
    _build_accepted_evidence_quality,
    _build_evidence_quality,
    _EvidenceRecord,
    _load_evidence_record,
    _summarize_record,
)


def validate_personal_readiness_window(
    *,
    output_dir: Path,
    required_days: int,
    calendar_source: str,
    expected_latest_date: date | None,
    trading_calendar: set[date] | list[date] | tuple[date, ...] | None,
    load_qlib_trading_calendar: Callable[[], list[date]] | None = None,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Validate readiness evidence files against the continuous-run acceptance gate."""

    project_root = Path(base_dir) if base_dir is not None else Path(settings.BASE_DIR)
    root = project_root / output_dir if not output_dir.is_absolute() else output_dir
    records = [_load_evidence_record(path) for path in sorted(root.glob("*.json"))]
    records = [record for record in records if record is not None]
    calendar = _resolve_trading_calendar(
        source=calendar_source,
        trading_calendar=trading_calendar,
        latest_required_date=max(
            (
                value
                for value in [
                    max((record.target_date for record in records), default=None),
                    expected_latest_date,
                ]
                if value is not None
            ),
            default=None,
        ),
        load_qlib_trading_calendar=load_qlib_trading_calendar,
    )
    trading_records = [
        record for record in records if _is_trading_day(record.target_date, calendar)
    ]
    latest = expected_latest_date or max(
        (record.target_date for record in trading_records), default=None
    )
    accepted, blocking = _continuous_window(
        records=trading_records,
        required_days=required_days,
        latest=latest,
        calendar=calendar,
    )
    remaining_days = max(required_days - len(accepted), 0)
    status = "accepted" if remaining_days == 0 else "in_progress"
    next_required_date, next_required_reason = _resolve_next_required_date(
        accepted=accepted,
        blocking=blocking,
        remaining_days=remaining_days,
        calendar=calendar,
    )
    projected_completion_date = _resolve_projected_completion_date(
        accepted=accepted,
        next_required_date=next_required_date,
        remaining_days=remaining_days,
        calendar=calendar,
    )
    accepted_evidence = [_summarize_record(record) for record in accepted]
    scheduler_clean_suffix_days = count_scheduler_clean_suffix_days(records=accepted_evidence)
    projected_scheduler_completion_date = _resolve_projected_scheduler_completion_date(
        accepted=accepted,
        next_required_date=next_required_date,
        required_days=required_days,
        scheduler_clean_suffix_days=scheduler_clean_suffix_days,
        calendar=calendar,
    )
    accepted_evidence_quality = _build_accepted_evidence_quality(accepted)

    return {
        "status": status,
        "required_days": required_days,
        "accepted_days": len(accepted),
        "remaining_days": remaining_days,
        "next_required_date": (next_required_date.isoformat() if next_required_date else None),
        "next_required_reason": next_required_reason,
        "evidence_file_count": len(records),
        "trading_record_count": len(trading_records),
        "latest_target_date": latest.isoformat() if latest else None,
        "expected_latest_date": (
            expected_latest_date.isoformat() if expected_latest_date else None
        ),
        "projected_completion_date": (
            projected_completion_date.isoformat() if projected_completion_date else None
        ),
        "scheduler_clean_suffix_days": scheduler_clean_suffix_days,
        "scheduler_clean_remaining_days": max(required_days - scheduler_clean_suffix_days, 0),
        "projected_scheduler_completion_date": (
            projected_scheduler_completion_date.isoformat()
            if projected_scheduler_completion_date
            else None
        ),
        "projected_remaining_calendar_days": (
            (projected_completion_date - latest).days
            if projected_completion_date is not None and latest is not None
            else None
        ),
        "projected_scheduler_remaining_calendar_days": (
            (projected_scheduler_completion_date - latest).days
            if projected_scheduler_completion_date is not None and latest is not None
            else None
        ),
        "calendar_source": calendar.source,
        "calendar_day_count": len(calendar.dates) if calendar.dates is not None else None,
        "accepted_dates": [record.target_date.isoformat() for record in accepted],
        "accepted_evidence": accepted_evidence,
        "accepted_evidence_quality": accepted_evidence_quality,
        "accepted_evidence_manifest": _build_accepted_evidence_manifest(accepted_evidence),
        "blocking_issues": blocking,
        "evidence_quality": _build_evidence_quality(
            records=records,
            trading_records=trading_records,
        ),
    }


def _continuous_window(
    *,
    records: list[_EvidenceRecord],
    required_days: int,
    latest: date | None,
    calendar: _TradingCalendar,
) -> tuple[list[_EvidenceRecord], list[dict[str, str]]]:
    if latest is None:
        return [], []

    records_by_date = {record.target_date: record for record in records}
    if not records_by_date:
        return [], [
            {
                "target_date": latest.isoformat(),
                "path": "",
                "reason": "evidence is missing",
            }
        ]
    earliest = min(records_by_date)
    accepted: list[_EvidenceRecord] = []
    blocking: list[dict[str, str]] = []
    current = latest

    while current >= earliest and len(accepted) < required_days:
        record = records_by_date.get(current)
        if record is None:
            blocking.append(
                {
                    "target_date": current.isoformat(),
                    "path": "",
                    "reason": "evidence is missing",
                }
            )
            break
        if not record.accepted:
            blocking.append(
                {
                    "target_date": record.target_date.isoformat(),
                    "path": str(record.path),
                    "reason": record.reason,
                }
            )
            break

        accepted.append(record)
        current = _previous_trading_day(current, calendar)

    accepted.reverse()
    return accepted, blocking


def _resolve_next_required_date(
    *,
    accepted: list[_EvidenceRecord],
    blocking: list[dict[str, str]],
    remaining_days: int,
    calendar: _TradingCalendar,
) -> tuple[date | None, str]:
    if remaining_days <= 0:
        return None, "window_accepted"
    if blocking:
        return date.fromisoformat(blocking[0]["target_date"]), "blocking_issue"
    if accepted:
        return _next_trading_day(accepted[-1].target_date, calendar), "next_trading_day"
    return None, "no_accepted_evidence"


def _resolve_projected_completion_date(
    *,
    accepted: list[_EvidenceRecord],
    next_required_date: date | None,
    remaining_days: int,
    calendar: _TradingCalendar,
) -> date | None:
    if remaining_days <= 0:
        if accepted:
            return accepted[-1].target_date
        return None
    if next_required_date is None:
        return None

    projected = next_required_date
    for _ in range(max(remaining_days - 1, 0)):
        projected = _next_trading_day(projected, calendar)
    return projected


def _resolve_projected_scheduler_completion_date(
    *,
    accepted: list[_EvidenceRecord],
    next_required_date: date | None,
    required_days: int,
    scheduler_clean_suffix_days: int,
    calendar: _TradingCalendar,
) -> date | None:
    if scheduler_clean_suffix_days >= required_days:
        return accepted[-1].target_date if accepted else None
    start_date = (
        _next_trading_day(accepted[-1].target_date, calendar) if accepted else next_required_date
    )
    return _resolve_projected_completion_date(
        accepted=[],
        next_required_date=start_date,
        remaining_days=max(required_days - scheduler_clean_suffix_days, 0),
        calendar=calendar,
    )
