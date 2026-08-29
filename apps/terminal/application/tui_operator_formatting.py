"""Formatting and severity helpers for operator-oriented TUI payloads."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from django.utils import timezone

from apps.audit.domain.entities import mask_sensitive_text

SEVERITY_ORDER = {
    "blocked": 0,
    "warning": 1,
    "notice": 2,
    "ok": 3,
}


def _governance_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    severity = _normalize_severity(str(row.get("severity") or "ok"))
    observed_at = str(row.get("observed_at") or "")
    return (SEVERITY_ORDER[severity], _descending_iso(observed_at))


def _descending_iso(value: str) -> str:
    return "".join(chr(255 - ord(ch)) for ch in value)


def _decision_queue_severity(status: str) -> str:
    normalized = str(status or "").upper()
    if normalized.startswith(("CONFLICT", "ERROR", "BLOCKED", "FAIL")):
        return "blocked"
    if normalized.startswith(("DEGRADED", "PENDING", "WARN", "WAIT")):
        return "warning"
    if normalized.startswith(("CLEAR", "DONE", "SUCCESS")):
        return "ok"
    return "notice"


def _monitor_severity(summary: dict[str, Any]) -> str:
    daily_state = dict(summary.get("daily_state") or {})
    return _map_external_severity(str(daily_state.get("severity") or ""))


def _map_external_severity(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"danger", "blocked", "error"}:
        return "blocked"
    if normalized in {"warn", "warning"}:
        return "warning"
    if normalized in {"neutral", "notice", "info"}:
        return "notice"
    return "ok"


def _surface_severity(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").strip().lower()
    if status in {"error", "blocked", "unavailable"}:
        return "blocked"
    if status in {"incomplete", "warning", "attention", "empty"}:
        return "warning"
    if status in {"loading", "unknown"}:
        return "notice"
    return "ok"


def _surface_reason(payload: dict[str, Any], fallback: str) -> str:
    return _first_text(
        payload.get("error"),
        payload.get("message"),
        payload.get("detail"),
        fallback if _surface_severity(payload) != "ok" else "",
    )


def _coverage_severity(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").strip().lower()
    if status in {"error", "blocked"}:
        return "blocked"
    if status in {"incomplete", "warning", "loading"}:
        return "warning"
    return "ok"


def _coverage_reason(payload: dict[str, Any]) -> str:
    universe_quality = dict(payload.get("universe_quality") or {})
    domains = dict(payload.get("domains") or {})
    issues = list(universe_quality.get("issues") or [])
    if issues:
        return _first_text(issues[0])
    for domain_name, detail in domains.items():
        if int((detail or {}).get("missing_count") or 0) > 0:
            return f"{domain_name} missing {(detail or {}).get('missing_count')} assets"
    return str(payload.get("error") or "")


def _latest_created_at(items: list[Any]) -> str:
    if not items:
        return _iso(timezone.now())
    latest = None
    for item in items:
        created_at = getattr(item, "created_at", None)
        if created_at is None:
            continue
        if latest is None or created_at > latest:
            latest = created_at
    return _iso(latest or timezone.now())


def _overall_status(sections: list[list[dict[str, Any]]]) -> str:
    severities = [
        _normalize_severity(str(row.get("severity") or "ok"))
        for section in sections
        for row in section
    ]
    return _highest_severity(severities)


def _highest_severity(severities: list[str]) -> str:
    if any(severity == "blocked" for severity in severities):
        return "blocked"
    if any(severity == "warning" for severity in severities):
        return "warning"
    if any(severity == "notice" for severity in severities):
        return "notice"
    return "ok"


def _normalize_severity(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SEVERITY_ORDER:
        return normalized
    return "ok"


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            for item in value:
                text = _first_text(item)
                if text:
                    return text
            continue
        text = str(value or "").strip()
        if text:
            return mask_sensitive_text(text)[:2_000]
    return ""


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    return text


def _domain_screen(domain: str) -> str:
    mapping = {
        "runtime": "api-library.runtime",
        "data-center": "api-library.data-center",
        "ai-provider": "ai-ops.providers",
        "ai-capability": "ai-ops.providers",
        "agent-runtime": "ai-ops.agent-runtime",
        "account-settings": "execution.account-settings",
        "config-center": "api-library.config-center",
    }
    return mapping.get(domain, "api-library.runtime")


def _domain_action(domain: str) -> str:
    mapping = {
        "runtime": "operator.governance.runtime_summary",
        "data-center": "operator.governance.data_center_summary",
        "ai-provider": "operator.governance.ai_provider_summary",
        "ai-capability": "operator.governance.ai_provider_summary",
        "agent-runtime": "operator.governance.agent_runtime_summary",
        "account-settings": "operator.governance.account_settings_summary",
        "config-center": "operator.governance.config_center_summary",
    }
    return mapping.get(domain, "operator.governance.runtime_summary")


def _is_admin_user(user: Any | None) -> bool:
    if user is None:
        return False
    if bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False)):
        return True
    role = str(getattr(user, "rbac_role", "") or "").strip().lower()
    if role == "admin":
        return True
    profile = getattr(user, "account_profile", None)
    profile_role = str(getattr(profile, "rbac_role", "") or "").strip().lower()
    return profile_role == "admin"


__all__ = [
    "_coverage_reason",
    "_coverage_severity",
    "_decision_queue_severity",
    "_domain_action",
    "_domain_screen",
    "_first_text",
    "_governance_sort_key",
    "_highest_severity",
    "_iso",
    "_is_admin_user",
    "_latest_created_at",
    "_map_external_severity",
    "_monitor_severity",
    "_normalize_severity",
    "_overall_status",
    "_surface_reason",
    "_surface_severity",
]
