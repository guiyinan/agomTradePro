"""Input gate helpers for the receipt-gated financial capacity task."""

from __future__ import annotations

from uuid import UUID

from apps.data_center.application import full_market_task_support as market_task
from shared.domain.task_outcomes import TaskBusinessOutcome


def formal_scope_import_input_failure(
    *, action: str, scope_capacity_import_id: str
) -> dict[str, object] | None:
    """Return a stable task payload when formal start lacks a canonical S6 import."""

    if action != "formal_start":
        return None
    if not scope_capacity_import_id:
        reason = "financial_capacity_scope_import_required"
        return {
            **market_task.full_market_input_failure(reason),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "capacity",
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "published": 0,
            "blocked_reason": reason,
            "must_not_use_for_decision": True,
        }
    try:
        if str(UUID(scope_capacity_import_id)) != scope_capacity_import_id:
            raise ValueError("non-canonical import ID")
    except (TypeError, ValueError):
        reason = "invalid_financial_capacity_scope_import_id"
        return {
            **market_task.full_market_input_failure(reason),
            "outcome": TaskBusinessOutcome.FAILED.value,
            "stage": "input",
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "published": 0,
        }
    return None
