"""Run the daily personal investment readiness pipeline."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from importlib import import_module
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.operational_readiness.management.commands.collect_personal_readiness_evidence import (
    DEFAULT_OUTPUT_DIR,
    collect_personal_readiness_evidence,
    write_personal_readiness_evidence_files,
)
from apps.operational_readiness.management.commands.validate_personal_readiness_window import (
    DEFAULT_CALENDAR_SOURCE,
    DEFAULT_REQUIRED_DAYS,
    validate_personal_readiness_window,
)


class Command(BaseCommand):
    help = "Run account preflight, daily evidence collection, and window validation."
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
        parser.add_argument("--user-id", type=int, default=None, help="Restrict to one user.")
        parser.add_argument(
            "--account-id",
            type=int,
            default=None,
            help="Restrict to one account.",
        )
        parser.add_argument(
            "--output-dir",
            default=DEFAULT_OUTPUT_DIR,
            help=f"Directory for evidence files. Default: {DEFAULT_OUTPUT_DIR}",
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
            help="Trading calendar source for window validation. Default: auto.",
        )
        parser.add_argument(
            "--max-qlib-staleness-days",
            type=int,
            default=5,
            help="Allowed Qlib freshness lag for build_qlib_data --check-only.",
        )
        parser.add_argument(
            "--initial-capital",
            default="1000000.00",
            help="Initial cash for created readiness simulated accounts.",
        )
        parser.add_argument(
            "--repair-accounts",
            action="store_true",
            help="Create missing readiness simulated accounts before collecting evidence.",
        )
        parser.add_argument(
            "--skip-workspace-refresh",
            action="store_true",
            help="Do not run the Regime/Pulse/Rotation workspace refresh.",
        )
        parser.add_argument(
            "--skip-weekly-advisor",
            action="store_true",
            help="Do not generate the weekly auto-advisor payload.",
        )
        parser.add_argument(
            "--persist-risk-report",
            action="store_true",
            help="Persist generated risk-center daily reports.",
        )
        parser.add_argument(
            "--strict-daily",
            action="store_true",
            help="Exit with CommandError when today's pipeline status is not ok.",
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
            "--json",
            action="store_true",
            dest="print_json",
            help="Print full JSON result.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        target_date = _parse_date(options.get("target_date"))
        _validate_target_date_is_closed(
            target_date=target_date,
            allow_unclosed_target_date=bool(options.get("allow_unclosed_target_date")),
        )

        payload = run_personal_readiness_daily(
            target_date=target_date,
            user_id=options.get("user_id"),
            account_id=options.get("account_id"),
            output_dir=Path(str(options["output_dir"])),
            required_days=int(options["required_days"]),
            calendar_source=str(options["calendar_source"]),
            max_qlib_staleness_days=int(options["max_qlib_staleness_days"]),
            initial_capital=_parse_capital(options["initial_capital"]),
            repair_accounts=bool(options.get("repair_accounts")),
            run_workspace_refresh=not bool(options.get("skip_workspace_refresh")),
            include_weekly_advisor=not bool(options.get("skip_weekly_advisor")),
            persist_risk_report=bool(options.get("persist_risk_report")),
            allow_unclosed_target_date=bool(options.get("allow_unclosed_target_date")),
            trigger_source=str(options.get("trigger_source") or "manual"),
            trigger_task_id=options.get("trigger_task_id"),
            trigger_task_name=options.get("trigger_task_name"),
        )

        if options.get("print_json"):
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            validation = payload["validation"]
            evidence = payload["evidence"]
            self.stdout.write(
                self.style.SUCCESS(
                    "Personal readiness daily run: "
                    f"status={payload['status']}, "
                    f"evidence={evidence.get('status')}, "
                    f"window={validation['accepted_days']}/{validation['required_days']}, "
                    f"remaining={validation['remaining_days']}"
                )
            )
            if payload.get("evidence_output_paths"):
                paths = payload["evidence_output_paths"]
                self.stdout.write(f"  json: {paths.get('json')}")
                self.stdout.write(f"  markdown: {paths.get('markdown')}")

        if options.get("strict_daily") and payload["status"] != "ok":
            raise CommandError(f"Personal readiness daily run is {payload['status']}")


def run_personal_readiness_daily(
    *,
    target_date: date,
    user_id: int | None,
    account_id: int | None,
    output_dir: Path,
    required_days: int = DEFAULT_REQUIRED_DAYS,
    calendar_source: str = DEFAULT_CALENDAR_SOURCE,
    max_qlib_staleness_days: int = 5,
    initial_capital: Decimal = Decimal("1000000.00"),
    repair_accounts: bool = False,
    run_workspace_refresh: bool = True,
    include_weekly_advisor: bool = True,
    persist_risk_report: bool = False,
    allow_unclosed_target_date: bool = False,
    trigger_source: str = "manual",
    trigger_task_id: str | None = None,
    trigger_task_name: str | None = None,
) -> dict[str, Any]:
    """Run the full daily readiness workflow used by the acceptance window."""

    account_repair = repair_personal_account_readiness(
        AccountReadinessRepairRequest(
            user_id=user_id,
            account_id=account_id,
            initial_capital=initial_capital,
            dry_run=not repair_accounts,
        )
    )
    repair_status = str(account_repair.get("status") or "unknown")

    evidence_output_paths: dict[str, str] = {}
    if repair_status in {"action_required", "error"}:
        evidence: dict[str, Any] = {
            "status": "skipped",
            "reason": f"account_readiness_{repair_status}",
            "target_date": target_date.isoformat(),
        }
    else:
        evidence = collect_personal_readiness_evidence(
            target_date=target_date,
            user_id=user_id,
            account_id=account_id,
            max_qlib_staleness_days=max_qlib_staleness_days,
            run_workspace_refresh=run_workspace_refresh,
            include_weekly_advisor=include_weekly_advisor,
            persist_risk_report=persist_risk_report,
            allow_unclosed_target_date=allow_unclosed_target_date,
            trigger_source=trigger_source,
            trigger_task_id=trigger_task_id,
            trigger_task_name=trigger_task_name,
        )
        evidence_output_paths = write_personal_readiness_evidence_files(
            payload=evidence,
            output_dir=output_dir,
        )

    validation = validate_personal_readiness_window(
        output_dir=output_dir,
        required_days=required_days,
        calendar_source=calendar_source,
        expected_latest_date=target_date,
    )
    status = _rollup_daily_status(
        repair_status=repair_status,
        evidence_status=str(evidence.get("status") or "unknown"),
        validation=validation,
    )

    return {
        "status": status,
        "target_date": target_date.isoformat(),
        "inputs": {
            "user_id": user_id,
            "account_id": account_id,
            "output_dir": str(output_dir),
            "required_days": required_days,
            "calendar_source": calendar_source,
            "max_qlib_staleness_days": max_qlib_staleness_days,
            "initial_capital": str(initial_capital),
            "repair_accounts": repair_accounts,
            "run_workspace_refresh": run_workspace_refresh,
            "include_weekly_advisor": include_weekly_advisor,
            "persist_risk_report": persist_risk_report,
            "allow_unclosed_target_date": allow_unclosed_target_date,
            "trigger_source": trigger_source,
            "trigger_task_id": trigger_task_id,
            "trigger_task_name": trigger_task_name,
        },
        "account_readiness": account_repair,
        "evidence": evidence,
        "evidence_output_paths": evidence_output_paths,
        "validation": validation,
    }


def _rollup_daily_status(
    *,
    repair_status: str,
    evidence_status: str,
    validation: dict[str, Any],
) -> str:
    if repair_status == "error" or evidence_status == "error":
        return "error"
    if repair_status == "action_required":
        return "action_required"
    if evidence_status in {"warning", "skipped"}:
        return "warning"
    if validation.get("blocking_issues"):
        return "warning"
    return "ok"


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
    """Resolve the latest closed trading day for scheduled readiness runs."""

    return resolve_recent_closed_trade_date()


def resolve_recent_closed_trade_date() -> date:
    """Resolve Alpha's closed-trade-date helper without a static app dependency."""

    module = import_module("apps.alpha.application.trade_dates")
    return module.resolve_recent_closed_trade_date()


def AccountReadinessRepairRequest(**kwargs: Any) -> Any:
    """Build the simulated-trading account readiness request at runtime."""

    module = import_module("apps.simulated_trading.application.readiness_services")
    return module.AccountReadinessRepairRequest(**kwargs)


def repair_personal_account_readiness(request: Any) -> dict[str, Any]:
    """Run simulated-trading account readiness repair without a static dependency."""

    module = import_module("apps.simulated_trading.application.readiness_services")
    return module.repair_personal_account_readiness(request)


def _validate_target_date_is_closed(
    *,
    target_date: date,
    allow_unclosed_target_date: bool,
) -> None:
    """Reject formal evidence runs for trading days that have not closed yet."""

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


def _parse_capital(value: Any) -> Decimal:
    try:
        capital = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CommandError("initial-capital must be a positive decimal") from exc
    if capital <= 0:
        raise CommandError("initial-capital must be positive")
    return capital
