"""Inspect one personal readiness evidence file for operational blockers."""

from __future__ import annotations

import json
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.task_monitor.management.auto_advisor_weekly_scheduler_status import (
    build_auto_advisor_weekly_due_status,
)
from apps.task_monitor.management.commands.validate_personal_readiness_window import (
    DEFAULT_OUTPUT_DIR,
    _evaluate_payload,
)


class Command(BaseCommand):
    help = "Inspect a personal readiness evidence JSON file and explain blockers."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--output-dir",
            default=DEFAULT_OUTPUT_DIR,
            help=f"Evidence directory. Default: {DEFAULT_OUTPUT_DIR}",
        )
        parser.add_argument(
            "--target-date",
            default=None,
            help="Evidence target date in YYYY-MM-DD format. Defaults to latest file.",
        )
        parser.add_argument(
            "--path",
            default=None,
            help="Inspect an explicit evidence JSON path instead of resolving by date.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit with CommandError when the evidence is not accepted.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="print_json",
            help="Print full JSON result.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        payload = inspect_personal_readiness_evidence(
            output_dir=Path(str(options["output_dir"])),
            target_date=_parse_date(options.get("target_date")),
            path=Path(str(options["path"])) if options.get("path") else None,
        )

        if options.get("print_json"):
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            evidence = payload["evidence"]
            acceptance = payload["acceptance"]
            self.stdout.write(
                self.style.SUCCESS(
                    "Personal readiness evidence: "
                    f"target={evidence.get('target_date')}, "
                    f"status={evidence.get('status')}, "
                    f"accepted={acceptance['accepted']}"
                )
            )
            if not acceptance["accepted"]:
                self.stdout.write(self.style.WARNING(f"  reason: {acceptance['reason']}"))
            for blocker in payload["blockers"][:10]:
                self.stdout.write(
                    self.style.WARNING(
                        "  {component}: {reason}".format(
                            component=blocker["component"],
                            reason=blocker["reason"],
                        )
                    )
                )
            for observation in payload["observations"][:5]:
                self.stdout.write(
                    "  note {component}: {reason}".format(
                        component=observation["component"],
                        reason=observation["reason"],
                    )
                )
            next_action = payload["next_action"]
            self.stdout.write(f"  next action: {next_action['action']}")
            if next_action.get("command"):
                self.stdout.write(f"  next command: {next_action['command']}")
            for action in payload["follow_up_actions"][:5]:
                self.stdout.write(
                    "  follow-up {action}: {reason}".format(
                        action=action["action"],
                        reason=action["reason"],
                    )
                )
                if action.get("command"):
                    self.stdout.write(f"  follow-up command: {action['command']}")

        if options.get("strict") and not payload["acceptance"]["accepted"]:
            raise CommandError(
                "Personal readiness evidence is not accepted: " f"{payload['acceptance']['reason']}"
            )


def inspect_personal_readiness_evidence(
    *,
    output_dir: Path,
    target_date: date | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Return a machine-readable inspection for one readiness evidence file."""

    evidence_path = _resolve_evidence_path(
        output_dir=output_dir,
        target_date=target_date,
        path=path,
    )
    evidence = _load_payload(evidence_path)
    accepted, reason = _evaluate_payload(evidence)
    findings = _collect_findings(evidence)
    blockers = findings["blockers"]
    observations = findings["observations"]
    target_date_text = str(evidence.get("target_date") or "")
    return {
        "status": "accepted" if accepted else "blocked",
        "path": str(evidence_path),
        "file": _build_file_fingerprint(evidence_path),
        "evidence": {
            "status": evidence.get("status"),
            "target_date": evidence.get("target_date"),
            "generated_at": evidence.get("generated_at"),
            "schema_version": evidence.get("schema_version"),
            "summary": dict(evidence.get("summary") or {}),
            "operation_context": dict(evidence.get("operation_context") or {}),
        },
        "acceptance": {
            "accepted": accepted,
            "reason": reason,
        },
        "blockers": blockers,
        "observations": observations,
        "next_action": _resolve_next_action(
            accepted=accepted,
            reason=reason,
            blockers=blockers,
            target_date=target_date_text,
        ),
        "follow_up_actions": _build_follow_up_actions(
            observations=observations,
            target_date=target_date_text,
        ),
    }


def _build_file_fingerprint(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CommandError(f"cannot read evidence file: {path}") from exc
    return {
        "path": str(path),
        "size_bytes": len(raw),
        "sha256": sha256(raw).hexdigest(),
    }


def _resolve_evidence_path(
    *,
    output_dir: Path,
    target_date: date | None,
    path: Path | None,
) -> Path:
    if path is not None:
        resolved = Path(settings.BASE_DIR) / path if not path.is_absolute() else path
        if not resolved.exists():
            raise CommandError(f"evidence file does not exist: {resolved}")
        return resolved

    root = Path(settings.BASE_DIR) / output_dir if not output_dir.is_absolute() else output_dir
    if target_date is not None:
        resolved = root / f"{target_date.isoformat()}-personal-readiness.json"
        if not resolved.exists():
            raise CommandError(f"evidence file does not exist: {resolved}")
        return resolved

    latest = _find_latest_evidence_file(root)
    if latest is None:
        raise CommandError(f"no readiness evidence JSON files found in {root}")
    return latest


def _find_latest_evidence_file(root: Path) -> Path | None:
    latest_path: Path | None = None
    latest_date: date | None = None
    for candidate in sorted(root.glob("*.json")):
        try:
            payload = _load_payload(candidate)
            candidate_date = date.fromisoformat(str(payload["target_date"]))
        except (CommandError, KeyError, TypeError, ValueError):
            continue
        if latest_date is None or candidate_date > latest_date:
            latest_date = candidate_date
            latest_path = candidate
    return latest_path


def _load_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CommandError(f"cannot read evidence file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CommandError(f"evidence file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise CommandError(f"evidence JSON root must be an object: {path}")
    return payload


def _collect_findings(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    current_decision_data = _load_current_decision_data_if_needed(payload=payload)
    _append_top_level_blockers(blockers=blockers, payload=payload)
    _append_operation_context_blockers(blockers=blockers, payload=payload)
    _append_operation_context_observations(observations=observations, payload=payload)
    _append_summary_blockers(blockers=blockers, payload=payload)
    _append_section_blockers(blockers=blockers, payload=payload)
    _append_qlib_blockers(blockers=blockers, payload=payload)
    _append_workspace_core_blockers(blockers=blockers, payload=payload)
    _append_alpha_workspace_blockers(blockers=blockers, payload=payload)
    _append_decision_data_blockers(blockers=blockers, payload=payload)
    _append_quote_freshness_blockers(blockers=blockers, payload=payload)
    _append_account_blockers(blockers=blockers, payload=payload)
    _append_risk_report_persistence_observations(observations=observations, payload=payload)
    _append_auto_advisor_persistence_observations(observations=observations, payload=payload)
    _append_degradation_observations(
        observations=observations,
        payload=payload,
        current_decision_data=current_decision_data,
    )
    return {
        "blockers": blockers,
        "observations": observations,
    }


def _append_top_level_blockers(
    *,
    blockers: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    status = payload.get("status")
    if status != "ok":
        blockers.append(
            {
                "component": "evidence",
                "status": status,
                "reason": f"overall status is {status or 'missing'}",
            }
        )


def _append_operation_context_blockers(
    *,
    blockers: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    operation_context = dict(payload.get("operation_context") or {})
    if not operation_context:
        return
    if operation_context.get("mode") != "formal":
        blockers.append(
            {
                "component": "operation_context",
                "status": operation_context.get("mode"),
                "reason": f"mode is {operation_context.get('mode')}",
            }
        )
    if operation_context.get("target_date_closed") is not True:
        blockers.append(
            {
                "component": "operation_context",
                "status": operation_context.get("target_date_closed"),
                "reason": "target_date_closed is not true",
            }
        )
    if operation_context.get("allow_unclosed_target_date") is True:
        blockers.append(
            {
                "component": "operation_context",
                "status": True,
                "reason": "allow_unclosed_target_date is true",
            }
        )


def _append_operation_context_observations(
    *,
    observations: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    operation_context = dict(payload.get("operation_context") or {})
    if operation_context:
        return
    observations.append(
        {
            "component": "operation_context",
            "status": "legacy",
            "reason": "operation_context is missing; accepted only as legacy evidence",
        }
    )


def _append_summary_blockers(
    *,
    blockers: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    summary = dict(payload.get("summary") or {})
    for key in ["system_status", "qlib_status", "workspace_status"]:
        status = summary.get(key)
        if status != "ok":
            blockers.append(
                {
                    "component": f"summary.{key}",
                    "status": status,
                    "reason": f"{key} is {status or 'missing'}",
                }
            )
    if int(summary.get("target_count") or 0) <= 0:
        blockers.append(
            {
                "component": "summary.target_count",
                "status": summary.get("target_count"),
                "reason": "target_count is zero",
            }
        )


def _append_section_blockers(
    *,
    blockers: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    for section_name in ["system", "qlib", "workspace"]:
        section = dict(payload.get(section_name) or {})
        status = section.get("status")
        if status in (None, "ok"):
            continue
        blockers.append(
            {
                "component": section_name,
                "status": status,
                "reason": (
                    section.get("error")
                    or section.get("reason")
                    or f"{section_name} status is {status}"
                ),
            }
        )


def _append_qlib_blockers(
    *,
    blockers: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    if not payload.get("operation_context"):
        return
    qlib = payload.get("qlib")
    if not isinstance(qlib, dict):
        blockers.append(
            {
                "component": "qlib",
                "status": "missing",
                "reason": "qlib readiness evidence is missing",
            }
        )
        return
    if qlib.get("status") != "ok":
        return
    if qlib.get("check_only") is not True:
        blockers.append(
            {
                "component": "qlib",
                "status": "not_check_only",
                "reason": "qlib readiness evidence was not collected with check_only",
            }
        )


def _append_decision_data_blockers(
    *,
    blockers: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    if not payload.get("operation_context"):
        return
    system = dict(payload.get("system") or {})
    checks = dict(system.get("checks") or {})
    decision_data = checks.get("decision_data")
    if not isinstance(decision_data, dict):
        blockers.append(
            {
                "component": "decision_data",
                "status": "missing",
                "reason": "decision_data readiness evidence is missing",
            }
        )
        return

    if decision_data.get("status") != "ok":
        blockers.append(
            {
                "component": "decision_data",
                "status": decision_data.get("status"),
                "reason": f"decision_data status is {decision_data.get('status') or 'missing'}",
            }
        )
    if decision_data.get("readiness_status") != "ok":
        blockers.append(
            {
                "component": "decision_data",
                "status": decision_data.get("readiness_status"),
                "reason": (
                    "decision_data readiness_status is "
                    f"{decision_data.get('readiness_status') or 'missing'}"
                ),
            }
        )
    if decision_data.get("must_not_use_for_decision") is True:
        blockers.append(
            {
                "component": "decision_data",
                "status": "blocked",
                "reason": "decision_data must_not_use_for_decision is true",
            }
        )


def _append_quote_freshness_blockers(
    *,
    blockers: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    if not payload.get("operation_context"):
        return
    system = dict(payload.get("system") or {})
    checks = dict(system.get("checks") or {})
    decision_data = checks.get("decision_data")
    if not isinstance(decision_data, dict):
        return
    quotes = decision_data.get("quotes")
    if not isinstance(quotes, dict) or not quotes:
        blockers.append(
            {
                "component": "decision_data.quotes",
                "status": "missing",
                "reason": "decision quote freshness evidence is missing",
            }
        )
        return

    stale_assets = []
    blocked_assets = []
    for asset_code, quote in quotes.items():
        if not isinstance(quote, dict):
            blocked_assets.append(str(asset_code))
            continue
        if quote.get("must_not_use_for_decision") is True or quote.get("status") != "ok":
            blocked_assets.append(str(asset_code))
            continue
        freshness_status = str(quote.get("freshness_status") or "").lower()
        if quote.get("is_stale") is True or (
            freshness_status and freshness_status not in {"fresh", "ok"}
        ):
            stale_assets.append(str(asset_code))

    if blocked_assets:
        blockers.append(
            {
                "component": "decision_data.quotes",
                "status": "blocked",
                "reason": f"decision quotes blocked: {','.join(blocked_assets)}",
            }
        )
    if stale_assets:
        blockers.append(
            {
                "component": "decision_data.quotes",
                "status": "stale",
                "reason": f"decision quotes stale: {','.join(stale_assets)}",
            }
        )


def _append_alpha_workspace_blockers(
    *,
    blockers: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    if not payload.get("operation_context"):
        return
    system = dict(payload.get("system") or {})
    checks = dict(system.get("checks") or {})
    alpha_workspace = checks.get("alpha_workspace_consistency")
    if not isinstance(alpha_workspace, dict):
        blockers.append(
            {
                "component": "alpha_workspace_consistency",
                "status": "missing",
                "reason": "alpha_workspace_consistency evidence is missing",
            }
        )
        return

    if alpha_workspace.get("status") != "ok":
        blockers.append(
            {
                "component": "alpha_workspace_consistency",
                "status": alpha_workspace.get("status"),
                "reason": (
                    "alpha_workspace_consistency status is "
                    f"{alpha_workspace.get('status') or 'missing'}"
                ),
            }
        )


def _append_workspace_core_blockers(
    *,
    blockers: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    if not payload.get("operation_context"):
        return
    workspace = dict(payload.get("workspace") or {})
    result = dict(workspace.get("result") or {})
    components = dict(result.get("components") or {})
    if not components:
        blockers.append(
            {
                "component": "workspace.core",
                "status": "missing",
                "reason": "workspace core evidence status is missing",
            }
        )
        return

    status = _workspace_core_status(components)
    if status != "ok":
        blockers.append(
            {
                "component": "workspace.core",
                "status": status,
                "reason": f"workspace core evidence status is {status}",
            }
        )


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


def _append_account_blockers(
    *,
    blockers: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    requires_pre_trade = bool(payload.get("operation_context"))
    accounts = list(payload.get("accounts") or [])
    if not accounts:
        blockers.append(
            {
                "component": "accounts",
                "status": "missing",
                "reason": "accounts evidence is missing",
            }
        )
        return

    for account in accounts:
        account_id = account.get("account_id") or "-"
        account_status = account.get("status")
        if account_status != "ok":
            blockers.append(
                {
                    "component": "account",
                    "account_id": account_id,
                    "status": account_status,
                    "reason": f"account {account_id} status is {account_status}",
                }
            )
        risk = dict(account.get("risk_center_daily_report") or {})
        risk_status = risk.get("status")
        if risk_status != "ok":
            blockers.append(
                {
                    "component": "risk_center_daily_report",
                    "account_id": account_id,
                    "status": risk_status,
                    "reason": (
                        risk.get("error")
                        or risk.get("reason")
                        or f"account {account_id} risk status is {risk_status}"
                    ),
                }
            )
        if requires_pre_trade:
            pre_trade = dict(risk.get("pre_trade_check") or {})
            pre_trade_status = pre_trade.get("status")
            if pre_trade_status != "ok":
                blockers.append(
                    {
                        "component": "risk_center_pre_trade_check",
                        "account_id": account_id,
                        "status": pre_trade_status,
                        "reason": (
                            pre_trade.get("error")
                            or pre_trade.get("reason")
                            or f"account {account_id} pre-trade risk status is "
                            f"{pre_trade_status or 'missing'}"
                        ),
                    }
                )
            post_investment = dict(risk.get("post_investment_check") or {})
            if post_investment.get("passed") is not True:
                blockers.append(
                    {
                        "component": "risk_center_post_investment_check",
                        "account_id": account_id,
                        "status": post_investment.get("passed"),
                        "reason": (
                            post_investment.get("error")
                            or post_investment.get("reason")
                            or f"account {account_id} post-investment risk passed is "
                            f"{post_investment.get('passed')}"
                        ),
                    }
                )
        advisor = dict(account.get("auto_advisor") or {})
        advisor_status = advisor.get("status")
        if advisor_status != "ok":
            blockers.append(
                {
                    "component": "auto_advisor",
                    "account_id": account_id,
                    "status": advisor_status,
                    "reason": (
                        advisor.get("console_error")
                        or advisor.get("weekly_report_error")
                        or f"account {account_id} advisor status is {advisor_status}"
                    ),
                }
            )


def _append_risk_report_persistence_observations(
    *,
    observations: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    if not payload.get("operation_context"):
        return
    for account in payload.get("accounts") or []:
        account_id = account.get("account_id")
        risk = dict(account.get("risk_center_daily_report") or {})
        if risk.get("status") != "ok":
            continue
        if risk.get("report_id") not in (None, ""):
            continue
        observations.append(
            {
                "component": "risk_center_daily_report_persistence",
                "account_id": account_id,
                "status": "missing",
                "reason": f"account {account_id} risk report is ok but has no persisted report_id",
            }
        )


def _append_auto_advisor_persistence_observations(
    *,
    observations: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    due_status = _resolve_weekly_due_status(payload=payload)
    for account in payload.get("accounts") or []:
        account_id = account.get("account_id")
        advisor = dict(account.get("auto_advisor") or {})
        if advisor.get("weekly_report") is None:
            continue
        persistence = dict(advisor.get("weekly_report_persistence") or {})
        persistence_status = persistence.get("status")
        if persistence_status == "ok":
            continue
        if due_status.get("due") is not True:
            observations.append(
                {
                    "component": "auto_advisor_weekly_persistence",
                    "account_id": account_id,
                    "status": "not_due",
                    "reason": due_status.get("reason"),
                    "scheduled_for": due_status.get("scheduled_for"),
                    "next_scheduled_for": due_status.get("next_scheduled_for"),
                }
            )
            continue
        observations.append(
            {
                "component": "auto_advisor_weekly_persistence",
                "account_id": account_id,
                "status": persistence_status or "missing",
                "reason": (
                    persistence.get("reason")
                    or f"account {account_id} weekly report persistence evidence is missing"
                ),
            }
        )


def _build_follow_up_actions(
    *,
    observations: list[dict[str, Any]],
    target_date: str,
) -> list[dict[str, Any]]:
    risk_account_ids = sorted(
        {
            observation.get("account_id")
            for observation in observations
            if observation.get("component") == "risk_center_daily_report_persistence"
            and observation.get("account_id") not in (None, "")
        },
        key=str,
    )
    weekly_account_ids = sorted(
        {
            observation.get("account_id")
            for observation in observations
            if observation.get("component") == "auto_advisor_weekly_persistence"
            and observation.get("status") != "not_due"
            and observation.get("account_id") not in (None, "")
        },
        key=str,
    )
    actions: list[dict[str, Any]] = []
    if risk_account_ids:
        actions.append(
            {
                "component": "risk_center_daily_report_persistence",
                "action": "verify_scheduled_risk_report_persistence",
                "reason": (
                    "risk reports are accepted but not persisted; final readiness "
                    "acceptance requires report_id coverage"
                ),
                "target_date": target_date or None,
                "account_ids": risk_account_ids,
                "command": "python manage.py show_personal_readiness_status --json --strict-monitor",
            }
        )
    if weekly_account_ids:
        actions.append(
            {
                "component": "auto_advisor_weekly_persistence",
                "action": "verify_scheduled_weekly_report_persistence",
                "reason": (
                    "weekly advisor output is present but persistence proof is "
                    "missing or warning; final readiness acceptance requires "
                    "scheduled weekly report persistence"
                ),
                "target_date": target_date or None,
                "account_ids": weekly_account_ids,
                "command": "python manage.py show_personal_readiness_status --json --strict-monitor",
            }
        )
    if _has_unresolved_component(
        observations=observations,
        component="workspace.macro_sync",
    ):
        actions.append(
            {
                "component": "workspace.macro_sync",
                "action": "repair_decision_data_reliability",
                "reason": (
                    "macro sync skipped inputs; repair decision-grade data before "
                    "the next formal readiness run"
                ),
                "target_date": target_date or None,
                "command": (
                    "python manage.py repair_decision_data_reliability "
                    f"--target-date {target_date} --strict"
                ),
            }
        )
    if (
        _has_unresolved_component(
            observations=observations,
            component="decision_data.market_thermometer",
        )
        or _has_unresolved_component(
            observations=observations,
            component="decision_data.skipped_latest_market_thermometer",
        )
    ):
        actions.append(
            {
                "component": "decision_data.market_thermometer",
                "action": "refresh_market_thermometer",
                "reason": (
                    "market thermometer evidence is degraded or skipped; sync inputs "
                    "and recalculate the snapshot"
                ),
                "target_date": target_date or None,
                "command": (
                    "python manage.py calculate_market_thermometer "
                    f"--as-of-date {target_date} --json"
                ),
            }
        )
    return actions


def _has_unresolved_component(
    *,
    observations: list[dict[str, Any]],
    component: str,
) -> bool:
    return any(
        observation.get("component") == component
        and observation.get("status") != "resolved_after_evidence"
        for observation in observations
    )


def _resolve_current_macro_sync_resolution(*, target_date: str) -> dict[str, Any] | None:
    try:
        asof_date = date.fromisoformat(target_date)
    except ValueError:
        return None

    try:
        from apps.data_center.application.dtos import MacroSeriesRequest
        from apps.data_center.application.repository_provider import (
            IndicatorCatalogRepository,
            IndicatorUnitRuleRepository,
            MacroFactRepository,
            PublisherCatalogRepository,
        )
        from apps.data_center.application.use_cases import (
            DEFAULT_DECISION_MACRO_INDICATORS,
            QueryMacroSeriesUseCase,
        )

        query = QueryMacroSeriesUseCase(
            fact_repo=MacroFactRepository(),
            catalog_repo=IndicatorCatalogRepository(),
            unit_rule_repo=IndicatorUnitRuleRepository(),
            publisher_repo=PublisherCatalogRepository(),
        )
        indicators: dict[str, dict[str, Any]] = {}
        blocked: list[str] = []
        for indicator_code in DEFAULT_DECISION_MACRO_INDICATORS:
            response = query.execute(
                MacroSeriesRequest(
                    indicator_code=indicator_code,
                    start=asof_date - timedelta(days=180),
                    end=asof_date,
                    limit=500,
                )
            )
            contract = response.to_dict().get("contract") or {}
            indicator_status = {
                "freshness_status": contract.get("freshness_status"),
                "decision_grade": contract.get("decision_grade"),
                "must_not_use_for_decision": contract.get("must_not_use_for_decision"),
                "latest_reporting_period": contract.get("latest_reporting_period"),
                "latest_published_at": contract.get("latest_published_at"),
                "provenance_class": contract.get("provenance_class"),
                "publisher_code": contract.get("publisher_code"),
            }
            indicators[indicator_code] = indicator_status
            if (
                indicator_status["must_not_use_for_decision"] is True
                or indicator_status["decision_grade"] != "decision_safe"
            ):
                blocked.append(indicator_code)
    except Exception:
        return None

    if blocked:
        return None
    return {
        "status": "ready",
        "decision_grade": "decision_safe",
        "indicator_count": len(indicators),
        "indicators": indicators,
    }


def _load_current_decision_data_if_needed(*, payload: dict[str, Any]) -> dict[str, Any] | None:
    system = dict(payload.get("system") or {})
    checks = dict(system.get("checks") or {})
    decision_data = dict(checks.get("decision_data") or {})
    thermometer = dict(decision_data.get("market_thermometer") or {})
    skipped_latest = dict(decision_data.get("skipped_latest_market_thermometer") or {})
    if not (
        thermometer.get("data_source") == "degraded"
        or thermometer.get("stale_components")
        or thermometer.get("missing_components")
        or skipped_latest
    ):
        return None
    try:
        from apps.task_monitor.application.readiness_status_services import (
            build_current_decision_data_from_settings,
        )

        return build_current_decision_data_from_settings()
    except Exception:
        return None


def _resolve_current_market_thermometer_resolution(
    *,
    current_decision_data: dict[str, Any] | None,
    target_date: str,
) -> dict[str, Any] | None:
    current = dict(current_decision_data or {})
    thermometer = dict(current.get("market_thermometer") or {})
    if not thermometer or str(thermometer.get("observed_at") or "") != target_date:
        return None
    if thermometer.get("must_not_use_for_decision") is True:
        return None
    if thermometer.get("stale_components") or thermometer.get("missing_components"):
        return None
    return {
        "observed_at": thermometer.get("observed_at"),
        "status": thermometer.get("status"),
        "data_source": thermometer.get("data_source"),
        "valid_component_count": thermometer.get("valid_component_count"),
        "proxy_components": list(thermometer.get("proxy_components") or []),
    }


def _resolve_weekly_due_status(*, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        target_date = date.fromisoformat(str(payload.get("target_date") or ""))
    except ValueError:
        return {
            "due": True,
            "reason": "evidence_target_date_unparseable",
            "scheduled_for": None,
        }
    return build_auto_advisor_weekly_due_status(target_date=target_date)


def _append_degradation_observations(
    *,
    observations: list[dict[str, Any]],
    payload: dict[str, Any],
    current_decision_data: dict[str, Any] | None,
) -> None:
    """Append non-blocking yellow items that should remain visible during trials."""

    workspace = dict(payload.get("workspace") or {})
    workspace_result = dict(workspace.get("result") or {})
    workspace_components = dict(workspace_result.get("components") or {})

    macro_sync = dict(workspace_components.get("macro_sync") or {})
    skipped_count = int(macro_sync.get("skipped_count") or 0)
    if skipped_count > 0:
        target_date = str(payload.get("target_date") or "")
        current_resolution = _resolve_current_macro_sync_resolution(target_date=target_date)
        observations.append(
            {
                "component": "workspace.macro_sync",
                "status": "resolved_after_evidence" if current_resolution else "degraded",
                "reason": (
                    f"macro sync skipped {skipped_count} indicator(s) "
                    f"after syncing {int(macro_sync.get('synced_count') or 0)}"
                ),
                **({"current_status": current_resolution} if current_resolution else {}),
            }
        )

    rotation_signals = dict(workspace_components.get("rotation_signals") or {})
    rotation_skipped = int(rotation_signals.get("skipped") or 0)
    if rotation_skipped > 0:
        observations.append(
            {
                "component": "workspace.rotation_signals",
                "status": "degraded",
                "reason": (
                    f"rotation signal generation skipped {rotation_skipped} config(s); "
                    f"successful={int(rotation_signals.get('successful') or 0)}, "
                    f"failed={int(rotation_signals.get('failed') or 0)}"
                ),
            }
        )

    system = dict(payload.get("system") or {})
    checks = dict(system.get("checks") or {})
    decision_data = dict(checks.get("decision_data") or {})
    thermometer = dict(decision_data.get("market_thermometer") or {})
    stale_components = list(thermometer.get("stale_components") or [])
    missing_components = list(thermometer.get("missing_components") or [])
    target_date = str(payload.get("target_date") or "")
    current_resolution = _resolve_current_market_thermometer_resolution(
        current_decision_data=current_decision_data,
        target_date=target_date,
    )
    if thermometer.get("data_source") == "degraded" or stale_components or missing_components:
        parts = []
        if thermometer.get("data_source"):
            parts.append(f"source={thermometer.get('data_source')}")
        if stale_components:
            parts.append(f"stale={','.join(str(item) for item in stale_components)}")
        if missing_components:
            parts.append(f"missing={','.join(str(item) for item in missing_components)}")
        observation = {
            "component": "decision_data.market_thermometer",
            "status": "resolved_after_evidence" if current_resolution else "degraded",
            "reason": "; ".join(parts),
        }
        if current_resolution:
            observation["current_status"] = current_resolution
        observations.append(observation)

    skipped_latest = dict(decision_data.get("skipped_latest_market_thermometer") or {})
    if skipped_latest:
        observation = {
            "component": "decision_data.skipped_latest_market_thermometer",
            "status": (
                "resolved_after_evidence"
                if current_resolution
                else skipped_latest.get("status") or "blocked"
            ),
            "reason": (
                f"latest thermometer snapshot {skipped_latest.get('observed_at') or '-'} "
                f"was skipped: {skipped_latest.get('blocked_reason') or 'blocked'}"
            ),
        }
        if current_resolution:
            observation["current_status"] = current_resolution
        observations.append(observation)


def _resolve_next_action(
    *,
    accepted: bool,
    reason: str,
    blockers: list[dict[str, Any]],
    target_date: str,
) -> dict[str, Any]:
    if accepted:
        return {
            "action": "continue_window",
            "reason": "evidence_accepted",
            "command": "python manage.py show_personal_readiness_status --json",
        }
    components = {str(blocker.get("component") or "") for blocker in blockers}
    if "accounts" in components or any(component == "account" for component in components):
        return {
            "action": "repair_accounts_then_rerun",
            "reason": reason,
            "command": (
                "python manage.py run_personal_readiness_daily "
                f"--target-date {target_date} --repair-accounts --json"
            ),
        }
    if "summary.qlib_status" in components or "qlib" in components:
        return {
            "action": "refresh_qlib_then_rerun",
            "reason": reason,
            "command": ("python manage.py build_qlib_data " f"--target-date {target_date}"),
        }
    return {
        "action": "inspect_subsystem_then_rerun",
        "reason": reason,
        "command": (
            "python manage.py run_personal_readiness_daily " f"--target-date {target_date} --json"
        ),
    }


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError("target-date must be YYYY-MM-DD") from exc
