"""Validate the continuous personal readiness evidence window."""

from __future__ import annotations

import json
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.task_monitor.application.readiness_status_services import (
    classify_formal_risk_evidence,
    count_scheduler_clean_suffix_days,
)

DEFAULT_OUTPUT_DIR = "var/readiness-evidence"
DEFAULT_REQUIRED_DAYS = 20
DEFAULT_CALENDAR_SOURCE = "auto"


class Command(BaseCommand):
    help = "Validate continuous personal readiness evidence over trading days."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--output-dir",
            default=DEFAULT_OUTPUT_DIR,
            help=f"Evidence directory. Default: {DEFAULT_OUTPUT_DIR}",
        )
        parser.add_argument(
            "--required-days",
            type=int,
            default=DEFAULT_REQUIRED_DAYS,
            help=f"Required accepted trading-day records. Default: {DEFAULT_REQUIRED_DAYS}",
        )
        parser.add_argument(
            "--calendar-source",
            choices=("auto", "qlib", "weekday"),
            default=DEFAULT_CALENDAR_SOURCE,
            help="Trading calendar source. Default: auto.",
        )
        parser.add_argument(
            "--expected-latest-date",
            default=None,
            help="Expected latest readiness date in YYYY-MM-DD format.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit with CommandError when the window is not yet accepted.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="print_json",
            help="Print full JSON result.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        payload = validate_personal_readiness_window(
            output_dir=Path(str(options["output_dir"])),
            required_days=int(options["required_days"]),
            calendar_source=str(options["calendar_source"]),
            expected_latest_date=_parse_date(options.get("expected_latest_date")),
        )
        if options.get("print_json"):
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Personal readiness window: "
                    f"status={payload['status']}, "
                    f"accepted_days={payload['accepted_days']}/{payload['required_days']}, "
                    f"remaining_days={payload['remaining_days']}"
                )
            )
            for issue in payload["blocking_issues"][:10]:
                self.stdout.write(
                    self.style.WARNING(f"  {issue['target_date']}: {issue['reason']}")
                )

        if options.get("strict") and payload["status"] != "accepted":
            raise CommandError(
                "Personal readiness window is not accepted: "
                f"{payload['accepted_days']}/{payload['required_days']} days"
            )


def validate_personal_readiness_window(
    *,
    output_dir: Path,
    required_days: int = DEFAULT_REQUIRED_DAYS,
    calendar_source: str = DEFAULT_CALENDAR_SOURCE,
    expected_latest_date: date | None = None,
    trading_calendar: set[date] | list[date] | tuple[date, ...] | None = None,
) -> dict[str, Any]:
    """Validate readiness evidence files against the continuous-run acceptance gate."""

    root = Path(settings.BASE_DIR) / output_dir if not output_dir.is_absolute() else output_dir
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


class _EvidenceRecord:
    def __init__(
        self,
        *,
        path: Path,
        target_date: date,
        accepted: bool,
        reason: str,
        evidence_mode: str,
        acceptance_candidate: bool,
        trigger_source: str | None,
        trigger_task_id: str | None,
        trigger_task_name: str | None,
        formal_workspace_core_record: bool,
        formal_workspace_core_ok: bool,
        formal_workspace_core_missing: bool,
        formal_qlib_record: bool,
        formal_qlib_ok: bool,
        formal_qlib_missing: bool,
        formal_qlib_blocked: bool,
        formal_alpha_workspace_record: bool,
        formal_alpha_workspace_ok: bool,
        formal_alpha_workspace_missing: bool,
        formal_decision_data_record: bool,
        formal_decision_data_ok: bool,
        formal_decision_data_missing: bool,
        formal_decision_data_blocked: bool,
        formal_quote_freshness_record: bool,
        formal_quote_freshness_ok: bool,
        formal_quote_freshness_missing: bool,
        formal_quote_freshness_stale: bool,
        formal_quote_freshness_blocked: bool,
        formal_quote_pre_readiness_scheduler_record: bool,
        formal_quote_pre_readiness_scheduler_ok: bool,
        formal_quote_pre_readiness_scheduler_missing: bool,
        formal_quote_pre_readiness_scheduler_blocked: bool,
        formal_risk_account_count: int,
        formal_risk_report_ok_account_count: int,
        formal_risk_persisted_report_account_count: int,
        formal_pre_trade_ok_account_count: int,
        formal_pre_trade_missing_account_count: int,
        formal_post_investment_ok_account_count: int,
        formal_post_investment_missing_account_count: int,
        formal_risk_evidence_status: str,
        weekly_report_account_count: int,
        weekly_report_persistence_ok_account_count: int,
        weekly_report_persistence_missing_account_count: int,
        weekly_report_persistence_warning_account_count: int,
        weekly_report_persistence_status: str,
        size_bytes: int,
        sha256_hash: str,
    ) -> None:
        self.path = path
        self.target_date = target_date
        self.accepted = accepted
        self.reason = reason
        self.evidence_mode = evidence_mode
        self.acceptance_candidate = acceptance_candidate
        self.trigger_source = trigger_source
        self.trigger_task_id = trigger_task_id
        self.trigger_task_name = trigger_task_name
        self.formal_workspace_core_record = formal_workspace_core_record
        self.formal_workspace_core_ok = formal_workspace_core_ok
        self.formal_workspace_core_missing = formal_workspace_core_missing
        self.formal_qlib_record = formal_qlib_record
        self.formal_qlib_ok = formal_qlib_ok
        self.formal_qlib_missing = formal_qlib_missing
        self.formal_qlib_blocked = formal_qlib_blocked
        self.formal_alpha_workspace_record = formal_alpha_workspace_record
        self.formal_alpha_workspace_ok = formal_alpha_workspace_ok
        self.formal_alpha_workspace_missing = formal_alpha_workspace_missing
        self.formal_decision_data_record = formal_decision_data_record
        self.formal_decision_data_ok = formal_decision_data_ok
        self.formal_decision_data_missing = formal_decision_data_missing
        self.formal_decision_data_blocked = formal_decision_data_blocked
        self.formal_quote_freshness_record = formal_quote_freshness_record
        self.formal_quote_freshness_ok = formal_quote_freshness_ok
        self.formal_quote_freshness_missing = formal_quote_freshness_missing
        self.formal_quote_freshness_stale = formal_quote_freshness_stale
        self.formal_quote_freshness_blocked = formal_quote_freshness_blocked
        self.formal_quote_pre_readiness_scheduler_record = (
            formal_quote_pre_readiness_scheduler_record
        )
        self.formal_quote_pre_readiness_scheduler_ok = formal_quote_pre_readiness_scheduler_ok
        self.formal_quote_pre_readiness_scheduler_missing = (
            formal_quote_pre_readiness_scheduler_missing
        )
        self.formal_quote_pre_readiness_scheduler_blocked = (
            formal_quote_pre_readiness_scheduler_blocked
        )
        self.formal_risk_account_count = formal_risk_account_count
        self.formal_risk_report_ok_account_count = formal_risk_report_ok_account_count
        self.formal_risk_persisted_report_account_count = (
            formal_risk_persisted_report_account_count
        )
        self.formal_pre_trade_ok_account_count = formal_pre_trade_ok_account_count
        self.formal_pre_trade_missing_account_count = formal_pre_trade_missing_account_count
        self.formal_post_investment_ok_account_count = formal_post_investment_ok_account_count
        self.formal_post_investment_missing_account_count = (
            formal_post_investment_missing_account_count
        )
        self.formal_risk_evidence_status = formal_risk_evidence_status
        self.weekly_report_account_count = weekly_report_account_count
        self.weekly_report_persistence_ok_account_count = weekly_report_persistence_ok_account_count
        self.weekly_report_persistence_missing_account_count = (
            weekly_report_persistence_missing_account_count
        )
        self.weekly_report_persistence_warning_account_count = (
            weekly_report_persistence_warning_account_count
        )
        self.weekly_report_persistence_status = weekly_report_persistence_status
        self.size_bytes = size_bytes
        self.sha256_hash = sha256_hash


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
    start_date = _next_trading_day(accepted[-1].target_date, calendar) if accepted else next_required_date
    return _resolve_projected_completion_date(
        accepted=[],
        next_required_date=start_date,
        remaining_days=max(required_days - scheduler_clean_suffix_days, 0),
        calendar=calendar,
    )


@dataclass(frozen=True)
class _TradingCalendar:
    source: str
    dates: tuple[date, ...] | None = None

    @property
    def date_set(self) -> set[date]:
        return set(self.dates or ())


def _resolve_trading_calendar(
    *,
    source: str,
    trading_calendar: set[date] | list[date] | tuple[date, ...] | None,
    latest_required_date: date | None,
) -> _TradingCalendar:
    if trading_calendar is not None:
        return _TradingCalendar(
            source="injected",
            dates=tuple(sorted(set(trading_calendar))),
        )

    if source == "weekday":
        return _TradingCalendar(source="weekday", dates=None)

    if source not in {"auto", "qlib"}:
        raise CommandError("calendar-source must be auto, qlib, or weekday")

    qlib_calendar = _load_qlib_trading_calendar()
    if qlib_calendar and (
        latest_required_date is None or latest_required_date <= qlib_calendar[-1]
    ):
        return _TradingCalendar(source="qlib", dates=tuple(qlib_calendar))

    if source == "qlib":
        raise CommandError("Qlib trading calendar is unavailable or stale for readiness evidence")

    return _TradingCalendar(source="weekday_fallback", dates=None)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError("expected-latest-date must be YYYY-MM-DD") from exc


def _load_qlib_trading_calendar() -> list[date]:
    try:
        from core.integration.runtime_settings import get_runtime_qlib_config

        runtime_config = get_runtime_qlib_config()
        provider_uri = runtime_config.get("provider_uri")
    except Exception:
        provider_uri = None

    if not provider_uri:
        provider_uri = getattr(settings, "QLIB_SETTINGS", {}).get("provider_uri")
    if not provider_uri:
        return []

    calendar_path = Path(str(provider_uri)).expanduser() / "calendars" / "day.txt"
    if not calendar_path.exists():
        return []

    values: list[date] = []
    try:
        with calendar_path.open("r", encoding="utf-8") as fp:
            for line in fp:
                normalized = line.strip()
                if not normalized:
                    continue
                values.append(date.fromisoformat(normalized[:10]))
    except (OSError, ValueError):
        return []
    return sorted(set(values))


def _load_evidence_record(path: Path) -> _EvidenceRecord | None:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        target_date = date.fromisoformat(str(payload["target_date"]))
    except (OSError, UnicodeDecodeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

    accepted, reason = _evaluate_payload(payload)
    classification = _classify_payload(payload)
    advisor_quality = _classify_auto_advisor_weekly_persistence(payload)
    workspace_quality = _classify_formal_workspace_core_evidence(payload)
    qlib_quality = _classify_formal_qlib_evidence(payload)
    alpha_quality = _classify_formal_alpha_workspace_evidence(payload)
    decision_quality = _classify_formal_decision_data_evidence(payload)
    quote_quality = _classify_formal_quote_freshness_evidence(payload)
    quote_pre_readiness_quality = _classify_formal_quote_pre_readiness_scheduler_evidence(
        payload
    )
    risk_quality = classify_formal_risk_evidence(
        payload=payload,
        classification=classification,
    )
    return _EvidenceRecord(
        path=path,
        target_date=target_date,
        accepted=accepted,
        reason=reason,
        evidence_mode=classification["evidence_mode"],
        acceptance_candidate=classification["acceptance_candidate"],
        trigger_source=classification["trigger_source"],
        trigger_task_id=classification["trigger_task_id"],
        trigger_task_name=classification["trigger_task_name"],
        formal_workspace_core_record=workspace_quality["formal_workspace_core_record"],
        formal_workspace_core_ok=workspace_quality["formal_workspace_core_ok"],
        formal_workspace_core_missing=workspace_quality["formal_workspace_core_missing"],
        formal_qlib_record=qlib_quality["formal_qlib_record"],
        formal_qlib_ok=qlib_quality["formal_qlib_ok"],
        formal_qlib_missing=qlib_quality["formal_qlib_missing"],
        formal_qlib_blocked=qlib_quality["formal_qlib_blocked"],
        formal_alpha_workspace_record=alpha_quality["formal_alpha_workspace_record"],
        formal_alpha_workspace_ok=alpha_quality["formal_alpha_workspace_ok"],
        formal_alpha_workspace_missing=alpha_quality["formal_alpha_workspace_missing"],
        formal_decision_data_record=decision_quality["formal_decision_data_record"],
        formal_decision_data_ok=decision_quality["formal_decision_data_ok"],
        formal_decision_data_missing=decision_quality["formal_decision_data_missing"],
        formal_decision_data_blocked=decision_quality["formal_decision_data_blocked"],
        formal_quote_freshness_record=quote_quality["formal_quote_freshness_record"],
        formal_quote_freshness_ok=quote_quality["formal_quote_freshness_ok"],
        formal_quote_freshness_missing=quote_quality["formal_quote_freshness_missing"],
        formal_quote_freshness_stale=quote_quality["formal_quote_freshness_stale"],
        formal_quote_freshness_blocked=quote_quality["formal_quote_freshness_blocked"],
        formal_quote_pre_readiness_scheduler_record=quote_pre_readiness_quality[
            "formal_quote_pre_readiness_scheduler_record"
        ],
        formal_quote_pre_readiness_scheduler_ok=quote_pre_readiness_quality[
            "formal_quote_pre_readiness_scheduler_ok"
        ],
        formal_quote_pre_readiness_scheduler_missing=quote_pre_readiness_quality[
            "formal_quote_pre_readiness_scheduler_missing"
        ],
        formal_quote_pre_readiness_scheduler_blocked=quote_pre_readiness_quality[
            "formal_quote_pre_readiness_scheduler_blocked"
        ],
        formal_risk_account_count=risk_quality["formal_risk_account_count"],
        formal_risk_report_ok_account_count=risk_quality["formal_risk_report_ok_account_count"],
        formal_risk_persisted_report_account_count=risk_quality[
            "formal_risk_persisted_report_account_count"
        ],
        formal_pre_trade_ok_account_count=risk_quality["formal_pre_trade_ok_account_count"],
        formal_pre_trade_missing_account_count=risk_quality[
            "formal_pre_trade_missing_account_count"
        ],
        formal_post_investment_ok_account_count=risk_quality[
            "formal_post_investment_ok_account_count"
        ],
        formal_post_investment_missing_account_count=risk_quality[
            "formal_post_investment_missing_account_count"
        ],
        formal_risk_evidence_status=risk_quality["formal_risk_evidence_status"],
        weekly_report_account_count=advisor_quality["weekly_report_account_count"],
        weekly_report_persistence_ok_account_count=advisor_quality[
            "weekly_report_persistence_ok_account_count"
        ],
        weekly_report_persistence_missing_account_count=advisor_quality[
            "weekly_report_persistence_missing_account_count"
        ],
        weekly_report_persistence_warning_account_count=advisor_quality[
            "weekly_report_persistence_warning_account_count"
        ],
        weekly_report_persistence_status=advisor_quality["weekly_report_persistence_status"],
        size_bytes=len(raw),
        sha256_hash=sha256(raw).hexdigest(),
    )


def _summarize_record(record: _EvidenceRecord) -> dict[str, Any]:
    return {
        "target_date": record.target_date.isoformat(),
        "path": str(record.path),
        "size_bytes": record.size_bytes,
        "sha256": record.sha256_hash,
        "evidence_mode": record.evidence_mode,
        "acceptance_candidate": record.acceptance_candidate,
        "trigger_source": record.trigger_source,
        "trigger_task_id": record.trigger_task_id,
        "trigger_task_name": record.trigger_task_name,
        "reason": record.reason,
    }


def _build_accepted_evidence_manifest(
    accepted_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "schema_version": "accepted-readiness-evidence-manifest.v1",
        "record_count": len(accepted_evidence),
        "target_dates": [str(record.get("target_date")) for record in accepted_evidence],
        "records": accepted_evidence,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "schema_version": payload["schema_version"],
        "record_count": payload["record_count"],
        "target_dates": payload["target_dates"],
        "sha256": sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _build_accepted_evidence_quality(records: list[_EvidenceRecord]) -> dict[str, Any]:
    return {
        "record_count": len(records),
        "start_date": records[0].target_date.isoformat() if records else None,
        "end_date": records[-1].target_date.isoformat() if records else None,
        "acceptance_candidate_record_count": sum(
            1 for record in records if record.acceptance_candidate
        ),
        "formal_record_count": sum(1 for record in records if record.evidence_mode == "formal"),
        "legacy_record_count": sum(
            1 for record in records if record.evidence_mode == "legacy_without_operation_context"
        ),
        "diagnostic_record_count": sum(1 for record in records if not record.acceptance_candidate),
        "scheduler_trigger_record_count": sum(
            1 for record in records if record.trigger_source == "scheduler"
        ),
        "manual_trigger_record_count": sum(
            1 for record in records if record.trigger_source == "manual"
        ),
        "unknown_trigger_record_count": sum(
            1 for record in records if record.trigger_source is None
        ),
        "task_provenance_record_count": sum(
            1 for record in records if record.trigger_task_id or record.trigger_task_name
        ),
        "missing_task_provenance_record_count": sum(
            1 for record in records if not record.trigger_task_id and not record.trigger_task_name
        ),
        "formal_workspace_core_record_count": sum(
            1 for record in records if record.formal_workspace_core_record
        ),
        "formal_workspace_core_ok_record_count": sum(
            1 for record in records if record.formal_workspace_core_ok
        ),
        "formal_workspace_core_missing_record_count": sum(
            1 for record in records if record.formal_workspace_core_missing
        ),
        "formal_qlib_record_count": sum(1 for record in records if record.formal_qlib_record),
        "formal_qlib_ok_record_count": sum(1 for record in records if record.formal_qlib_ok),
        "formal_qlib_missing_record_count": sum(
            1 for record in records if record.formal_qlib_missing
        ),
        "formal_qlib_blocked_record_count": sum(
            1 for record in records if record.formal_qlib_blocked
        ),
        "formal_alpha_workspace_record_count": sum(
            1 for record in records if record.formal_alpha_workspace_record
        ),
        "formal_alpha_workspace_ok_record_count": sum(
            1 for record in records if record.formal_alpha_workspace_ok
        ),
        "formal_alpha_workspace_missing_record_count": sum(
            1 for record in records if record.formal_alpha_workspace_missing
        ),
        "formal_decision_data_record_count": sum(
            1 for record in records if record.formal_decision_data_record
        ),
        "formal_decision_data_ok_record_count": sum(
            1 for record in records if record.formal_decision_data_ok
        ),
        "formal_decision_data_missing_record_count": sum(
            1 for record in records if record.formal_decision_data_missing
        ),
        "formal_decision_data_blocked_record_count": sum(
            1 for record in records if record.formal_decision_data_blocked
        ),
        "formal_quote_freshness_record_count": sum(
            1 for record in records if record.formal_quote_freshness_record
        ),
        "formal_quote_freshness_ok_record_count": sum(
            1 for record in records if record.formal_quote_freshness_ok
        ),
        "formal_quote_freshness_missing_record_count": sum(
            1 for record in records if record.formal_quote_freshness_missing
        ),
        "formal_quote_freshness_stale_record_count": sum(
            1 for record in records if record.formal_quote_freshness_stale
        ),
        "formal_quote_freshness_blocked_record_count": sum(
            1 for record in records if record.formal_quote_freshness_blocked
        ),
        "formal_quote_pre_readiness_scheduler_record_count": sum(
            1 for record in records if record.formal_quote_pre_readiness_scheduler_record
        ),
        "formal_quote_pre_readiness_scheduler_ok_record_count": sum(
            1 for record in records if record.formal_quote_pre_readiness_scheduler_ok
        ),
        "formal_quote_pre_readiness_scheduler_missing_record_count": sum(
            1 for record in records if record.formal_quote_pre_readiness_scheduler_missing
        ),
        "formal_quote_pre_readiness_scheduler_blocked_record_count": sum(
            1 for record in records if record.formal_quote_pre_readiness_scheduler_blocked
        ),
        **_build_formal_risk_quality(records),
        **_build_weekly_report_quality(records),
        "evidence_modes": sorted({record.evidence_mode for record in records}),
        "trigger_sources": sorted(
            {record.trigger_source for record in records if record.trigger_source is not None}
        ),
        "trigger_task_names": sorted(
            {record.trigger_task_name for record in records if record.trigger_task_name is not None}
        ),
    }


def _classify_payload(payload: dict[str, Any]) -> dict[str, Any]:
    operation_context = dict(payload.get("operation_context") or {})
    if not operation_context:
        return {
            "evidence_mode": "legacy_without_operation_context",
            "acceptance_candidate": True,
            "trigger_source": None,
            "trigger_task_id": None,
            "trigger_task_name": None,
        }
    is_formal = (
        operation_context.get("mode") == "formal"
        and operation_context.get("target_date_closed") is True
        and operation_context.get("allow_unclosed_target_date") is not True
    )
    return {
        "evidence_mode": str(operation_context.get("mode") or "unknown"),
        "acceptance_candidate": is_formal,
        "trigger_source": (
            str(operation_context.get("trigger_source"))
            if operation_context.get("trigger_source") is not None
            else None
        ),
        "trigger_task_id": (
            str(operation_context.get("trigger_task_id"))
            if operation_context.get("trigger_task_id") is not None
            else None
        ),
        "trigger_task_name": (
            str(operation_context.get("trigger_task_name"))
            if operation_context.get("trigger_task_name") is not None
            else None
        ),
    }


def _build_weekly_report_quality(records: list[_EvidenceRecord]) -> dict[str, Any]:
    record_groups = {
        "weekly_report": records,
        "scheduled_weekly_report": [record for record in records if record.target_date.weekday() == 4],
    }
    quality: dict[str, Any] = {}
    for prefix, grouped_records in record_groups.items():
        quality.update(
            {
                f"{prefix}_record_count": sum(
                    1 for record in grouped_records if record.weekly_report_account_count > 0
                ),
                f"{prefix}_persistence_ok_record_count": sum(
                    1
                    for record in grouped_records
                    if record.weekly_report_persistence_status == "ok"
                ),
                f"{prefix}_persistence_missing_record_count": sum(
                    1
                    for record in grouped_records
                    if record.weekly_report_persistence_status == "missing"
                ),
                f"{prefix}_persistence_warning_record_count": sum(
                    1
                    for record in grouped_records
                    if record.weekly_report_persistence_status == "warning"
                ),
                f"{prefix}_account_count": sum(
                    record.weekly_report_account_count for record in grouped_records
                ),
                f"{prefix}_persistence_ok_account_count": sum(
                    record.weekly_report_persistence_ok_account_count
                    for record in grouped_records
                ),
                f"{prefix}_persistence_missing_account_count": sum(
                    record.weekly_report_persistence_missing_account_count
                    for record in grouped_records
                ),
                f"{prefix}_persistence_warning_account_count": sum(
                    record.weekly_report_persistence_warning_account_count
                    for record in grouped_records
                ),
            }
        )
    return quality


def _build_formal_risk_quality(records: list[_EvidenceRecord]) -> dict[str, Any]:
    return {
        "formal_risk_record_count": sum(
            1 for record in records if record.formal_risk_account_count > 0
        ),
        "formal_risk_ok_record_count": sum(
            1 for record in records if record.formal_risk_evidence_status == "ok"
        ),
        "formal_risk_missing_record_count": sum(
            1
            for record in records
            if record.formal_risk_account_count > 0 and record.formal_risk_evidence_status != "ok"
        ),
        "formal_risk_account_count": sum(record.formal_risk_account_count for record in records),
        "formal_risk_report_ok_account_count": sum(
            record.formal_risk_report_ok_account_count for record in records
        ),
        "formal_risk_persisted_report_account_count": sum(
            record.formal_risk_persisted_report_account_count for record in records
        ),
        "formal_pre_trade_ok_account_count": sum(
            record.formal_pre_trade_ok_account_count for record in records
        ),
        "formal_pre_trade_missing_account_count": sum(
            record.formal_pre_trade_missing_account_count for record in records
        ),
        "formal_post_investment_ok_account_count": sum(
            record.formal_post_investment_ok_account_count for record in records
        ),
        "formal_post_investment_missing_account_count": sum(
            record.formal_post_investment_missing_account_count for record in records
        ),
    }


def _classify_auto_advisor_weekly_persistence(payload: dict[str, Any]) -> dict[str, Any]:
    weekly_report_account_count = 0
    persistence_ok_count = 0
    persistence_missing_count = 0
    persistence_warning_count = 0

    for account in payload.get("accounts") or []:
        advisor = dict(account.get("auto_advisor") or {})
        if advisor.get("weekly_report") is None:
            continue
        weekly_report_account_count += 1
        persistence = advisor.get("weekly_report_persistence")
        if not isinstance(persistence, dict):
            persistence_missing_count += 1
            continue
        if persistence.get("status") == "ok":
            persistence_ok_count += 1
        else:
            persistence_warning_count += 1

    if weekly_report_account_count <= 0:
        status = "not_requested"
    elif persistence_missing_count > 0:
        status = "missing"
    elif persistence_warning_count > 0:
        status = "warning"
    elif persistence_ok_count == weekly_report_account_count:
        status = "ok"
    else:
        status = "partial"

    return {
        "weekly_report_account_count": weekly_report_account_count,
        "weekly_report_persistence_ok_account_count": persistence_ok_count,
        "weekly_report_persistence_missing_account_count": persistence_missing_count,
        "weekly_report_persistence_warning_account_count": persistence_warning_count,
        "weekly_report_persistence_status": status,
    }


def _classify_formal_decision_data_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    classification = _classify_payload(payload)
    if classification["evidence_mode"] != "formal" or not classification["acceptance_candidate"]:
        return {
            "formal_decision_data_record": False,
            "formal_decision_data_ok": False,
            "formal_decision_data_missing": False,
            "formal_decision_data_blocked": False,
        }

    decision_data = _get_decision_data(payload)
    if not decision_data:
        return {
            "formal_decision_data_record": True,
            "formal_decision_data_ok": False,
            "formal_decision_data_missing": True,
            "formal_decision_data_blocked": False,
        }

    must_not_use = decision_data.get("must_not_use_for_decision") is True
    ok = (
        decision_data.get("status") == "ok"
        and decision_data.get("readiness_status") == "ok"
        and not must_not_use
    )
    return {
        "formal_decision_data_record": True,
        "formal_decision_data_ok": ok,
        "formal_decision_data_missing": False,
        "formal_decision_data_blocked": must_not_use,
    }


def _classify_formal_quote_freshness_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    classification = _classify_payload(payload)
    if classification["evidence_mode"] != "formal" or not classification["acceptance_candidate"]:
        return {
            "formal_quote_freshness_record": False,
            "formal_quote_freshness_ok": False,
            "formal_quote_freshness_missing": False,
            "formal_quote_freshness_stale": False,
            "formal_quote_freshness_blocked": False,
        }

    decision_data = _get_decision_data(payload)
    status = _decision_quote_freshness_status(decision_data)
    return {
        "formal_quote_freshness_record": True,
        "formal_quote_freshness_ok": status == "ok",
        "formal_quote_freshness_missing": status == "missing",
        "formal_quote_freshness_stale": status == "stale",
        "formal_quote_freshness_blocked": status == "blocked",
    }


def _classify_formal_quote_pre_readiness_scheduler_evidence(
    payload: dict[str, Any],
) -> dict[str, Any]:
    classification = _classify_payload(payload)
    if classification["evidence_mode"] != "formal" or not classification["acceptance_candidate"]:
        return {
            "formal_quote_pre_readiness_scheduler_record": False,
            "formal_quote_pre_readiness_scheduler_ok": False,
            "formal_quote_pre_readiness_scheduler_missing": False,
            "formal_quote_pre_readiness_scheduler_blocked": False,
        }

    scheduler_evidence = payload.get("scheduler_evidence")
    quote_pre_readiness_scheduler = (
        scheduler_evidence.get("quote_pre_readiness_scheduler")
        if isinstance(scheduler_evidence, dict)
        else None
    )
    status = _quote_pre_readiness_scheduler_evidence_status(
        quote_pre_readiness_scheduler,
        target_date=_parse_payload_target_date(payload),
    )
    return {
        "formal_quote_pre_readiness_scheduler_record": True,
        "formal_quote_pre_readiness_scheduler_ok": status == "ok",
        "formal_quote_pre_readiness_scheduler_missing": status == "missing",
        "formal_quote_pre_readiness_scheduler_blocked": status == "blocked",
    }


def _quote_pre_readiness_scheduler_evidence_status(
    value: Any,
    *,
    target_date: date | None,
) -> str:
    if not isinstance(value, dict) or not value:
        return "missing"
    if value.get("status") == "missing":
        return "missing"
    safety = value.get("safety")
    safety_status = safety.get("status") if isinstance(safety, dict) else None
    run_metadata = value.get("run_metadata")
    latest_run_date = _parse_iso_datetime_date(
        run_metadata.get("last_run_at") if isinstance(run_metadata, dict) else None
    )
    if (
        value.get("status") == "ok"
        and value.get("enabled") is True
        and safety_status == "ok"
        and target_date is not None
        and latest_run_date is not None
        and latest_run_date >= target_date
    ):
        return "ok"
    return "blocked"


def _parse_payload_target_date(payload: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(payload.get("target_date") or ""))
    except ValueError:
        return None


def _parse_iso_datetime_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _decision_quote_freshness_status(decision_data: dict[str, Any]) -> str:
    quotes = decision_data.get("quotes")
    if not isinstance(quotes, dict) or not quotes:
        return "missing"

    has_stale = False
    for quote in quotes.values():
        if not isinstance(quote, dict):
            return "blocked"
        if quote.get("must_not_use_for_decision") is True:
            return "blocked"
        if quote.get("status") != "ok":
            return "blocked"
        if quote.get("is_stale") is True:
            has_stale = True
        freshness_status = str(quote.get("freshness_status") or "").lower()
        if freshness_status and freshness_status not in {"fresh", "ok"}:
            has_stale = True
    return "stale" if has_stale else "ok"


def _classify_formal_workspace_core_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    classification = _classify_payload(payload)
    if classification["evidence_mode"] != "formal" or not classification["acceptance_candidate"]:
        return {
            "formal_workspace_core_record": False,
            "formal_workspace_core_ok": False,
            "formal_workspace_core_missing": False,
        }

    components = _get_workspace_components(payload)
    if not components:
        return {
            "formal_workspace_core_record": True,
            "formal_workspace_core_ok": False,
            "formal_workspace_core_missing": True,
        }
    ok = _workspace_core_status(components) == "ok"
    return {
        "formal_workspace_core_record": True,
        "formal_workspace_core_ok": ok,
        "formal_workspace_core_missing": False,
    }


def _classify_formal_qlib_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    classification = _classify_payload(payload)
    if classification["evidence_mode"] != "formal" or not classification["acceptance_candidate"]:
        return {
            "formal_qlib_record": False,
            "formal_qlib_ok": False,
            "formal_qlib_missing": False,
            "formal_qlib_blocked": False,
        }

    qlib = payload.get("qlib")
    if not isinstance(qlib, dict):
        return {
            "formal_qlib_record": True,
            "formal_qlib_ok": False,
            "formal_qlib_missing": True,
            "formal_qlib_blocked": False,
        }
    ok = _qlib_evidence_status(qlib) == "ok"
    return {
        "formal_qlib_record": True,
        "formal_qlib_ok": ok,
        "formal_qlib_missing": False,
        "formal_qlib_blocked": not ok,
    }


def _qlib_evidence_status(qlib: dict[str, Any]) -> str:
    if not qlib:
        return "missing"
    if qlib.get("status") != "ok":
        return str(qlib.get("status") or "blocked")
    if qlib.get("check_only") is not True:
        return "not_check_only"
    return "ok"


def _get_workspace_components(payload: dict[str, Any]) -> dict[str, Any]:
    workspace = dict(payload.get("workspace") or {})
    result = dict(workspace.get("result") or {})
    components = result.get("components")
    return dict(components) if isinstance(components, dict) else {}


def _workspace_core_status(components: dict[str, Any]) -> str:
    regime = dict(components.get("regime_snapshot") or {})
    pulse = dict(components.get("pulse_snapshot") or {})
    action = dict(components.get("action_recommendation") or {})
    if not regime or not pulse or not action:
        return "missing"
    if regime.get("status") != "success":
        return "regime_not_success"
    if pulse.get("status") != "success":
        return "pulse_not_success"
    if pulse.get("is_reliable") is not True:
        return "pulse_not_reliable"
    if action.get("status") != "success":
        return "action_not_success"
    return "ok"


def _classify_formal_alpha_workspace_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    classification = _classify_payload(payload)
    if classification["evidence_mode"] != "formal" or not classification["acceptance_candidate"]:
        return {
            "formal_alpha_workspace_record": False,
            "formal_alpha_workspace_ok": False,
            "formal_alpha_workspace_missing": False,
        }

    alpha_workspace = _get_alpha_workspace_consistency(payload)
    if not alpha_workspace:
        return {
            "formal_alpha_workspace_record": True,
            "formal_alpha_workspace_ok": False,
            "formal_alpha_workspace_missing": True,
        }
    ok = alpha_workspace.get("status") == "ok"
    return {
        "formal_alpha_workspace_record": True,
        "formal_alpha_workspace_ok": ok,
        "formal_alpha_workspace_missing": False,
    }


def _get_alpha_workspace_consistency(payload: dict[str, Any]) -> dict[str, Any]:
    system = dict(payload.get("system") or {})
    checks = dict(system.get("checks") or {})
    alpha_workspace = checks.get("alpha_workspace_consistency")
    return dict(alpha_workspace) if isinstance(alpha_workspace, dict) else {}


def _get_decision_data(payload: dict[str, Any]) -> dict[str, Any]:
    system = dict(payload.get("system") or {})
    checks = dict(system.get("checks") or {})
    decision_data = checks.get("decision_data")
    return dict(decision_data) if isinstance(decision_data, dict) else {}


def _build_evidence_quality(
    *,
    records: list[_EvidenceRecord],
    trading_records: list[_EvidenceRecord],
) -> dict[str, Any]:
    trading_paths = {record.path for record in trading_records}
    return {
        "record_count": len(records),
        "trading_record_count": len(trading_records),
        "non_trading_record_count": len(records) - len(trading_records),
        "accepted_record_count": sum(1 for record in records if record.accepted),
        "rejected_record_count": sum(1 for record in records if not record.accepted),
        "acceptance_candidate_record_count": sum(
            1 for record in records if record.acceptance_candidate
        ),
        "formal_record_count": sum(1 for record in records if record.evidence_mode == "formal"),
        "legacy_record_count": sum(
            1 for record in records if record.evidence_mode == "legacy_without_operation_context"
        ),
        "diagnostic_record_count": sum(1 for record in records if not record.acceptance_candidate),
        "scheduler_trigger_record_count": sum(
            1 for record in records if record.trigger_source == "scheduler"
        ),
        "manual_trigger_record_count": sum(
            1 for record in records if record.trigger_source == "manual"
        ),
        "unknown_trigger_record_count": sum(
            1 for record in records if record.trigger_source is None
        ),
        "task_provenance_record_count": sum(
            1 for record in records if record.trigger_task_id or record.trigger_task_name
        ),
        "missing_task_provenance_record_count": sum(
            1 for record in records if not record.trigger_task_id and not record.trigger_task_name
        ),
        "formal_workspace_core_record_count": sum(
            1 for record in records if record.formal_workspace_core_record
        ),
        "formal_workspace_core_ok_record_count": sum(
            1 for record in records if record.formal_workspace_core_ok
        ),
        "formal_workspace_core_missing_record_count": sum(
            1 for record in records if record.formal_workspace_core_missing
        ),
        "formal_qlib_record_count": sum(1 for record in records if record.formal_qlib_record),
        "formal_qlib_ok_record_count": sum(1 for record in records if record.formal_qlib_ok),
        "formal_qlib_missing_record_count": sum(
            1 for record in records if record.formal_qlib_missing
        ),
        "formal_qlib_blocked_record_count": sum(
            1 for record in records if record.formal_qlib_blocked
        ),
        "formal_alpha_workspace_record_count": sum(
            1 for record in records if record.formal_alpha_workspace_record
        ),
        "formal_alpha_workspace_ok_record_count": sum(
            1 for record in records if record.formal_alpha_workspace_ok
        ),
        "formal_alpha_workspace_missing_record_count": sum(
            1 for record in records if record.formal_alpha_workspace_missing
        ),
        "formal_decision_data_record_count": sum(
            1 for record in records if record.formal_decision_data_record
        ),
        "formal_decision_data_ok_record_count": sum(
            1 for record in records if record.formal_decision_data_ok
        ),
        "formal_decision_data_missing_record_count": sum(
            1 for record in records if record.formal_decision_data_missing
        ),
        "formal_decision_data_blocked_record_count": sum(
            1 for record in records if record.formal_decision_data_blocked
        ),
        "formal_quote_freshness_record_count": sum(
            1 for record in records if record.formal_quote_freshness_record
        ),
        "formal_quote_freshness_ok_record_count": sum(
            1 for record in records if record.formal_quote_freshness_ok
        ),
        "formal_quote_freshness_missing_record_count": sum(
            1 for record in records if record.formal_quote_freshness_missing
        ),
        "formal_quote_freshness_stale_record_count": sum(
            1 for record in records if record.formal_quote_freshness_stale
        ),
        "formal_quote_freshness_blocked_record_count": sum(
            1 for record in records if record.formal_quote_freshness_blocked
        ),
        "formal_quote_pre_readiness_scheduler_record_count": sum(
            1 for record in records if record.formal_quote_pre_readiness_scheduler_record
        ),
        "formal_quote_pre_readiness_scheduler_ok_record_count": sum(
            1 for record in records if record.formal_quote_pre_readiness_scheduler_ok
        ),
        "formal_quote_pre_readiness_scheduler_missing_record_count": sum(
            1 for record in records if record.formal_quote_pre_readiness_scheduler_missing
        ),
        "formal_quote_pre_readiness_scheduler_blocked_record_count": sum(
            1 for record in records if record.formal_quote_pre_readiness_scheduler_blocked
        ),
        **_build_formal_risk_quality(records),
        **_build_weekly_report_quality(records),
        "non_trading_dates": [
            record.target_date.isoformat() for record in records if record.path not in trading_paths
        ],
        "rejected_dates": [
            {
                "target_date": record.target_date.isoformat(),
                "reason": record.reason,
                "evidence_mode": record.evidence_mode,
            }
            for record in records
            if not record.accepted
        ],
    }


def _evaluate_payload(payload: dict[str, Any]) -> tuple[bool, str]:
    if payload.get("status") != "ok":
        return False, f"overall status is {payload.get('status') or 'missing'}"

    operation_context = dict(payload.get("operation_context") or {})
    if operation_context:
        if operation_context.get("mode") != "formal":
            return False, f"operation_context mode is {operation_context.get('mode')}"
        if operation_context.get("target_date_closed") is not True:
            return False, "operation_context target_date_closed is not true"
        if operation_context.get("allow_unclosed_target_date") is True:
            return False, "operation_context allow_unclosed_target_date is true"

    summary = dict(payload.get("summary") or {})
    required_summary_statuses = {
        "system_status": "ok",
        "qlib_status": "ok",
        "workspace_status": "ok",
    }
    for key, expected in required_summary_statuses.items():
        actual = summary.get(key)
        if actual != expected:
            return False, f"{key} is {actual or 'missing'}"

    if int(summary.get("target_count") or 0) <= 0:
        return False, "target_count is zero"

    if operation_context:
        qlib = payload.get("qlib")
        if not isinstance(qlib, dict):
            return False, "qlib readiness evidence is missing"
        qlib_status = _qlib_evidence_status(qlib)
        if qlib_status != "ok":
            return False, f"qlib readiness evidence status is {qlib_status}"
        workspace_components = _get_workspace_components(payload)
        workspace_status = _workspace_core_status(workspace_components)
        if workspace_status != "ok":
            return False, f"workspace core evidence status is {workspace_status}"
        alpha_workspace = _get_alpha_workspace_consistency(payload)
        if not alpha_workspace:
            return False, "alpha_workspace_consistency evidence is missing"
        if alpha_workspace.get("status") != "ok":
            return (
                False,
                f"alpha_workspace_consistency status is "
                f"{alpha_workspace.get('status') or 'missing'}",
            )
        decision_data = _get_decision_data(payload)
        if not decision_data:
            return False, "decision_data readiness evidence is missing"
        if decision_data.get("status") != "ok":
            return False, f"decision_data status is {decision_data.get('status') or 'missing'}"
        if decision_data.get("readiness_status") != "ok":
            return (
                False,
                f"decision_data readiness_status is "
                f"{decision_data.get('readiness_status') or 'missing'}",
            )
        if decision_data.get("must_not_use_for_decision") is True:
            return False, "decision_data must_not_use_for_decision is true"
        quote_status = _decision_quote_freshness_status(decision_data)
        if quote_status != "ok":
            return False, f"decision quote freshness status is {quote_status}"

    accounts = list(payload.get("accounts") or [])
    if not accounts:
        return False, "accounts evidence is missing"

    for account in accounts:
        account_id = account.get("account_id") or "-"
        if account.get("status") != "ok":
            return False, f"account {account_id} status is {account.get('status')}"
        risk = dict(account.get("risk_center_daily_report") or {})
        if risk.get("status") != "ok":
            return False, f"account {account_id} risk status is {risk.get('status')}"
        if operation_context:
            pre_trade = dict(risk.get("pre_trade_check") or {})
            if pre_trade.get("status") != "ok":
                return (
                    False,
                    f"account {account_id} pre-trade risk status is "
                    f"{pre_trade.get('status') or 'missing'}",
                )
            post_investment = dict(risk.get("post_investment_check") or {})
            if post_investment.get("passed") is not True:
                return (
                    False,
                    f"account {account_id} post-investment risk passed is "
                    f"{post_investment.get('passed')}",
                )
        advisor = dict(account.get("auto_advisor") or {})
        if advisor.get("status") != "ok":
            return False, f"account {account_id} advisor status is {advisor.get('status')}"

    return True, "accepted"


def _is_trading_day(value: date, calendar: _TradingCalendar) -> bool:
    if calendar.dates is not None:
        return value in calendar.date_set
    return _is_weekday(value)


def _previous_trading_day(value: date, calendar: _TradingCalendar) -> date:
    if calendar.dates is not None:
        index = bisect_left(calendar.dates, value)
        if index <= 0:
            return date.min
        return calendar.dates[index - 1]
    return _previous_weekday(value)


def _next_trading_day(value: date, calendar: _TradingCalendar) -> date:
    if calendar.dates is not None:
        index = bisect_left(calendar.dates, value)
        while index < len(calendar.dates) and calendar.dates[index] <= value:
            index += 1
        if index < len(calendar.dates):
            return calendar.dates[index]
    return _next_weekday(value)


def _is_weekday(value: date) -> bool:
    return value.weekday() < 5


def _previous_weekday(value: date) -> date:
    current = date.fromordinal(value.toordinal() - 1)
    while not _is_weekday(current):
        current = date.fromordinal(current.toordinal() - 1)
    return current


def _next_weekday(value: date) -> date:
    current = date.fromordinal(value.toordinal() + 1)
    while not _is_weekday(current):
        current = date.fromordinal(current.toordinal() + 1)
    return current
