"""Shared parsing and normalization contract for readiness evidence."""

from __future__ import annotations

from typing import Any

ACCEPTED_DECISION_QUOTE_FRESHNESS_STATUSES = frozenset({"fresh", "ok", "latest_completed_session"})


def classify_operation_context(operation_context: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy and formal readiness operation provenance."""

    if not operation_context:
        return {
            "formal_evidence": None,
            "evidence_mode": "legacy_without_operation_context",
            "acceptance_candidate": True,
            "trigger_source": None,
            "trigger_task_id": None,
            "trigger_task_name": None,
        }
    formal_evidence = (
        operation_context.get("mode") == "formal"
        and operation_context.get("target_date_closed") is True
        and operation_context.get("allow_unclosed_target_date") is not True
    )
    return {
        "formal_evidence": formal_evidence,
        "evidence_mode": str(operation_context.get("mode") or "unknown"),
        "acceptance_candidate": formal_evidence,
        "trigger_source": _optional_string(operation_context.get("trigger_source")),
        "trigger_task_id": _optional_string(operation_context.get("trigger_task_id")),
        "trigger_task_name": _optional_string(operation_context.get("trigger_task_name")),
    }


def classify_evidence_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize provenance directly from a readiness evidence payload."""

    return classify_operation_context(dict(payload.get("operation_context") or {}))


def get_decision_data(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the normalized decision-data evidence section."""

    system = dict(payload.get("system") or {})
    checks = dict(system.get("checks") or {})
    decision_data = checks.get("decision_data")
    return dict(decision_data) if isinstance(decision_data, dict) else {}


def get_workspace_components(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the normalized workspace component map."""

    workspace = dict(payload.get("workspace") or {})
    result = dict(workspace.get("result") or {})
    components = result.get("components")
    return dict(components) if isinstance(components, dict) else {}


def workspace_core_status(components: dict[str, Any]) -> str:
    """Classify the workspace core evidence with one shared rule."""

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


def decision_quote_freshness_status(decision_data: dict[str, Any]) -> str:
    """Classify quote freshness with the canonical accepted-status set."""

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
        if freshness_status and freshness_status not in ACCEPTED_DECISION_QUOTE_FRESHNESS_STATUSES:
            has_stale = True
    return "stale" if has_stale else "ok"


def _optional_string(value: Any) -> str | None:
    """Normalize optional provenance identifiers without inventing values."""

    return str(value) if value is not None else None


__all__ = [
    "ACCEPTED_DECISION_QUOTE_FRESHNESS_STATUSES",
    "classify_evidence_payload",
    "classify_operation_context",
    "decision_quote_freshness_status",
    "get_decision_data",
    "get_workspace_components",
    "workspace_core_status",
]
