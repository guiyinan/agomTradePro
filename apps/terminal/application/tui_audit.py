"""Canonical audit helpers for metadata-driven TUI action execution."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any, Mapping

from apps.terminal.domain.entities import TerminalAuditEntry
from apps.terminal.domain.interfaces import TerminalAuditRepository

TUI_AUDIT_SCHEMA_VERSION = "tui-audit.v1"
SENSITIVE_PARAM_TOKENS = (
    "access_token",
    "api_key",
    "authorization",
    "credential",
    "otp",
    "passcode",
    "password",
    "secret",
    "token",
)


def action_requires_audit(action: Mapping[str, Any]) -> bool:
    """Return whether one TUI action must emit a canonical audit record."""

    if bool(action.get("audit_required")):
        return True
    risk = str(action.get("risk") or "read").strip().lower()
    method = str(action.get("method") or "GET").strip().upper()
    return risk in {"write", "admin"} and method != "GET"


def mask_sensitive_params(
    action: Mapping[str, Any],
    params: Mapping[str, Any],
) -> dict[str, Any]:
    """Return params with credential-like fields masked for audit storage."""

    sensitive_keys = {
        str(field.get("key") or "")
        for field in action.get("fields") or []
        if isinstance(field, Mapping) and _is_sensitive_param_key(str(field.get("key") or ""))
    }
    masked: dict[str, Any] = {}
    for key, value in dict(params or {}).items():
        normalized_key = str(key)
        if normalized_key in sensitive_keys or _is_sensitive_param_key(normalized_key):
            masked[normalized_key] = "***"
            continue
        masked[normalized_key] = copy.deepcopy(value)
    return masked


def build_tui_audit_record(
    action: Mapping[str, Any],
    params: Mapping[str, Any],
    *,
    actor: str,
    outcome: str,
    confirmation_evidence: Mapping[str, Any] | None = None,
    reauth_evidence: Mapping[str, Any] | None = None,
    result: Mapping[str, Any] | None = None,
    error: str = "",
    occurred_at: str | None = None,
) -> dict[str, Any]:
    """Return one canonical append-only TUI audit record payload."""

    response = result.get("response") if isinstance(result, Mapping) else {}
    status_code = response.get("status_code") if isinstance(response, Mapping) else None
    missing_fields = result.get("missing_fields") if isinstance(result, Mapping) else []
    return {
        "schema_version": TUI_AUDIT_SCHEMA_VERSION,
        "occurred_at": occurred_at or _utc_now_iso(),
        "actor": str(actor or "anonymous"),
        "action_key": str(action.get("key") or ""),
        "action_label": str(action.get("label") or ""),
        "risk": str(action.get("risk") or "read"),
        "sensitive_level": str(action.get("sensitive_level") or "none"),
        "audit_required": bool(action_requires_audit(action)),
        "params": mask_sensitive_params(action, params),
        "confirmation": _audit_confirmation_payload(confirmation_evidence),
        "reauth": _audit_reauth_payload(reauth_evidence),
        "outcome": str(outcome),
        "result": {
            "status_code": status_code,
            "confirmation_required": (
                bool(result.get("confirmation_required")) if isinstance(result, Mapping) else False
            ),
            "password_challenge_required": (
                bool(result.get("password_challenge_required"))
                if isinstance(result, Mapping)
                else False
            ),
            "missing_fields": [
                str(field.get("key") or "")
                for field in (missing_fields or [])
                if isinstance(field, Mapping)
            ],
            "error": str(error or ""),
        },
    }


def verified_reauth_evidence(evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return re-authentication evidence with verified status and no credential."""

    payload = {
        key: value
        for key, value in dict(evidence or {}).items()
        if not _is_sensitive_param_key(str(key))
    }
    payload["verified"] = True
    payload.setdefault("verified_at", _utc_now_iso())
    payload.setdefault("method", "password")
    return payload


class TuiTerminalAuditSink:
    """Append canonical TUI audit records to the terminal audit repository."""

    def __init__(self, repository: TerminalAuditRepository) -> None:
        self.repository = repository

    def append(
        self,
        record: Mapping[str, Any],
        *,
        user_id: int | None,
        username: str,
        session_id: str,
    ) -> None:
        """Persist one canonical TUI audit record through the existing repository."""

        action_key = str(record.get("action_key") or "tui.action")
        entry = TerminalAuditEntry(
            user_id=user_id,
            username=username,
            session_id=session_id,
            command_name=action_key[:50],
            risk_level=str(record.get("risk") or "read"),
            mode="tui-workbench",
            params_summary=json.dumps(dict(record), ensure_ascii=False, default=str),
            confirmation_required=_confirmation_required(record),
            confirmation_status=_confirmation_status(record),
            result_status=_result_status(record),
            error_message=_error_message(record),
            duration_ms=0,
        )
        self.repository.save(entry)


def _audit_confirmation_payload(evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    if not evidence:
        return {"confirmed": False}
    return {
        "confirmed": bool(evidence.get("confirmed", True)),
        "confirmed_at": str(evidence.get("confirmed_at") or ""),
        "message": str(evidence.get("message") or ""),
    }


def _audit_reauth_payload(evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    if not evidence:
        return {"verified": False}
    return {
        "verified": bool(evidence.get("verified", False)),
        "verified_at": str(evidence.get("verified_at") or ""),
        "method": str(evidence.get("method") or "password"),
        "challenge_id": str(evidence.get("challenge_id") or ""),
    }


def _confirmation_status(record: Mapping[str, Any]) -> str:
    if (record.get("confirmation") or {}).get("confirmed"):
        return "confirmed"
    return "not_required"


def _confirmation_required(record: Mapping[str, Any]) -> bool:
    if (record.get("confirmation") or {}).get("confirmed"):
        return True
    result = record.get("result") if isinstance(record.get("result"), Mapping) else {}
    if isinstance(result, Mapping) and bool(result.get("confirmation_required")):
        return True
    return str(record.get("outcome") or "") == "blocked_confirmation_required"


def _result_status(record: Mapping[str, Any]) -> str:
    outcome = str(record.get("outcome") or "")
    if outcome == "succeeded":
        return "success"
    if outcome in {
        "blocked_confirmation_required",
        "blocked_reauth_required",
        "blocked_reauth_failed",
        "rejected_missing_fields",
    }:
        return "blocked"
    if outcome in {"failed", "failed_exception"}:
        return "error"
    return "pending"


def _error_message(record: Mapping[str, Any]) -> str:
    result = record.get("result") if isinstance(record.get("result"), Mapping) else {}
    if not isinstance(result, Mapping):
        return ""
    return str(result.get("error") or "")


def _is_sensitive_param_key(key: str) -> bool:
    normalized = str(key or "").strip().lower().replace("-", "_")
    return any(token in normalized for token in SENSITIVE_PARAM_TOKENS)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
