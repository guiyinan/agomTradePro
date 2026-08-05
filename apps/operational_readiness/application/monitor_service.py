"""UI-facing personal readiness monitor summaries."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from copy import deepcopy
from datetime import date, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from django.core.cache import cache

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = "var/readiness-evidence"
DEFAULT_REQUIRED_DAYS = 20
DEFAULT_CALENDAR_SOURCE = "auto"
STRICT_RUNTIME_CACHE_KEY = "task_monitor:readiness_monitor:strict:v1"
STRICT_RUNTIME_CACHE_TTL_SECONDS = 60


def get_personal_readiness_monitor_summary(
    *,
    strict_runtime: bool = False,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Return the operator-facing daily readiness monitor payload."""

    if strict_runtime and not include_raw:
        cached_summary = _get_cached_strict_runtime_summary()
        if cached_summary is not None:
            return cached_summary

    payload = build_personal_readiness_status(
        output_dir=Path(DEFAULT_OUTPUT_DIR),
        required_days=DEFAULT_REQUIRED_DAYS,
        calendar_source=DEFAULT_CALENDAR_SOURCE,
        expected_latest_date=resolve_default_readiness_target_date(),
        require_local_scheduler_runtime=strict_runtime,
        include_current_macro_context=True,
        include_current_decision_data=True,
    )
    summary = _summarize_personal_readiness_payload(payload)
    if include_raw:
        summary["raw"] = payload
    elif strict_runtime:
        _set_cached_strict_runtime_summary(summary)
    return summary


def build_personal_readiness_status(**kwargs: Any) -> dict[str, Any]:
    """Resolve the status command implementation at runtime."""

    module = import_module(
        "apps.operational_readiness.management.commands.show_personal_readiness_status"
    )
    result: object = module.build_personal_readiness_status(**kwargs)
    return _require_payload_mapping(result, label="personal readiness status")


def resolve_default_readiness_target_date() -> date:
    """Resolve the default target-date helper at runtime."""

    module = import_module(
        "apps.operational_readiness.management.commands.run_personal_readiness_daily"
    )
    result: object = module.resolve_default_readiness_target_date()
    if isinstance(result, datetime) or not isinstance(result, date):
        raise TypeError("default readiness target date provider returned an invalid value")
    return result


def get_ai_capability_surface_status_payload() -> dict[str, Any]:
    """Resolve AI capability surface status without a static app dependency."""

    module = import_module("apps.ai_capability.application.query_services")
    result: object = module.get_ai_capability_surface_status_payload()
    return _require_payload_mapping(result, label="AI capability surface status")


def get_terminal_surface_status_payload() -> dict[str, Any]:
    """Resolve Terminal surface status without a static app dependency."""

    module = import_module("apps.terminal.application.query_services")
    result: object = module.get_terminal_surface_status_payload()
    return _require_payload_mapping(result, label="Terminal surface status")


def get_active_stock_fact_coverage_payload() -> dict[str, Any]:
    """Resolve Data Center coverage status without a static app dependency."""

    module = import_module("apps.data_center.application.public")
    result: object = module.get_active_stock_fact_coverage_payload()
    return _require_payload_mapping(result, label="active stock fact coverage")


def _get_cached_strict_runtime_summary() -> dict[str, Any] | None:
    try:
        cached: object = cache.get(STRICT_RUNTIME_CACHE_KEY)
        cached_summary = _copy_payload_mapping(cached)
    except Exception as exc:
        _log_readiness_failure("Readiness monitor strict cache read failed", exc)
        return None
    if cached_summary is None or not _is_cached_monitor_summary(cached_summary):
        return None
    return cached_summary


def _set_cached_strict_runtime_summary(summary: dict[str, Any]) -> None:
    try:
        cache.set(
            STRICT_RUNTIME_CACHE_KEY,
            deepcopy(summary),
            timeout=STRICT_RUNTIME_CACHE_TTL_SECONDS,
        )
    except Exception as exc:
        _log_readiness_failure("Readiness monitor strict cache write failed", exc)


def get_personal_readiness_monitor_placeholder() -> dict[str, Any]:
    """Return a lightweight placeholder for initial page rendering."""

    return {
        "status": "loading",
        "daily_state": {
            "code": "loading",
            "severity": "neutral",
            "title": "正在读取验收状态",
            "message": "页面加载后会读取最新 readiness monitor。",
        },
        "monitor_gate": {
            "ok": False,
            "state": "loading",
            "reason": None,
            "next_action": None,
            "next_check_after": None,
            "command": None,
        },
        "window": {
            "accepted": False,
            "accepted_days": 0,
            "required_days": DEFAULT_REQUIRED_DAYS,
            "remaining_days": DEFAULT_REQUIRED_DAYS,
            "latest_target_date": None,
            "next_required_date": None,
            "next_required_reason": None,
            "projected_completion_date": None,
            "projected_scheduler_completion_date": None,
        },
        "today": {
            "status_date": None,
            "latest_closed_date": None,
            "expected_latest_date": None,
            "latest_evidence_status": None,
            "latest_evidence_target_date": None,
            "latest_target_date": None,
        },
        "schedule": {
            "due_status": None,
            "scheduled_for": None,
            "grace_deadline": None,
            "next_check_after": None,
        },
        "next_action": {
            "action": None,
            "reason": None,
            "target_date": None,
            "command": None,
        },
        "scheduler_runtime": {
            "required": False,
            "status": "not_checked",
            "worker_process_count": None,
            "beat_process_count": None,
            "responsive_worker_count": None,
            "missing_queues": [],
            "missing_registered_tasks": [],
        },
        "decision_data": {
            "status": None,
            "readiness_status": None,
            "must_not_use_for_decision": False,
            "blocked_reasons": [],
        },
        "data_coverage": _empty_data_coverage(),
        "operator_surfaces": _empty_operator_surfaces(),
        "blocking_issues": [],
        "accepted_dates": [],
    }


def _summarize_personal_readiness_payload(payload: dict[str, Any]) -> dict[str, Any]:
    validation = _mapping_field(payload, "validation")
    monitor_gate = _mapping_field(payload, "monitor_gate")
    latest_evidence = _mapping_field(payload, "latest_evidence")
    acceptance_gate = _mapping_field(payload, "acceptance_gate")
    schedule_expectation = _mapping_field(payload, "schedule_expectation")
    next_action = _mapping_field(payload, "next_action")
    scheduler_runtime = _mapping_field(payload, "scheduler_runtime")
    current_decision_data = _mapping_field(payload, "current_decision_data")
    latest_target_date = str(
        latest_evidence.get("target_date")
        or validation.get("latest_target_date")
        or payload.get("expected_latest_date")
        or ""
    )

    daily_state = _classify_daily_state(
        payload=payload,
        validation=validation,
        monitor_gate=monitor_gate,
        latest_evidence=latest_evidence,
        acceptance_gate=acceptance_gate,
        schedule_expectation=schedule_expectation,
        next_action=next_action,
    )

    summary = {
        "status": payload.get("status"),
        "daily_state": daily_state,
        "monitor_gate": {
            "ok": monitor_gate.get("ok") is True,
            "state": monitor_gate.get("state"),
            "reason": monitor_gate.get("reason"),
            "next_action": monitor_gate.get("next_action"),
            "next_check_after": monitor_gate.get("next_check_after"),
            "command": monitor_gate.get("command"),
        },
        "window": {
            "accepted": acceptance_gate.get("accepted") is True,
            "accepted_days": validation.get("accepted_days"),
            "required_days": validation.get("required_days"),
            "remaining_days": validation.get("remaining_days"),
            "latest_target_date": validation.get("latest_target_date"),
            "next_required_date": validation.get("next_required_date"),
            "next_required_reason": validation.get("next_required_reason"),
            "projected_completion_date": acceptance_gate.get("projected_completion_date"),
            "projected_scheduler_completion_date": acceptance_gate.get(
                "projected_scheduler_completion_date"
            ),
        },
        "today": {
            "status_date": payload.get("status_date"),
            "latest_closed_date": payload.get("latest_closed_date"),
            "expected_latest_date": payload.get("expected_latest_date"),
            "latest_evidence_status": latest_evidence.get("status"),
            "latest_evidence_target_date": latest_evidence.get("target_date"),
            "latest_target_date": latest_target_date,
        },
        "schedule": {
            "due_status": schedule_expectation.get("due_status"),
            "scheduled_for": schedule_expectation.get("scheduled_for"),
            "grace_deadline": schedule_expectation.get("grace_deadline"),
            "next_check_after": monitor_gate.get("next_check_after"),
        },
        "next_action": {
            "action": next_action.get("action"),
            "reason": next_action.get("reason"),
            "target_date": next_action.get("target_date"),
            "command": next_action.get("command"),
        },
        "scheduler_runtime": {
            "required": scheduler_runtime.get("required") is True,
            "status": scheduler_runtime.get("status"),
            "worker_process_count": scheduler_runtime.get("worker_process_count"),
            "beat_process_count": scheduler_runtime.get("beat_process_count"),
            "responsive_worker_count": scheduler_runtime.get("responsive_worker_count"),
            "missing_queues": _sequence_value(scheduler_runtime.get("missing_queues")),
            "missing_registered_tasks": _sequence_value(
                scheduler_runtime.get("missing_registered_tasks")
            ),
        },
        "decision_data": {
            "status": current_decision_data.get("status"),
            "readiness_status": current_decision_data.get("readiness_status"),
            "must_not_use_for_decision": current_decision_data.get("must_not_use_for_decision")
            is True,
            "blocked_reasons": _sequence_value(current_decision_data.get("blocked_reasons")),
        },
        "data_coverage": _get_data_coverage(),
        "operator_surfaces": _get_operator_surfaces(),
        "blocking_issues": _sequence_value(validation.get("blocking_issues")),
        "accepted_dates": _sequence_value(validation.get("accepted_dates")),
    }
    return summary


def _get_operator_surfaces() -> dict[str, Any]:
    payload = _empty_operator_surfaces()
    ai_capability = _get_ai_capability_surface()
    terminal = _get_terminal_surface()
    payload["ai_capability"] = ai_capability
    payload["terminal"] = terminal
    payload["status"] = (
        "ok"
        if all(item.get("status") == "ok" for item in [ai_capability, terminal])
        else "incomplete"
    )
    return payload


def _get_ai_capability_surface() -> dict[str, Any]:
    try:
        return get_ai_capability_surface_status_payload()
    except Exception as exc:
        _log_readiness_failure("Readiness monitor AI capability query failed", exc)
        return {"status": "error", "error": "ai_capability_status_unavailable"}


def _get_terminal_surface() -> dict[str, Any]:
    try:
        return get_terminal_surface_status_payload()
    except Exception as exc:
        _log_readiness_failure("Readiness monitor terminal surface query failed", exc)
        return {"status": "error", "error": "terminal_status_unavailable"}


def _empty_operator_surfaces() -> dict[str, Any]:
    return {
        "status": "loading",
        "ai_capability": {
            "status": "loading",
            "catalog": {"total": 0, "enabled": 0, "disabled": 0},
            "mcp_tools": {
                "total": 0,
                "routing_enabled": 0,
                "terminal_enabled": 0,
                "chat_enabled": 0,
                "agent_enabled": 0,
                "requires_confirmation": 0,
                "latest_sync_at": None,
                "status": "loading",
            },
            "terminal_capabilities": {
                "total": 0,
                "routing_enabled": 0,
                "terminal_enabled": 0,
                "chat_enabled": 0,
                "agent_enabled": 0,
                "requires_confirmation": 0,
                "latest_sync_at": None,
                "status": "loading",
            },
        },
        "terminal": {
            "status": "loading",
            "terminal_commands": {
                "active": 0,
                "terminal_enabled": 0,
                "requires_mcp": 0,
                "api_type": 0,
                "prompt_type": 0,
                "status": "loading",
            },
            "tui_metadata": {
                "status": "loading",
                "version": None,
                "schema_version": None,
                "modules": 0,
                "screens": 0,
                "actions": 0,
                "default_screen": None,
                "coverage_summary": {},
            },
        },
    }


def _get_data_coverage() -> dict[str, Any]:
    try:
        return get_active_stock_fact_coverage_payload()
    except Exception as exc:
        _log_readiness_failure("Readiness monitor data coverage query failed", exc)
        payload = _empty_data_coverage()
        payload["status"] = "error"
        payload["error"] = "data_coverage_unavailable"
        return payload


def _empty_data_coverage() -> dict[str, Any]:
    return {
        "status": "loading",
        "universe": "active_stock",
        "asset_count": 0,
        "universe_quality": {
            "status": "loading",
            "minimum_active_a_share_count": 0,
            "minimum_star_market_count": 0,
            "minimum_bse_count": 0,
            "exchange_counts": {"SSE": 0, "SZSE": 0, "BSE": 0},
            "board_counts": {
                "star_market": 0,
                "chinext": 0,
                "bse": 0,
                "sh_main": 0,
                "sz_main": 0,
            },
            "issues": [],
        },
        "domains": {
            "price": {
                "covered_count": 0,
                "missing_count": 0,
                "latest_date": None,
                "status": "loading",
            },
            "valuation": {
                "covered_count": 0,
                "missing_count": 0,
                "latest_date": None,
                "status": "loading",
            },
            "financial": {
                "covered_count": 0,
                "missing_count": 0,
                "latest_date": None,
                "status": "loading",
            },
        },
    }


def _classify_daily_state(
    *,
    payload: dict[str, Any],
    validation: dict[str, Any],
    monitor_gate: dict[str, Any],
    latest_evidence: dict[str, Any],
    acceptance_gate: dict[str, Any],
    schedule_expectation: dict[str, Any],
    next_action: dict[str, Any],
) -> dict[str, Any]:
    if acceptance_gate.get("accepted") is True:
        return {
            "code": "window_accepted",
            "severity": "ok",
            "title": "20 日验收窗口已完成",
            "message": "连续运行证据窗口已经满足正式验收要求。",
        }

    if monitor_gate.get("ok") is not True:
        return {
            "code": "needs_attention",
            "severity": "danger",
            "title": "需要处理",
            "message": _build_attention_message(
                monitor_gate=monitor_gate,
                next_action=next_action,
            ),
        }

    latest_evidence_target = latest_evidence.get("target_date")
    expected_latest_date = payload.get("expected_latest_date")
    next_required_date = validation.get("next_required_date")
    latest_closed_date = payload.get("latest_closed_date")

    if (
        latest_evidence.get("status") == "ok"
        and latest_evidence_target == expected_latest_date
        and next_required_date
        and latest_closed_date
        and str(next_required_date) > str(latest_closed_date)
    ):
        return {
            "code": "latest_closed_day_accepted",
            "severity": "ok",
            "title": "最新收盘日已验收",
            "message": "当前最新已收盘交易日已有有效证据，等待下一交易日收盘。",
        }

    action = str(next_action.get("action") or "")
    due_status = str(schedule_expectation.get("due_status") or "")
    if action == "wait_for_post_close":
        return {
            "code": "waiting_post_close",
            "severity": "neutral",
            "title": "等待收盘",
            "message": "下一个验收目标交易日尚未收盘。",
        }
    if action == "wait_for_scheduled_run" or due_status in {"pending", "grace_period"}:
        return {
            "code": "waiting_scheduled_run",
            "severity": "warn",
            "title": "等待自动证据",
            "message": "目标交易日已进入调度窗口，等待 Celery beat 生成证据。",
        }
    return {
        "code": "monitor_ok",
        "severity": "ok",
        "title": "监视器正常",
        "message": "当前没有需要人工处理的 readiness 问题。",
    }


def _build_attention_message(
    *,
    monitor_gate: dict[str, Any],
    next_action: dict[str, Any],
) -> str:
    command = _bounded_public_text(
        monitor_gate.get("command") or next_action.get("command"),
        max_length=512,
    )
    reason = (
        _bounded_public_text(
            monitor_gate.get("reason") or next_action.get("reason"),
            max_length=512,
        )
        or "unknown"
    )
    if command:
        return f"{reason}: {command}"
    return reason


def _require_payload_mapping(value: object, *, label: str) -> dict[str, Any]:
    """Return a detached string-keyed mapping or reject a broken dynamic provider."""

    payload = _copy_payload_mapping(value)
    if payload is None:
        raise TypeError(f"{label} provider returned a non-object payload")
    return payload


def _copy_payload_mapping(value: object) -> dict[str, Any] | None:
    """Detach a dynamic mapping while rejecting non-string keys."""

    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    for key, nested_value in value.items():
        if not isinstance(key, str):
            return None
        result[key] = deepcopy(nested_value)
    return result


def _mapping_field(payload: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    """Read one nested object without letting malformed sections crash the monitor."""

    return _copy_payload_mapping(payload.get(field_name)) or {}


def _sequence_value(value: object) -> list[Any]:
    """Return a detached bounded list without splitting strings into characters."""

    if not isinstance(value, (list, tuple)):
        return []
    return [deepcopy(item) for item in value[:500]]


def _is_cached_monitor_summary(payload: Mapping[str, Any]) -> bool:
    """Return whether cached strict-runtime data has the governed summary shape."""

    required_mapping_fields = (
        "daily_state",
        "monitor_gate",
        "window",
        "today",
        "schedule",
        "next_action",
        "scheduler_runtime",
        "decision_data",
        "data_coverage",
        "operator_surfaces",
    )
    if not isinstance(payload.get("status"), str):
        return False
    if any(
        not isinstance(payload.get(field_name), Mapping) for field_name in required_mapping_fields
    ):
        return False
    if not isinstance(payload.get("blocking_issues"), list) or not isinstance(
        payload.get("accepted_dates"), list
    ):
        return False
    daily_state = payload["daily_state"]
    monitor_gate = payload["monitor_gate"]
    window = payload["window"]
    return bool(
        isinstance(daily_state.get("code"), str)
        and isinstance(daily_state.get("severity"), str)
        and isinstance(monitor_gate.get("ok"), bool)
        and isinstance(window.get("accepted"), bool)
    )


def _bounded_public_text(value: object, *, max_length: int) -> str | None:
    """Return a bounded single-line UI string from a dynamic readiness field."""

    if not isinstance(value, str):
        return None
    normalized = " ".join(value.replace("\x00", " ").split())
    if not normalized:
        return None
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[:max_length]}…"


def _log_readiness_failure(message: str, exc: BaseException) -> None:
    """Log a stable readiness failure without exposing provider exception text."""

    logger.warning(message, extra={"exception_type": type(exc).__name__})
