"""Evidence summary helpers for personal readiness status reporting."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from django.conf import settings

from apps.operational_readiness.application import status_services
from apps.operational_readiness.domain.evidence_contract import (
    classify_operation_context,
)


def _collect_latest_evidence(
    *,
    output_dir: Path,
    formal_candidate_only: bool = False,
) -> dict[str, Any]:
    root = Path(settings.BASE_DIR) / output_dir if not output_dir.is_absolute() else output_dir
    latest_payload: dict[str, Any] | None = None
    latest_date: date | None = None
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            target_date = date.fromisoformat(str(payload["target_date"]))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        operation_context = dict(payload.get("operation_context") or {})
        if formal_candidate_only and not _is_acceptance_candidate(
            operation_context=operation_context
        ):
            continue
        if latest_date is None or target_date > latest_date:
            latest_date = target_date
            latest_payload = payload

    if latest_payload is None:
        return {"status": "missing", "target_date": None}

    return _summarize_evidence_payload(latest_payload)


def _summarize_evidence_payload(payload: dict[str, Any]) -> dict[str, Any]:
    summary = dict(payload.get("summary") or {})
    operation_context = dict(payload.get("operation_context") or {})
    classification = _classify_evidence(operation_context=operation_context)
    return {
        "status": payload.get("status"),
        "target_date": payload.get("target_date"),
        "operation_context": operation_context or None,
        "formal_evidence": classification["formal_evidence"],
        "acceptance_candidate": classification["acceptance_candidate"],
        "evidence_mode": classification["evidence_mode"],
        "trigger_source": classification["trigger_source"],
        "trigger_task_id": classification["trigger_task_id"],
        "trigger_task_name": classification["trigger_task_name"],
        "summary": {
            "system_status": summary.get("system_status"),
            "qlib_status": summary.get("qlib_status"),
            "qlib_readiness": status_services.summarize_evidence_qlib_readiness(payload),
            "workspace_status": summary.get("workspace_status"),
            "target_count": summary.get("target_count"),
            "account_evidence": status_services.summarize_evidence_accounts(payload),
            "decision_data": status_services.summarize_evidence_decision_data(payload),
            "macro_context": status_services.summarize_evidence_macro_context(payload),
            "alpha_workspace_consistency": status_services.summarize_evidence_alpha_workspace(
                payload
            ),
            "workspace_components": status_services.summarize_evidence_workspace_components(
                payload
            ),
        },
    }


def _classify_evidence(*, operation_context: dict[str, Any]) -> dict[str, Any]:
    return classify_operation_context(operation_context)


def _is_acceptance_candidate(*, operation_context: dict[str, Any]) -> bool:
    return bool(_classify_evidence(operation_context=operation_context)["acceptance_candidate"])


def _is_formal_evidence(*, operation_context: dict[str, Any]) -> bool | None:
    return classify_operation_context(operation_context)["formal_evidence"]
