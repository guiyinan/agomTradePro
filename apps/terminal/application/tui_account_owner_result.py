"""Route owned-account JSON results to their existing task projections."""

from __future__ import annotations

from typing import Any

from apps.terminal.application.tui_fee_correction_result import project_fee_correction_result
from apps.terminal.application.tui_holding_disclosure_result import (
    project_tui_holding_disclosure_result,
)
from apps.terminal.application.tui_order_history_result import (
    project_tui_order_history_result,
)
from apps.terminal.application.tui_order_match_result import project_tui_order_match_result
from apps.terminal.application.tui_owner_order_submission_result import (
    project_tui_owner_order_submission_result,
)
from apps.terminal.application.tui_portfolio_risk_result import project_portfolio_risk_result
from apps.terminal.application.tui_rebalance_plan_result import project_rebalance_plan_result
from apps.terminal.application.tui_simulated_corporate_action_consent_result import (
    CORPORATE_ACTION_CONSENT_CONFIRM_ACTION_KEY,
    CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY,
    CORPORATE_ACTION_CONSENT_WITHDRAW_ACTION_KEY,
    CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY,
    project_simulated_corporate_action_consent_result,
)


def project_account_owner_result(
    action_key: str,
    payload: object,
    *,
    status_code: int,
    request_params: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Dispatch only recognized account tasks, preserving each original JSON validator."""
    if action_key in {
        CORPORATE_ACTION_CONSENT_PREPARE_ACTION_KEY,
        CORPORATE_ACTION_CONSENT_CONFIRM_ACTION_KEY,
        CORPORATE_ACTION_CONSENT_WITHDRAW_PREPARE_ACTION_KEY,
        CORPORATE_ACTION_CONSENT_WITHDRAW_ACTION_KEY,
    }:
        return project_simulated_corporate_action_consent_result(
            action_key, payload, http_status=status_code, requested_params=request_params
        )
    if action_key.startswith("rebalance-plan.") and action_key not in {
        "rebalance-plan.order-confirm",
        "rebalance-plan.order-by-key",
    }:
        return dict(
            project_rebalance_plan_result(
                action_key,
                payload,
                requested_params=request_params,
                http_status=status_code,
            )
        )
    if action_key == "simulated-trading.holding-disclosures":
        return project_tui_holding_disclosure_result(
            action_key, payload, http_status=status_code, requested_params=request_params
        )
    if action_key in {
        "simulated-trading.portfolio-risk-report",
        "simulated-trading.portfolio-pressure-run",
    }:
        return project_portfolio_risk_result(payload, http_status=status_code)
    if action_key in {"rebalance-plan.order-confirm", "rebalance-plan.order-by-key"}:
        owner_action_key = (
            "simulated-trading.order-confirm"
            if action_key == "rebalance-plan.order-confirm"
            else "simulated-trading.order-by-key"
        )
        return project_tui_owner_order_submission_result(
            owner_action_key,
            payload,
            http_status=status_code,
            requested_params=request_params,
        )
    if action_key in {
        "simulated-trading.fee-correction-policy",
        "simulated-trading.fee-correction-policy-save",
        "simulated-trading.fee-correction-policy-disable",
        "simulated-trading.fee-correction-preview",
        "simulated-trading.fee-correction-confirm",
        "simulated-trading.fee-correction-head",
        "simulated-trading.fee-correction-recover",
        "simulated-trading.fee-correction-discover",
    }:
        return project_fee_correction_result(
            action_key, payload, http_status=status_code, requested_params=request_params
        )
    if action_key in {
        "simulated-trading.orders",
        "simulated-trading.order-fills",
        "simulated-trading.order-decisions",
        "simulated-trading.order-decision-apply",
        "simulated-trading.order-cancel",
    }:
        return project_tui_order_history_result(
            action_key, payload, http_status=status_code, requested_params=request_params
        )
    if action_key in {
        "simulated-trading.account-stop-loss-check",
        "simulated-trading.order-entry-orders",
        "simulated-trading.order-preview",
        "simulated-trading.order-confirm",
        "simulated-trading.order-by-key",
    }:
        return project_tui_owner_order_submission_result(
            action_key, payload, http_status=status_code, requested_params=request_params
        )
    if action_key == "simulated-trading.order-match":
        return project_tui_order_match_result(
            payload, http_status=status_code, requested_params=request_params
        )
    return None
