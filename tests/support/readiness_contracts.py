"""Reusable builders for personal-readiness acceptance contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def build_formal_acceptance_window_result(
    *,
    task_path: str,
    required_days: int = 20,
    quality_overrides: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Build one fully accepted formal window with optional quality gaps."""

    quality = {
        "formal_record_count": required_days,
        "formal_workspace_core_record_count": required_days,
        "formal_workspace_core_ok_record_count": required_days,
        "formal_workspace_core_missing_record_count": 0,
        "formal_qlib_record_count": required_days,
        "formal_qlib_ok_record_count": required_days,
        "formal_qlib_missing_record_count": 0,
        "formal_qlib_blocked_record_count": 0,
        "formal_alpha_workspace_record_count": required_days,
        "formal_alpha_workspace_ok_record_count": required_days,
        "formal_alpha_workspace_missing_record_count": 0,
        "formal_decision_data_record_count": required_days,
        "formal_decision_data_ok_record_count": required_days,
        "formal_decision_data_missing_record_count": 0,
        "formal_decision_data_blocked_record_count": 0,
        "formal_quote_freshness_record_count": required_days,
        "formal_quote_freshness_ok_record_count": required_days,
        "formal_quote_freshness_missing_record_count": 0,
        "formal_quote_freshness_stale_record_count": 0,
        "formal_quote_freshness_blocked_record_count": 0,
        "formal_risk_record_count": required_days,
        "formal_risk_ok_record_count": required_days,
        "formal_risk_missing_record_count": 0,
        "formal_risk_account_count": required_days * 2,
        "formal_risk_report_ok_account_count": required_days * 2,
        "formal_pre_trade_ok_account_count": required_days * 2,
        "formal_pre_trade_missing_account_count": 0,
        "formal_post_investment_ok_account_count": required_days * 2,
        "formal_post_investment_missing_account_count": 0,
        "weekly_report_persistence_ok_record_count": 4,
        "weekly_report_persistence_ok_account_count": 8,
        "weekly_report_persistence_missing_record_count": 0,
        "weekly_report_persistence_warning_record_count": 0,
    }
    quality.update(quality_overrides or {})
    return {
        "status": "accepted",
        "required_days": required_days,
        "accepted_days": required_days,
        "remaining_days": 0,
        "next_required_date": None,
        "next_required_reason": "window_accepted",
        "accepted_evidence": [
            {
                "target_date": f"2026-07-{day:02d}",
                "evidence_mode": "formal",
                "acceptance_candidate": True,
                "trigger_source": "scheduler",
                "trigger_task_id": f"task-{day}",
                "trigger_task_name": task_path,
            }
            for day in range(1, required_days + 1)
        ],
        "accepted_evidence_quality": quality,
        "blocking_issues": [],
    }
