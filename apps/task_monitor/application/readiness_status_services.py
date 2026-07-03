"""Pure helpers for personal readiness status calculations."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

MAX_SCHEDULED_QLIB_STALENESS_DAYS = 5


def summarize_evidence_decision_data(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return a compact decision-data summary from one readiness evidence payload."""

    system = _as_dict(payload.get("system"))
    checks = _as_dict(system.get("checks"))
    decision_data = _as_dict(checks.get("decision_data"))
    if not decision_data:
        return None

    return summarize_decision_data(decision_data)


def summarize_decision_data(decision_data: dict[str, Any]) -> dict[str, Any] | None:
    """Return a compact operator-facing decision-data summary."""

    if not decision_data:
        return None

    thermometer = _as_dict(decision_data.get("market_thermometer"))
    skipped_latest = _as_dict(decision_data.get("skipped_latest_market_thermometer"))
    component_details = _summarize_thermometer_component_details(thermometer)
    summary = {
        "status": decision_data.get("status"),
        "readiness_status": decision_data.get("readiness_status") or decision_data.get("status"),
        "must_not_use_for_decision": decision_data.get("must_not_use_for_decision"),
        "blocked_reasons": list(decision_data.get("blocked_reasons") or []),
        "market_thermometer": {
            "status": thermometer.get("status"),
            "observed_at": thermometer.get("observed_at"),
            "data_source": thermometer.get("data_source"),
            "must_not_use_for_decision": thermometer.get("must_not_use_for_decision"),
            "blocked_reason": thermometer.get("blocked_reason"),
            "stale_components": list(thermometer.get("stale_components") or []),
            "missing_components": list(thermometer.get("missing_components") or []),
            "proxy_components": list(thermometer.get("proxy_components") or []),
            "component_data_provenance": list(
                thermometer.get("component_data_provenance") or []
            ),
            "component_details": component_details,
            "stale_component_details": [
                item for item in component_details if item.get("is_stale") is True
            ],
            "missing_component_details": [
                item for item in component_details if item.get("is_missing") is True
            ],
            "valid_component_count": thermometer.get("valid_component_count"),
        },
    }
    if skipped_latest:
        summary["skipped_latest_market_thermometer"] = {
            "status": skipped_latest.get("status"),
            "observed_at": skipped_latest.get("observed_at"),
            "data_source": skipped_latest.get("data_source"),
            "must_not_use_for_decision": skipped_latest.get("must_not_use_for_decision"),
            "blocked_reason": skipped_latest.get("blocked_reason"),
            "skip_reason": skipped_latest.get("skip_reason"),
        }
    return summary


def build_current_decision_data(
    *,
    asset_codes: list[str],
    quote_max_age_hours: float,
) -> dict[str, Any] | None:
    """Return current decision-data readiness for operator-facing status output."""

    try:
        from apps.data_center.application.interface_services import (
            get_decision_data_readiness_payload,
        )

        payload = get_decision_data_readiness_payload(
            asset_codes=asset_codes,
            quote_max_age_hours=quote_max_age_hours,
        )
    except Exception as exc:
        return {
            "status": "error",
            "readiness_status": "error",
            "must_not_use_for_decision": True,
            "blocked_reasons": [str(exc)],
            "market_thermometer": {"status": "error", "blocked_reason": str(exc)},
        }
    return summarize_decision_data(payload)


def build_current_decision_data_from_settings() -> dict[str, Any] | None:
    """Return current decision-data readiness using configured readiness assets."""

    from django.conf import settings

    return build_current_decision_data(
        asset_codes=list(getattr(settings, "DECISION_READINESS_ASSET_CODES", [])),
        quote_max_age_hours=float(getattr(settings, "DECISION_QUOTE_MAX_AGE_HOURS", 4.0)),
    )


def build_account_readiness_summary() -> dict[str, Any]:
    """Return read-only account readiness for operator-facing status output."""

    from apps.simulated_trading.application.readiness_services import (
        AccountReadinessRepairRequest,
        repair_personal_account_readiness,
    )

    payload = repair_personal_account_readiness(AccountReadinessRepairRequest(dry_run=True))
    results = list(payload.get("results") or [])
    decision_ready_account_ids = [
        int(account_id)
        for result in results
        for account_id in result.get("decision_ready_account_ids") or []
    ]
    zero_equity_account_ids = [
        int(account_id)
        for result in results
        for account_id in result.get("zero_equity_account_ids") or []
    ]
    blocking_results = [
        result
        for result in results
        if result.get("zero_equity_status") == "blocking_no_positive_equity"
    ]
    placeholder_results = [
        result
        for result in results
        if result.get("zero_equity_status") == "non_blocking_placeholder"
    ]
    return {
        "status": payload.get("status"),
        "dry_run": payload.get("dry_run"),
        "target_count": payload.get("target_count"),
        "status_counts": dict(payload.get("status_counts") or {}),
        "decision_ready_account_count": len(decision_ready_account_ids),
        "decision_ready_account_ids": sorted(set(decision_ready_account_ids)),
        "zero_equity_account_count": len(zero_equity_account_ids),
        "zero_equity_account_ids": sorted(set(zero_equity_account_ids)),
        "non_blocking_placeholder_count": len(placeholder_results),
        "blocking_no_positive_equity_count": len(blocking_results),
        "results": results,
    }


def summarize_evidence_workspace_components(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return compact workspace component proof from readiness evidence."""

    workspace = _as_dict(payload.get("workspace"))
    result = _as_dict(workspace.get("result"))
    components = _as_dict(result.get("components"))
    rotation = _as_dict(components.get("rotation_signals"))
    if not rotation:
        return None
    return {
        "rotation_signals": {
            "status": rotation.get("status"),
            "signal_date": rotation.get("signal_date"),
            "total_configs": rotation.get("total_configs"),
            "successful": rotation.get("successful"),
            "skipped": rotation.get("skipped"),
            "failed": rotation.get("failed"),
        }
    }


def summarize_evidence_macro_context(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return compact Regime/Pulse context from one readiness evidence payload."""

    system = _as_dict(payload.get("system"))
    checks = _as_dict(system.get("checks"))
    regime = _as_dict(checks.get("regime"))
    pulse = _as_dict(checks.get("pulse"))
    if not regime and not pulse:
        return None
    return {
        "regime": {
            "status": regime.get("status"),
            "observed_at": regime.get("observed_at"),
            "dominant_regime": regime.get("dominant_regime"),
            "confidence": regime.get("confidence"),
            "source": regime.get("source"),
            "is_fallback": regime.get("is_fallback"),
            "records_count": regime.get("records_count"),
            "warnings": list(regime.get("warnings") or []),
        }
        if regime
        else None,
        "pulse": {
            "status": pulse.get("status"),
            "observed_at": pulse.get("observed_at"),
            "regime_context": pulse.get("regime_context"),
            "composite_score": pulse.get("composite_score"),
            "regime_strength": pulse.get("regime_strength"),
            "transition_warning": pulse.get("transition_warning"),
            "transition_direction": pulse.get("transition_direction"),
            "stale_indicator_count": pulse.get("stale_indicator_count"),
            "data_source": pulse.get("data_source"),
        }
        if pulse
        else None,
    }


def summarize_evidence_alpha_workspace(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return compact Alpha/workspace consistency proof from readiness evidence."""

    system = _as_dict(payload.get("system"))
    checks = _as_dict(system.get("checks"))
    consistency = _as_dict(checks.get("alpha_workspace_consistency"))
    if not consistency:
        return None
    return summarize_alpha_workspace_consistency(consistency)


def summarize_alpha_workspace_consistency(
    consistency: dict[str, Any],
) -> dict[str, Any] | None:
    """Return a compact operator-facing Alpha/workspace consistency summary."""

    if not consistency:
        return None

    alpha = _as_dict(consistency.get("alpha"))
    workspace = _as_dict(consistency.get("workspace"))
    issues = [
        _as_dict(item)
        for item in consistency.get("issues") or []
        if isinstance(item, dict)
    ]
    return {
        "status": consistency.get("status"),
        "checked_account_id": consistency.get("checked_account_id"),
        "issue_codes": [item.get("code") for item in issues if item.get("code")],
        "alpha": {
            "latest_trade_date": alpha.get("latest_trade_date"),
            "latest_updated_at": alpha.get("latest_updated_at"),
            "provider_source": alpha.get("provider_source"),
            "status": alpha.get("status"),
            "top_codes": list(alpha.get("top_codes") or [])[:10],
        },
        "workspace": {
            "account_id": workspace.get("account_id"),
            "latest_updated_at": workspace.get("latest_updated_at"),
            "recommendation_codes": list(workspace.get("recommendation_codes") or [])[:10],
            "source_candidate_id_count": len(workspace.get("source_candidate_ids") or []),
            "total_count": workspace.get("total_count"),
        },
    }


def build_current_macro_context(*, target_date: date) -> dict[str, Any]:
    """Return current Regime/Pulse context for operator-facing status output."""

    return {
        "regime": _collect_current_regime_context(target_date=target_date),
        "pulse": _collect_current_pulse_context(target_date=target_date),
    }


def build_scheduler_activity(
    *,
    validation: dict[str, Any],
    scheduler: dict[str, Any],
) -> dict[str, Any]:
    """Build final scheduler activity proof from evidence and PeriodicTask metadata."""

    run_metadata = dict(scheduler.get("run_metadata") or {})
    total_run_count = _parse_optional_int(run_metadata.get("total_run_count"))
    accepted_evidence = list(validation.get("accepted_evidence") or [])
    scheduler_trigger_count = _count_accepted_evidence_by_trigger(
        accepted_evidence=accepted_evidence,
        trigger_source="scheduler",
    )
    scheduler_task_provenance_count = _count_scheduler_task_provenance(
        accepted_evidence=accepted_evidence,
        expected_task_name=scheduler.get("task"),
    )
    scheduler_task_ids = _collect_scheduler_task_ids(
        accepted_evidence=accepted_evidence,
        expected_task_name=scheduler.get("task"),
    )
    unique_scheduler_task_id_count = len(set(scheduler_task_ids))
    manual_trigger_count = _count_accepted_evidence_by_trigger(
        accepted_evidence=accepted_evidence,
        trigger_source="manual",
    )
    latest_scheduler_evidence_date = _resolve_latest_accepted_evidence_date(
        accepted_evidence=accepted_evidence,
        trigger_source="scheduler",
    )
    latest_scheduler_run_date = _parse_iso_datetime_date(run_metadata.get("last_run_at"))
    legacy_count = sum(
        1
        for record in accepted_evidence
        if record.get("evidence_mode") == "legacy_without_operation_context"
    )
    required_dispatches = None
    if validation.get("status") == "accepted":
        required_days = int(validation.get("required_days") or 0)
        required_dispatches = required_days

    payload = {
        "status": "pending_window",
        "ok": True,
        "required_dispatches": required_dispatches,
        "observed_dispatches": total_run_count,
        "scheduler_trigger_record_count": scheduler_trigger_count,
        "scheduler_task_provenance_record_count": scheduler_task_provenance_count,
        "unique_scheduler_task_id_count": unique_scheduler_task_id_count,
        "duplicate_scheduler_task_id_count": max(
            len(scheduler_task_ids) - unique_scheduler_task_id_count,
            0,
        ),
        "missing_scheduler_task_provenance_record_count": max(
            scheduler_trigger_count - scheduler_task_provenance_count,
            0,
        ),
        "manual_trigger_record_count": manual_trigger_count,
        "legacy_record_count": legacy_count,
        "latest_scheduler_evidence_date": (
            latest_scheduler_evidence_date.isoformat() if latest_scheduler_evidence_date else None
        ),
        "latest_scheduler_run_date": (
            latest_scheduler_run_date.isoformat() if latest_scheduler_run_date else None
        ),
        "last_run_at": run_metadata.get("last_run_at"),
        "date_changed": run_metadata.get("date_changed"),
    }
    if validation.get("status") != "accepted":
        return payload

    if manual_trigger_count > 0:
        payload["status"] = "manual_formal_evidence_in_window"
        payload["ok"] = False
        return payload

    if legacy_count > 0:
        payload["status"] = "legacy_evidence_in_accepted_window"
        payload["ok"] = False
        return payload

    if scheduler_trigger_count < int(required_dispatches or 0):
        payload["status"] = "insufficient_scheduler_evidence"
        payload["ok"] = False
        return payload

    if scheduler_task_provenance_count < int(required_dispatches or 0):
        payload["status"] = "insufficient_scheduler_task_provenance"
        payload["ok"] = False
        return payload

    if unique_scheduler_task_id_count < int(required_dispatches or 0):
        payload["status"] = "duplicate_scheduler_task_ids"
        payload["ok"] = False
        return payload

    if (
        total_run_count is None
        or required_dispatches is None
        or total_run_count < required_dispatches
    ):
        payload["status"] = "insufficient_dispatch_history"
        payload["ok"] = False
        return payload

    if latest_scheduler_run_date is None:
        payload["status"] = "missing_scheduler_last_run_at"
        payload["ok"] = False
        return payload

    if (
        latest_scheduler_evidence_date is not None
        and latest_scheduler_run_date < latest_scheduler_evidence_date
    ):
        payload["status"] = "stale_scheduler_last_run_at"
        payload["ok"] = False
        return payload

    payload["status"] = "ok"
    return payload


def build_scheduler_kwargs_safety(*, effective_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Build safety metadata for scheduled readiness task keyword arguments."""

    issues: list[dict[str, str]] = []
    if effective_kwargs.get("allow_unclosed_target_date") is True:
        issues.append(
            {
                "code": "unclosed_target_date_override_enabled",
                "message": "Scheduled readiness evidence may run before the target date closes.",
            }
        )
    if effective_kwargs.get("repair_accounts") is True:
        issues.append(
            {
                "code": "scheduled_account_repair_enabled",
                "message": "Scheduled runs can create simulated readiness accounts.",
            }
        )
    if effective_kwargs.get("trigger_source") != "scheduler":
        issues.append(
            {
                "code": "scheduled_trigger_source_not_scheduler",
                "message": "Scheduled readiness evidence must be marked as scheduler-triggered.",
            }
        )
    if effective_kwargs.get("target_date"):
        issues.append(
            {
                "code": "fixed_scheduler_target_date",
                "message": "Scheduled readiness evidence must resolve the latest closed date.",
            }
        )
    if effective_kwargs.get("calendar_source") != "auto":
        issues.append(
            {
                "code": "unexpected_scheduler_calendar_source",
                "message": "Scheduled readiness evidence must use calendar_source=auto.",
            }
        )
    if effective_kwargs.get("run_workspace_refresh") is not True:
        issues.append(
            {
                "code": "scheduled_workspace_refresh_disabled",
                "message": "Scheduled readiness evidence must refresh the workspace.",
            }
        )
    if effective_kwargs.get("include_weekly_advisor") is not True:
        issues.append(
            {
                "code": "scheduled_weekly_advisor_disabled",
                "message": "Scheduled readiness evidence must include the advisor payload.",
            }
        )
    if effective_kwargs.get("persist_risk_report") is not True:
        issues.append(
            {
                "code": "scheduled_risk_report_persistence_disabled",
                "message": "Scheduled readiness evidence must persist risk-center daily reports.",
            }
        )
    max_qlib_staleness_days = _parse_optional_int(effective_kwargs.get("max_qlib_staleness_days"))
    if max_qlib_staleness_days is not None and (
        max_qlib_staleness_days <= 0 or max_qlib_staleness_days > MAX_SCHEDULED_QLIB_STALENESS_DAYS
    ):
        issues.append(
            {
                "code": "unsafe_scheduler_qlib_staleness_days",
                "message": (
                    "Scheduled readiness evidence must keep Qlib staleness threshold "
                    f"within {MAX_SCHEDULED_QLIB_STALENESS_DAYS} days."
                ),
            }
        )
    return {
        "allow_unclosed_target_date": bool(effective_kwargs.get("allow_unclosed_target_date")),
        "repair_accounts": bool(effective_kwargs.get("repair_accounts")),
        "trigger_source": effective_kwargs.get("trigger_source"),
        "calendar_source": effective_kwargs.get("calendar_source"),
        "run_workspace_refresh": effective_kwargs.get("run_workspace_refresh"),
        "include_weekly_advisor": effective_kwargs.get("include_weekly_advisor"),
        "persist_risk_report": effective_kwargs.get("persist_risk_report"),
        "max_qlib_staleness_days": max_qlib_staleness_days,
        "issues": issues,
    }


def classify_formal_risk_evidence(
    *,
    payload: dict[str, Any],
    classification: dict[str, Any],
) -> dict[str, Any]:
    """Classify formal risk-center evidence completeness for accepted readiness records."""

    formal_account_count = 0
    risk_report_ok_count = 0
    persisted_report_count = 0
    pre_trade_ok_count = 0
    pre_trade_missing_count = 0
    post_investment_ok_count = 0
    post_investment_missing_count = 0

    if classification["evidence_mode"] == "formal" and classification["acceptance_candidate"]:
        for account in payload.get("accounts") or []:
            formal_account_count += 1
            risk = dict(account.get("risk_center_daily_report") or {})
            if risk.get("status") == "ok":
                risk_report_ok_count += 1
            if risk.get("report_id") not in (None, ""):
                persisted_report_count += 1
            pre_trade = dict(risk.get("pre_trade_check") or {})
            if pre_trade.get("status") == "ok":
                pre_trade_ok_count += 1
            else:
                pre_trade_missing_count += 1
            post_investment = dict(risk.get("post_investment_check") or {})
            if post_investment.get("passed") is True:
                post_investment_ok_count += 1
            else:
                post_investment_missing_count += 1

    if formal_account_count <= 0:
        status = "not_formal"
    elif (
        risk_report_ok_count == formal_account_count
        and persisted_report_count == formal_account_count
        and pre_trade_ok_count == formal_account_count
        and post_investment_ok_count == formal_account_count
    ):
        status = "ok"
    else:
        status = "missing"

    return {
        "formal_risk_account_count": formal_account_count,
        "formal_risk_report_ok_account_count": risk_report_ok_count,
        "formal_risk_persisted_report_account_count": persisted_report_count,
        "formal_pre_trade_ok_account_count": pre_trade_ok_count,
        "formal_pre_trade_missing_account_count": pre_trade_missing_count,
        "formal_post_investment_ok_account_count": post_investment_ok_count,
        "formal_post_investment_missing_account_count": post_investment_missing_count,
        "formal_risk_evidence_status": status,
    }


def build_risk_center_formal_evidence_requirement(
    *,
    validation: dict[str, Any],
) -> dict[str, Any]:
    """Build the final acceptance gate for risk-center evidence."""

    quality = dict(validation.get("accepted_evidence_quality") or {})
    record_count = int(quality.get("formal_record_count") or 0)
    risk_record_count = int(quality.get("formal_risk_record_count") or 0)
    risk_ok_record_count = int(quality.get("formal_risk_ok_record_count") or 0)
    risk_missing_record_count = int(quality.get("formal_risk_missing_record_count") or 0)
    account_count = int(quality.get("formal_risk_account_count") or 0)
    risk_ok_count = int(quality.get("formal_risk_report_ok_account_count") or 0)
    persisted_report_count = int(
        quality.get("formal_risk_persisted_report_account_count", risk_ok_count) or 0
    )
    pre_trade_ok_count = int(quality.get("formal_pre_trade_ok_account_count") or 0)
    pre_trade_missing_count = int(quality.get("formal_pre_trade_missing_account_count") or 0)
    post_investment_ok_count = int(quality.get("formal_post_investment_ok_account_count") or 0)
    post_investment_missing_count = int(
        quality.get("formal_post_investment_missing_account_count") or 0
    )
    payload = {
        "ok": True,
        "status": "pending_window",
        "required_when": "evidence_window_accepted",
        "formal_record_count": record_count,
        "risk_record_count": risk_record_count,
        "ok_record_count": risk_ok_record_count,
        "missing_record_count": risk_missing_record_count,
        "account_count": account_count,
        "risk_ok_account_count": risk_ok_count,
        "persisted_report_account_count": persisted_report_count,
        "pre_trade_ok_account_count": pre_trade_ok_count,
        "pre_trade_missing_account_count": pre_trade_missing_count,
        "post_investment_ok_account_count": post_investment_ok_count,
        "post_investment_missing_account_count": post_investment_missing_count,
    }
    if validation.get("status") != "accepted":
        return payload
    complete = (
        record_count > 0
        and risk_record_count == record_count
        and risk_ok_record_count == record_count
        and risk_missing_record_count == 0
        and account_count > 0
        and risk_ok_count == account_count
        and persisted_report_count == account_count
        and pre_trade_ok_count == account_count
        and pre_trade_missing_count == 0
        and post_investment_ok_count == account_count
        and post_investment_missing_count == 0
    )
    payload["status"] = "ok" if complete else "missing"
    payload["ok"] = payload["status"] == "ok"
    return payload


def build_risk_center_persistence_advisory_action(
    *, requirement: dict[str, Any]
) -> dict[str, Any] | None:
    """Build a non-blocking operator action for early risk persistence gaps."""

    if requirement.get("status") != "pending_window":
        return None
    account_count = int(requirement.get("account_count") or 0)
    persisted_report_count = int(requirement.get("persisted_report_account_count") or 0)
    risk_ok_count = int(requirement.get("risk_ok_account_count") or 0)
    if account_count <= 0:
        return None
    if risk_ok_count < account_count:
        return None
    if persisted_report_count >= account_count:
        return None
    return {
        "requirement": "risk_center_formal_evidence",
        "action": "verify_scheduled_risk_report_persistence",
        "reason": "formal_risk_reports_not_persisted_yet",
        "account_count": account_count,
        "persisted_report_account_count": persisted_report_count,
        "advisory": True,
        "command": "python manage.py show_personal_readiness_status --json --strict-monitor",
    }


def count_scheduler_clean_suffix_days(*, records: list[dict[str, Any]]) -> int:
    """Count the latest contiguous formal scheduler records with task provenance."""

    count = 0
    for record in reversed(records):
        if not all(
            [
                record.get("evidence_mode") == "formal",
                record.get("acceptance_candidate") is True,
                record.get("trigger_source") == "scheduler",
                bool(record.get("trigger_task_id")),
                bool(record.get("trigger_task_name")),
            ]
        ):
            break
        count += 1
    return count


def count_weekly_schedule_dates(
    *,
    start_date: date | None,
    end_date: date | None,
    weekday: int = 4,
) -> int:
    """Count scheduled weekly dates inside an inclusive date window."""

    if start_date is None or end_date is None or end_date < start_date:
        return 0
    current = start_date
    count = 0
    while current <= end_date:
        if current.weekday() == weekday:
            count += 1
        current += timedelta(days=1)
    return count


def latest_weekly_schedule_date(
    *,
    start_date: date | None,
    end_date: date | None,
    weekday: int = 4,
) -> date | None:
    """Resolve the latest scheduled weekly date inside an inclusive date window."""

    if start_date is None or end_date is None or end_date < start_date:
        return None
    current = end_date
    while current >= start_date:
        if current.weekday() == weekday:
            return current
        current -= timedelta(days=1)
    return None


def _parse_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _isoformat_or_value(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def _summarize_thermometer_component_details(thermometer: dict[str, Any]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for raw_component in thermometer.get("components") or []:
        component = _as_dict(raw_component)
        component_key = component.get("component_key")
        if not component_key:
            continue
        details.append(
            {
                "component_key": component_key,
                "label": component.get("label"),
                "is_stale": bool(component.get("is_stale")),
                "is_missing": bool(component.get("is_missing")),
                "age_days": component.get("age_days"),
                "current_value": component.get("current_value"),
                "unit": component.get("unit"),
            }
        )
    return details


def _collect_current_regime_context(*, target_date: date) -> dict[str, Any]:
    try:
        from apps.regime.application.interface_services import (
            get_regime_current_payload,
            get_regime_health_payload,
        )

        health = get_regime_health_payload()
        current = get_regime_current_payload(as_of_date=target_date)
        data = _as_dict(current.get("data"))
        return {
            "status": "ok" if current.get("success") else "warning",
            "health_status": health.get("status"),
            "records_count": health.get("records_count"),
            "observed_at": _isoformat_or_value(data.get("observed_at")),
            "dominant_regime": data.get("dominant_regime"),
            "confidence": data.get("confidence"),
            "source": data.get("source"),
            "is_fallback": data.get("is_fallback"),
            "warnings": list(data.get("warnings") or []),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _collect_current_pulse_context(*, target_date: date) -> dict[str, Any]:
    try:
        from apps.pulse.application.use_cases import GetLatestPulseUseCase

        snapshot = GetLatestPulseUseCase().execute(
            as_of_date=target_date,
            require_reliable=False,
            refresh_if_stale=False,
        )
        if snapshot is None:
            return {"status": "missing"}
        return {
            "status": "ok",
            "observed_at": _isoformat_or_value(snapshot.observed_at),
            "regime_context": snapshot.regime_context,
            "composite_score": snapshot.composite_score,
            "regime_strength": snapshot.regime_strength,
            "transition_warning": snapshot.transition_warning,
            "transition_direction": snapshot.transition_direction,
            "stale_indicator_count": snapshot.stale_indicator_count,
            "data_source": snapshot.data_source,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _count_accepted_evidence_by_trigger(
    *,
    accepted_evidence: list[Any],
    trigger_source: str,
) -> int:
    return sum(
        1
        for record in accepted_evidence
        if isinstance(record, dict) and record.get("trigger_source") == trigger_source
    )


def _count_scheduler_task_provenance(
    *,
    accepted_evidence: list[Any],
    expected_task_name: Any,
) -> int:
    if not expected_task_name:
        return 0
    expected = str(expected_task_name)
    return sum(
        1
        for record in accepted_evidence
        if isinstance(record, dict)
        and record.get("trigger_source") == "scheduler"
        and record.get("trigger_task_id")
        and record.get("trigger_task_name") == expected
    )


def _collect_scheduler_task_ids(
    *,
    accepted_evidence: list[Any],
    expected_task_name: Any,
) -> list[str]:
    if not expected_task_name:
        return []
    expected = str(expected_task_name)
    task_ids: list[str] = []
    for record in accepted_evidence:
        if not isinstance(record, dict):
            continue
        if record.get("trigger_source") != "scheduler":
            continue
        if record.get("trigger_task_name") != expected:
            continue
        raw_task_id = record.get("trigger_task_id")
        if not raw_task_id:
            continue
        task_ids.append(str(raw_task_id))
    return task_ids


def _resolve_latest_accepted_evidence_date(
    *,
    accepted_evidence: list[Any],
    trigger_source: str,
) -> date | None:
    dates: list[date] = []
    for record in accepted_evidence:
        if not isinstance(record, dict) or record.get("trigger_source") != trigger_source:
            continue
        raw_target_date = record.get("target_date")
        if not raw_target_date:
            continue
        try:
            dates.append(date.fromisoformat(str(raw_target_date)))
        except ValueError:
            continue
    return max(dates, default=None)


def _parse_iso_datetime_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None
