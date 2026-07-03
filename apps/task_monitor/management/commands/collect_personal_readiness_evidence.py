"""Collect repeatable personal investment readiness evidence."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management import CommandError, call_command
from django.core.management.base import BaseCommand

from apps.account.application.query_services import get_application_user_by_id
from apps.alpha.application.trade_dates import resolve_recent_closed_trade_date
from apps.dashboard.application.query_services import (
    build_auto_advisor_console_payload,
    build_auto_advisor_notifications_payload,
    build_auto_advisor_weekly_report_history_payload,
    build_auto_advisor_weekly_report_payload,
)
from apps.risk_center.application.trade_guard import (
    EvaluatePreTradeRiskUseCase,
    GenerateRiskCenterDailyReportUseCase,
)
from apps.simulated_trading.application.query_services import (
    get_position_snapshots,
    list_active_account_targets,
    list_dashboard_account_payloads,
)
from apps.task_monitor.application import readiness_status_services as status_services
from apps.task_monitor.management.quote_pre_readiness_scheduler_status import (
    collect_quote_pre_readiness_scheduler_status,
)
from core.health_checks import is_healthy, run_readiness_checks

DEFAULT_OUTPUT_DIR = "var/readiness-evidence"


class Command(BaseCommand):
    help = "Collect daily evidence for personal investment system readiness."
    stealth_options = ("trigger_source", "trigger_task_id", "trigger_task_name")

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--target-date",
            dest="target_date",
            default=None,
            help=(
                "Readiness date in YYYY-MM-DD format; defaults to the latest closed " "trading day."
            ),
        )
        parser.add_argument(
            "--user-id",
            dest="user_id",
            type=int,
            default=None,
            help="Restrict account checks to one user.",
        )
        parser.add_argument(
            "--account-id",
            dest="account_id",
            type=int,
            default=None,
            help="Restrict account checks to one account.",
        )
        parser.add_argument(
            "--output-dir",
            dest="output_dir",
            default=DEFAULT_OUTPUT_DIR,
            help=f"Directory for evidence files. Default: {DEFAULT_OUTPUT_DIR}",
        )
        parser.add_argument(
            "--max-qlib-staleness-days",
            dest="max_qlib_staleness_days",
            type=int,
            default=5,
            help="Allowed Qlib freshness lag for build_qlib_data --check-only.",
        )
        parser.add_argument(
            "--run-workspace-refresh",
            dest="run_workspace_refresh",
            action="store_true",
            help="Run the Regime/Pulse/Rotation workspace snapshot refresh task inline.",
        )
        parser.add_argument(
            "--include-weekly-advisor",
            dest="include_weekly_advisor",
            action="store_true",
            help="Also generate the auto-advisor weekly report payload.",
        )
        parser.add_argument(
            "--persist-risk-report",
            dest="persist_risk_report",
            action="store_true",
            help="Persist generated risk-center daily reports.",
        )
        parser.add_argument(
            "--allow-unclosed-target-date",
            action="store_true",
            help=(
                "Allow target-date later than the latest closed trading day. "
                "Use only for diagnostics."
            ),
        )
        parser.add_argument(
            "--no-file",
            dest="write_file",
            action="store_false",
            default=True,
            help="Print evidence only; do not write JSON/Markdown evidence files.",
        )
        parser.add_argument(
            "--json",
            dest="print_json",
            action="store_true",
            help="Print the full JSON payload to stdout.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        target_date = _parse_date(options.get("target_date"))
        allow_unclosed_target_date = bool(options.get("allow_unclosed_target_date"))
        _validate_target_date_is_closed(
            target_date=target_date,
            allow_unclosed_target_date=allow_unclosed_target_date,
        )
        payload = collect_personal_readiness_evidence(
            target_date=target_date,
            user_id=options.get("user_id"),
            account_id=options.get("account_id"),
            max_qlib_staleness_days=int(options["max_qlib_staleness_days"]),
            run_workspace_refresh=bool(options["run_workspace_refresh"]),
            include_weekly_advisor=bool(options["include_weekly_advisor"]),
            persist_risk_report=bool(options["persist_risk_report"]),
            allow_unclosed_target_date=allow_unclosed_target_date,
            trigger_source=str(options.get("trigger_source") or "manual"),
            trigger_task_id=options.get("trigger_task_id"),
            trigger_task_name=options.get("trigger_task_name"),
        )

        output_paths = {}
        if options.get("write_file"):
            output_paths = write_personal_readiness_evidence_files(
                payload=payload,
                output_dir=Path(str(options["output_dir"])),
            )
            payload["output_paths"] = output_paths

        if options.get("print_json"):
            self.stdout.write(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2))
        else:
            status = str(payload.get("status") or "unknown")
            summary = payload.get("summary") or {}
            target_count = int(summary.get("target_count") or 0)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Personal readiness evidence collected: status={status}, "
                    f"targets={target_count}"
                )
            )
            if output_paths:
                self.stdout.write(f"  json: {output_paths.get('json')}")
                self.stdout.write(f"  markdown: {output_paths.get('markdown')}")

        return None


def collect_personal_readiness_evidence(
    *,
    target_date: date,
    user_id: int | None,
    account_id: int | None,
    max_qlib_staleness_days: int = 5,
    run_workspace_refresh: bool = False,
    include_weekly_advisor: bool = False,
    persist_risk_report: bool = False,
    allow_unclosed_target_date: bool = False,
    trigger_source: str = "manual",
    trigger_task_id: str | None = None,
    trigger_task_name: str | None = None,
) -> dict[str, Any]:
    """Collect daily readiness evidence without requiring every subsystem to pass."""

    generated_at = datetime.now(UTC)
    latest_closed_date = resolve_default_readiness_target_date()
    operation_context = _build_operation_context(
        target_date=target_date,
        latest_closed_date=latest_closed_date,
        allow_unclosed_target_date=allow_unclosed_target_date,
        trigger_source=trigger_source,
        trigger_task_id=trigger_task_id,
        trigger_task_name=trigger_task_name,
    )
    system = _collect_system_readiness(target_date=target_date)
    decision_data_summary = _summarize_system_decision_data(system)
    macro_context_summary = _summarize_system_macro_context(system)
    alpha_workspace_summary = _summarize_system_alpha_workspace(system)
    qlib = _collect_qlib_readiness(
        target_date=target_date,
        max_staleness_days=max_qlib_staleness_days,
    )
    workspace = _collect_workspace_refresh(
        target_date=target_date,
        enabled=run_workspace_refresh,
    )
    scheduler_evidence = _collect_scheduler_evidence()
    targets = _resolve_targets(user_id=user_id, account_id=account_id)
    account_checks = [
        _collect_account_evidence(
            target=target,
            target_date=target_date,
            include_weekly_advisor=include_weekly_advisor,
            persist_risk_report=persist_risk_report,
        )
        for target in targets
    ]

    sections = [system, qlib, workspace, *account_checks]
    overall_status = _rollup_status(
        [str(section.get("status") or "unknown") for section in sections]
    )

    return {
        "schema_version": "2026-06-30.v1",
        "status": overall_status,
        "target_date": target_date.isoformat(),
        "generated_at": generated_at.isoformat(),
        "inputs": {
            "user_id": user_id,
            "account_id": account_id,
            "max_qlib_staleness_days": max_qlib_staleness_days,
            "run_workspace_refresh": run_workspace_refresh,
            "include_weekly_advisor": include_weekly_advisor,
            "persist_risk_report": persist_risk_report,
            "allow_unclosed_target_date": allow_unclosed_target_date,
            "trigger_source": trigger_source,
            "trigger_task_id": trigger_task_id,
            "trigger_task_name": trigger_task_name,
        },
        "operation_context": operation_context,
        "summary": {
            "system_status": system.get("status"),
            "qlib_status": qlib.get("status"),
            "workspace_status": workspace.get("status"),
            "quote_pre_readiness_scheduler_status": (
                scheduler_evidence.get("quote_pre_readiness_scheduler") or {}
            ).get("status"),
            "decision_data": decision_data_summary,
            "macro_context": macro_context_summary,
            "alpha_workspace_consistency": alpha_workspace_summary,
            "target_count": len(targets),
            "account_status_counts": _count_statuses(account_checks),
        },
        "system": system,
        "qlib": qlib,
        "workspace": workspace,
        "scheduler_evidence": scheduler_evidence,
        "accounts": account_checks,
    }


def _collect_scheduler_evidence() -> dict[str, Any]:
    return {
        "quote_pre_readiness_scheduler": collect_quote_pre_readiness_scheduler_status(),
    }


def _summarize_system_decision_data(system: dict[str, Any]) -> dict[str, Any] | None:
    checks = system.get("checks") if isinstance(system, dict) else {}
    if not isinstance(checks, dict):
        return None
    decision_data = checks.get("decision_data")
    if not isinstance(decision_data, dict):
        return None
    return status_services.summarize_decision_data(decision_data)


def _summarize_system_macro_context(system: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(system, dict):
        return None
    return status_services.summarize_evidence_macro_context({"system": system})


def _summarize_system_alpha_workspace(system: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(system, dict):
        return None
    return status_services.summarize_evidence_alpha_workspace({"system": system})


def _collect_system_readiness(*, target_date: date) -> dict[str, Any]:
    try:
        checks = run_readiness_checks()
        macro_context = status_services.build_current_macro_context(target_date=target_date)
        checks["regime"] = macro_context.get("regime")
        checks["pulse"] = macro_context.get("pulse")
        return {
            "status": "ok" if is_healthy(checks) else "error",
            "healthy": is_healthy(checks),
            "checks": checks,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _build_operation_context(
    *,
    target_date: date,
    latest_closed_date: date,
    allow_unclosed_target_date: bool,
    trigger_source: str = "manual",
    trigger_task_id: str | None = None,
    trigger_task_name: str | None = None,
) -> dict[str, Any]:
    target_date_closed = target_date <= latest_closed_date
    if allow_unclosed_target_date:
        mode = "diagnostic_override" if target_date_closed else "diagnostic_unclosed_target"
    else:
        mode = "formal" if target_date_closed else "diagnostic_unclosed_target"
    return {
        "collector": "collect_personal_readiness_evidence",
        "target_date_closed": target_date_closed,
        "latest_closed_date": latest_closed_date.isoformat(),
        "allow_unclosed_target_date": allow_unclosed_target_date,
        "mode": mode,
        "trigger_source": trigger_source,
        "trigger_task_id": trigger_task_id,
        "trigger_task_name": trigger_task_name,
    }


def _collect_qlib_readiness(*, target_date: date, max_staleness_days: int) -> dict[str, Any]:
    buffer = StringIO()
    try:
        call_command(
            "build_qlib_data",
            check_only=True,
            target_date=target_date.isoformat(),
            max_staleness_days=max_staleness_days,
            stdout=buffer,
            stderr=buffer,
        )
        return {
            "status": "ok",
            "check_only": True,
            "command": "build_qlib_data --check-only",
            "output": buffer.getvalue().strip(),
        }
    except CommandError as exc:
        return {
            "status": "warning",
            "check_only": True,
            "command": "build_qlib_data --check-only",
            "error": str(exc),
            "output": buffer.getvalue().strip(),
        }
    except Exception as exc:
        return {
            "status": "error",
            "check_only": True,
            "command": "build_qlib_data --check-only",
            "error": str(exc),
            "output": buffer.getvalue().strip(),
        }


def _collect_workspace_refresh(*, target_date: date, enabled: bool) -> dict[str, Any]:
    if not enabled:
        return {
            "status": "skipped",
            "reason": "run_workspace_refresh_not_requested",
        }
    try:
        from apps.decision_rhythm.application.tasks import refresh_decision_workspace_snapshots

        result = refresh_decision_workspace_snapshots.run(
            as_of_date=target_date.isoformat(),
            source="akshare",
        )
        status = str((result or {}).get("status") or "unknown")
        return {
            "status": "ok" if status == "success" else "warning",
            "task_status": status,
            "result": result,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _resolve_targets(*, user_id: int | None, account_id: int | None) -> list[dict[str, int]]:
    if user_id is not None:
        return _dedupe_targets(_resolve_user_targets(user_id=int(user_id), account_id=account_id))

    user_ids: set[int] = set()
    for target in list_active_account_targets():
        if account_id is not None and int(target["account_id"]) != int(account_id):
            continue
        user_ids.add(int(target["user_id"]))
    targets = [
        target
        for target_user_id in sorted(user_ids)
        for target in _resolve_user_targets(
            user_id=target_user_id,
            account_id=account_id,
        )
    ]
    return _dedupe_targets(targets)


def _resolve_user_targets(*, user_id: int, account_id: int | None) -> list[dict[str, int]]:
    accounts = [
        dict(account)
        for account in list_dashboard_account_payloads(int(user_id))
        if bool(account.get("is_active"))
        and (account_id is None or int(account.get("id") or 0) == int(account_id))
    ]
    if account_id is None:
        decision_ready_accounts = []
        for account in accounts:
            total_value = _optional_float(account.get("total_value"))
            if total_value is not None and total_value > 0:
                decision_ready_accounts.append(account)
        if decision_ready_accounts:
            accounts = decision_ready_accounts
    return [
        {
            "user_id": int(user_id),
            "account_id": int(account["id"]),
        }
        for account in accounts
    ]


def _collect_account_evidence(
    *,
    target: dict[str, int],
    target_date: date,
    include_weekly_advisor: bool,
    persist_risk_report: bool,
) -> dict[str, Any]:
    user_id = int(target["user_id"])
    account_id = int(target["account_id"])
    user = get_application_user_by_id(user_id)
    if user is None:
        return {
            "status": "error",
            "user_id": user_id,
            "account_id": account_id,
            "error": "user_not_found",
        }

    account_payload = _find_account_payload(user_id=user_id, account_id=account_id)
    risk = _collect_risk_report(
        user=user,
        account_id=account_id,
        account_payload=account_payload,
        target_date=target_date,
        persist=persist_risk_report,
    )
    advisor = _collect_auto_advisor(
        user=user,
        account_id=account_id,
        target_date=target_date,
        include_weekly=include_weekly_advisor,
    )
    status = _rollup_status([str(risk.get("status") or ""), str(advisor.get("status") or "")])
    return {
        "status": status,
        "user_id": user_id,
        "account_id": account_id,
        "account": account_payload or {},
        "risk_center_daily_report": risk,
        "auto_advisor": advisor,
    }


def _find_account_payload(*, user_id: int, account_id: int) -> dict[str, Any] | None:
    for account in list_dashboard_account_payloads(int(user_id)):
        if int(account.get("id") or 0) == int(account_id):
            return dict(account)
    return None


def _collect_risk_report(
    *,
    user: Any,
    account_id: int,
    account_payload: dict[str, Any] | None,
    target_date: date,
    persist: bool,
) -> dict[str, Any]:
    if account_payload is None:
        return {"status": "skipped", "reason": "account_payload_not_found"}

    account_equity = _optional_float(account_payload.get("total_value"))
    if account_equity is None or account_equity <= 0:
        return {
            "status": "warning",
            "reason": "account_equity_not_positive",
            "account_equity": account_equity,
        }

    try:
        positions = get_position_snapshots(account_id=account_id)
        pre_trade = _collect_pre_trade_risk_probe(
            account_id=account_id,
            account_equity=account_equity,
            cash_balance=_optional_float(account_payload.get("cash")),
            total_position_value=_optional_float(account_payload.get("market_value")),
            positions=positions,
        )
        result = GenerateRiskCenterDailyReportUseCase().execute(
            account_id=account_id,
            report_date=target_date.isoformat(),
            account_equity=account_equity,
            cash_balance=_optional_float(account_payload.get("cash")),
            total_position_value=_optional_float(account_payload.get("market_value")),
            positions=positions,
            actor=user,
            persist=persist,
        )
        report_status = str(result.risk_daily_report.get("status") or "unknown")
        status = _rollup_status(
            [
                "ok" if report_status == "ok" else "warning",
                str(pre_trade.get("status") or "unknown"),
            ]
        )
        return {
            "status": status,
            "persisted": persist,
            "report_id": result.report_id,
            "risk_daily_report": result.risk_daily_report,
            "position_daily_report": result.position_daily_report,
            "pre_trade_check": pre_trade,
            "post_investment_check": result.post_investment_check,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _collect_pre_trade_risk_probe(
    *,
    account_id: int,
    account_equity: float,
    cash_balance: float | None,
    total_position_value: float | None,
    positions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run a small no-order pre-trade check to prove the guard path is usable."""

    probe = _build_pre_trade_probe(
        account_equity=account_equity,
        cash_balance=cash_balance,
        total_position_value=total_position_value,
        positions=positions,
    )
    if probe is None:
        return {
            "status": "warning",
            "reason": "pre_trade_probe_unavailable",
        }

    try:
        result = EvaluatePreTradeRiskUseCase().execute(account_id=account_id, **probe)
        return {
            "status": "ok",
            "probe_order": probe,
            "passed": result.passed,
            "violations": result.violations,
            "warnings": result.warnings,
            "metrics": result.metrics,
            "effective_policy": result.effective_policy,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc), "probe_order": probe}


def _build_pre_trade_probe(
    *,
    account_equity: float,
    cash_balance: float | None,
    total_position_value: float | None,
    positions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Build a conservative synthetic order for readiness-only pre-trade checks."""

    equity = max(float(account_equity), 0.0)
    if equity <= 0:
        return None

    cash = max(float(cash_balance), 0.0) if cash_balance is not None else 0.0
    total_position = (
        max(float(total_position_value), 0.0)
        if total_position_value is not None
        else sum(_optional_float(item.get("market_value")) or 0.0 for item in positions)
    )
    position = _first_position_with_symbol(positions)
    symbol = str(
        (position or {}).get("symbol") or (position or {}).get("asset_code") or "510300.SH"
    )
    price = (
        _optional_float((position or {}).get("current_price"))
        or _optional_float((position or {}).get("price"))
        or _optional_float((position or {}).get("avg_cost"))
        or 1.0
    )
    current_symbol_position_value = _optional_float((position or {}).get("market_value")) or 0.0

    if cash > 0:
        order_value = max(min(cash * 0.01, equity * 0.005), min(cash, price))
        quantity = max(order_value / price, 0.000001)
        side = "buy"
    elif current_symbol_position_value > 0:
        order_value = min(current_symbol_position_value * 0.01, equity * 0.005)
        quantity = max(order_value / price, 0.000001)
        side = "sell"
    else:
        return None

    return {
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price": price,
        "account_equity": equity,
        "total_position_value": total_position,
        "cash_balance": cash,
        "current_symbol_position_value": current_symbol_position_value,
    }


def _first_position_with_symbol(positions: list[dict[str, Any]]) -> dict[str, Any] | None:
    for position in positions:
        if position.get("symbol") or position.get("asset_code"):
            return position
    return None


def _collect_auto_advisor(
    *,
    user: Any,
    account_id: int,
    target_date: date,
    include_weekly: bool,
) -> dict[str, Any]:
    try:
        console = build_auto_advisor_console_payload(account_id=str(account_id), user=user)
    except Exception as exc:
        return {"status": "error", "console_error": str(exc)}

    weekly: dict[str, Any] | None = None
    weekly_history: dict[str, Any] | None = None
    weekly_notifications: dict[str, Any] | None = None
    weekly_persistence: dict[str, Any] | None = None
    if include_weekly:
        try:
            weekly = build_auto_advisor_weekly_report_payload(
                account_id=str(account_id),
                user=user,
                as_of=target_date,
            )
        except Exception as exc:
            return {
                "status": "warning",
                "console": console,
                "weekly_report_error": str(exc),
            }
        try:
            weekly_history = build_auto_advisor_weekly_report_history_payload(
                user=user,
                account_id=str(account_id),
                limit=20,
            )
            weekly_notifications = build_auto_advisor_notifications_payload(
                user=user,
                account_id=str(account_id),
                limit=20,
            )
            weekly_persistence = _build_weekly_report_persistence_evidence(
                target_date=target_date,
                history=weekly_history,
                notifications=weekly_notifications,
            )
        except Exception as exc:
            weekly_persistence = {
                "status": "warning",
                "target_report_date": target_date.isoformat(),
                "reason": f"weekly report persistence evidence query failed: {exc}",
            }

    return {
        "status": "ok",
        "console": console,
        "weekly_report": weekly,
        "weekly_report_history": weekly_history,
        "weekly_report_notifications": weekly_notifications,
        "weekly_report_persistence": weekly_persistence,
    }


def _build_weekly_report_persistence_evidence(
    *,
    target_date: date,
    history: dict[str, Any],
    notifications: dict[str, Any],
) -> dict[str, Any]:
    target_report_date = target_date.isoformat()
    reports = list(history.get("reports") or [])
    notification_rows = list(notifications.get("notifications") or [])
    matched_report = next(
        (
            report
            for report in reports
            if str(report.get("report_date") or "") == target_report_date
        ),
        None,
    )
    matched_report_id = matched_report.get("id") if matched_report else None
    matched_notifications = [
        notification
        for notification in notification_rows
        if matched_report_id is not None and notification.get("report_id") == matched_report_id
    ]
    delivered_count = sum(
        1
        for notification in matched_notifications
        if str(notification.get("delivery_status") or "").lower() == "delivered"
    )

    compact_report = _compact_weekly_report_record(matched_report) if matched_report else None
    compact_notifications = [
        _compact_weekly_notification_record(notification)
        for notification in matched_notifications[:5]
    ]

    if matched_report is None:
        status = "warning"
        reason = f"no persisted weekly report found for {target_report_date}"
    elif delivered_count <= 0:
        status = "warning"
        reason = f"weekly report {matched_report_id} has no delivered notification"
    else:
        status = "ok"
        reason = "persisted weekly report and delivered notification found"

    return {
        "status": status,
        "target_report_date": target_report_date,
        "reason": reason,
        "history_status": history.get("status"),
        "history_count": history.get("count", len(reports)),
        "notification_status": notifications.get("status"),
        "notification_count": notifications.get("count", len(notification_rows)),
        "matched_report": compact_report,
        "matched_notification_count": len(matched_notifications),
        "delivered_notification_count": delivered_count,
        "matched_notifications": compact_notifications,
    }


def _compact_weekly_report_record(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": report.get("id"),
        "user_id": report.get("user_id"),
        "account_id": report.get("account_id"),
        "report_date": report.get("report_date"),
        "week_start": report.get("week_start"),
        "week_end": report.get("week_end"),
        "status": report.get("status"),
        "audit_log_id": report.get("audit_log_id"),
        "created_at": report.get("created_at"),
        "updated_at": report.get("updated_at"),
    }


def _compact_weekly_notification_record(notification: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": notification.get("id"),
        "report_id": notification.get("report_id"),
        "channel": notification.get("channel"),
        "delivery_status": notification.get("delivery_status"),
        "delivered_at": notification.get("delivered_at"),
        "created_at": notification.get("created_at"),
    }


def write_personal_readiness_evidence_files(
    *, payload: dict[str, Any], output_dir: Path
) -> dict[str, str]:
    root = Path(settings.BASE_DIR) / output_dir if not output_dir.is_absolute() else output_dir
    root.mkdir(parents=True, exist_ok=True)
    stem = f"{payload['target_date']}-personal-readiness"
    json_path = root / f"{stem}.json"
    markdown_path = root / f"{stem}.md"
    json_path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(_build_markdown(payload), encoding="utf-8")
    return {
        "json": str(json_path),
        "markdown": str(markdown_path),
    }


def _build_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    operation_context = payload.get("operation_context") or {}
    scheduler_evidence = payload.get("scheduler_evidence") or {}
    quote_pre_readiness = scheduler_evidence.get("quote_pre_readiness_scheduler") or {}
    quote_schedule = quote_pre_readiness.get("schedule") or {}
    quote_run_metadata = quote_pre_readiness.get("run_metadata") or {}
    decision_data = _resolve_decision_data_summary(payload=payload, summary=summary)
    macro_context = _resolve_macro_context_summary(payload=payload, summary=summary)
    alpha_workspace = _resolve_alpha_workspace_summary(payload=payload, summary=summary)
    lines = [
        f"# Personal Readiness Evidence - {payload.get('target_date')}",
        "",
        f"- status: {payload.get('status')}",
        f"- generated_at: {payload.get('generated_at')}",
        f"- mode: {operation_context.get('mode')}",
        f"- trigger_source: {operation_context.get('trigger_source')}",
        f"- trigger_task_name: {operation_context.get('trigger_task_name')}",
        f"- trigger_task_id: {operation_context.get('trigger_task_id')}",
        f"- target_date_closed: {operation_context.get('target_date_closed')}",
        f"- latest_closed_date: {operation_context.get('latest_closed_date')}",
        f"- allow_unclosed_target_date: {operation_context.get('allow_unclosed_target_date')}",
        f"- system_status: {summary.get('system_status')}",
        f"- qlib_status: {summary.get('qlib_status')}",
        f"- workspace_status: {summary.get('workspace_status')}",
        f"- quote_pre_readiness_scheduler_status: {quote_pre_readiness.get('status')}",
        f"- target_count: {summary.get('target_count')}",
        "",
        "## Scheduler Evidence",
        "",
        f"- quote_pre_readiness_enabled: {quote_pre_readiness.get('enabled')}",
        f"- quote_pre_readiness_schedule: {quote_schedule.get('hour')}:{quote_schedule.get('minute')} {quote_schedule.get('day_of_week')} {quote_schedule.get('timezone')}",
        f"- quote_pre_readiness_last_run_at: {quote_run_metadata.get('last_run_at')}",
        f"- quote_pre_readiness_total_run_count: {quote_run_metadata.get('total_run_count')}",
        "",
    ]
    if macro_context:
        _append_macro_context_markdown(lines=lines, macro_context=macro_context)
    if alpha_workspace:
        _append_alpha_workspace_markdown(lines=lines, alpha_workspace=alpha_workspace)
    if decision_data:
        _append_decision_data_markdown(lines=lines, decision_data=decision_data)
    lines.extend(["## Account Checks"])
    accounts = list(payload.get("accounts") or [])
    if not accounts:
        lines.append("")
        lines.append("- no account target discovered")
    for account in accounts:
        risk = account.get("risk_center_daily_report") or {}
        pre_trade = risk.get("pre_trade_check") or {}
        post_investment = risk.get("post_investment_check") or {}
        advisor = account.get("auto_advisor") or {}
        weekly_persistence = advisor.get("weekly_report_persistence") or {}
        lines.extend(
            [
                "",
                f"### Account {account.get('account_id')}",
                "",
                f"- status: {account.get('status')}",
                f"- user_id: {account.get('user_id')}",
                f"- risk_status: {risk.get('status')}",
                f"- risk_persisted: {risk.get('persisted')}",
                f"- risk_report_id: {risk.get('report_id')}",
                f"- pre_trade_status: {pre_trade.get('status')}",
                f"- post_investment_passed: {post_investment.get('passed')}",
                f"- advisor_status: {advisor.get('status')}",
                f"- weekly_persistence_status: {weekly_persistence.get('status')}",
                f"- weekly_persistence_report_id: {(weekly_persistence.get('matched_report') or {}).get('id')}",
                f"- weekly_delivered_notifications: {weekly_persistence.get('delivered_notification_count')}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _resolve_decision_data_summary(
    *, payload: dict[str, Any], summary: dict[str, Any]
) -> dict[str, Any]:
    summary_decision_data = summary.get("decision_data")
    if isinstance(summary_decision_data, dict) and summary_decision_data:
        return summary_decision_data
    evidence_summary = status_services.summarize_evidence_decision_data(payload)
    return evidence_summary or {}


def _resolve_macro_context_summary(
    *, payload: dict[str, Any], summary: dict[str, Any]
) -> dict[str, Any]:
    summary_macro_context = summary.get("macro_context")
    if isinstance(summary_macro_context, dict) and summary_macro_context:
        return summary_macro_context
    evidence_summary = status_services.summarize_evidence_macro_context(payload)
    return evidence_summary or {}


def _resolve_alpha_workspace_summary(
    *, payload: dict[str, Any], summary: dict[str, Any]
) -> dict[str, Any]:
    summary_alpha_workspace = summary.get("alpha_workspace_consistency")
    if isinstance(summary_alpha_workspace, dict) and summary_alpha_workspace:
        return summary_alpha_workspace
    evidence_summary = status_services.summarize_evidence_alpha_workspace(payload)
    return evidence_summary or {}


def _append_macro_context_markdown(
    *, lines: list[str], macro_context: dict[str, Any]
) -> None:
    regime = macro_context.get("regime") or {}
    pulse = macro_context.get("pulse") or {}
    warnings = ", ".join(str(item) for item in regime.get("warnings") or [])
    lines.extend(
        [
            "## Macro Context",
            "",
            f"- regime_status: {regime.get('status')}",
            f"- regime_observed_at: {regime.get('observed_at')}",
            f"- dominant_regime: {regime.get('dominant_regime')}",
            f"- regime_confidence: {regime.get('confidence')}",
            f"- regime_source: {regime.get('source')}",
            f"- regime_is_fallback: {regime.get('is_fallback')}",
            f"- regime_records_count: {regime.get('records_count')}",
            f"- regime_warnings: {warnings}",
            f"- pulse_status: {pulse.get('status')}",
            f"- pulse_observed_at: {pulse.get('observed_at')}",
            f"- pulse_regime_context: {pulse.get('regime_context')}",
            f"- pulse_composite_score: {pulse.get('composite_score')}",
            f"- pulse_regime_strength: {pulse.get('regime_strength')}",
            f"- pulse_transition_warning: {pulse.get('transition_warning')}",
            f"- pulse_transition_direction: {pulse.get('transition_direction')}",
            f"- pulse_stale_indicator_count: {pulse.get('stale_indicator_count')}",
            f"- pulse_data_source: {pulse.get('data_source')}",
            "",
        ]
    )


def _append_alpha_workspace_markdown(
    *, lines: list[str], alpha_workspace: dict[str, Any]
) -> None:
    alpha = alpha_workspace.get("alpha") or {}
    workspace = alpha_workspace.get("workspace") or {}
    issue_codes = ", ".join(str(item) for item in alpha_workspace.get("issue_codes") or [])
    top_codes = ", ".join(str(item) for item in alpha.get("top_codes") or [])
    recommendation_codes = ", ".join(
        str(item) for item in workspace.get("recommendation_codes") or []
    )
    lines.extend(
        [
            "## Alpha Workspace",
            "",
            f"- alpha_workspace_status: {alpha_workspace.get('status')}",
            f"- alpha_workspace_checked_account_id: {alpha_workspace.get('checked_account_id')}",
            f"- alpha_workspace_issue_codes: {issue_codes}",
            f"- alpha_latest_trade_date: {alpha.get('latest_trade_date')}",
            f"- alpha_latest_updated_at: {alpha.get('latest_updated_at')}",
            f"- alpha_provider_source: {alpha.get('provider_source')}",
            f"- alpha_status: {alpha.get('status')}",
            f"- alpha_top_codes: {top_codes}",
            f"- workspace_account_id: {workspace.get('account_id')}",
            f"- workspace_latest_updated_at: {workspace.get('latest_updated_at')}",
            f"- workspace_total_count: {workspace.get('total_count')}",
            f"- workspace_recommendation_codes: {recommendation_codes}",
            f"- workspace_source_candidate_id_count: {workspace.get('source_candidate_id_count')}",
            "",
        ]
    )


def _append_decision_data_markdown(
    *, lines: list[str], decision_data: dict[str, Any]
) -> None:
    thermometer = decision_data.get("market_thermometer") or {}
    skipped_latest = decision_data.get("skipped_latest_market_thermometer") or {}
    blocked_reasons = ", ".join(str(item) for item in decision_data.get("blocked_reasons") or [])
    stale_components = ", ".join(str(item) for item in thermometer.get("stale_components") or [])
    missing_components = ", ".join(str(item) for item in thermometer.get("missing_components") or [])
    lines.extend(
        [
            "## Decision Data",
            "",
            f"- decision_data_status: {decision_data.get('status')}",
            f"- decision_data_readiness_status: {decision_data.get('readiness_status')}",
            f"- decision_data_must_not_use: {decision_data.get('must_not_use_for_decision')}",
            f"- decision_data_blocked_reasons: {blocked_reasons}",
            f"- market_thermometer_status: {thermometer.get('status')}",
            f"- market_thermometer_observed_at: {thermometer.get('observed_at')}",
            f"- market_thermometer_data_source: {thermometer.get('data_source')}",
            f"- market_thermometer_blocked_reason: {thermometer.get('blocked_reason')}",
            f"- market_thermometer_stale_components: {stale_components}",
            f"- market_thermometer_missing_components: {missing_components}",
        ]
    )
    if skipped_latest:
        lines.extend(
            [
                f"- skipped_latest_market_thermometer_status: {skipped_latest.get('status')}",
                f"- skipped_latest_market_thermometer_observed_at: {skipped_latest.get('observed_at')}",
                f"- skipped_latest_market_thermometer_data_source: {skipped_latest.get('data_source')}",
                f"- skipped_latest_market_thermometer_skip_reason: {skipped_latest.get('skip_reason')}",
                f"- skipped_latest_market_thermometer_blocked_reason: {skipped_latest.get('blocked_reason')}",
            ]
        )
    lines.append("")


def _parse_date(value: Any) -> date:
    if not value:
        return resolve_default_readiness_target_date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError("target-date must be YYYY-MM-DD") from exc


def resolve_default_readiness_target_date() -> date:
    """Resolve the latest closed trading day for evidence collection."""

    return resolve_recent_closed_trade_date()


def _validate_target_date_is_closed(
    *,
    target_date: date,
    allow_unclosed_target_date: bool,
) -> None:
    if allow_unclosed_target_date:
        return
    latest_closed_date = resolve_default_readiness_target_date()
    if target_date <= latest_closed_date:
        return
    raise CommandError(
        f"target-date {target_date.isoformat()} is later than latest closed trading day "
        f"{latest_closed_date.isoformat()}; use --allow-unclosed-target-date only for "
        "diagnostics"
    )


def _rollup_status(statuses: list[str]) -> str:
    normalized = [status for status in statuses if status]
    if any(status == "error" for status in normalized):
        return "error"
    if any(status == "warning" for status in normalized):
        return "warning"
    if normalized and all(status == "skipped" for status in normalized):
        return "skipped"
    return "ok"


def _count_statuses(sections: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for section in sections:
        status = str(section.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _dedupe_targets(targets: list[dict[str, int]]) -> list[dict[str, int]]:
    seen: set[tuple[int, int]] = set()
    result: list[dict[str, int]] = []
    for target in targets:
        key = (int(target["user_id"]), int(target["account_id"]))
        if key in seen:
            continue
        seen.add(key)
        result.append(target)
    return result


def _optional_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
