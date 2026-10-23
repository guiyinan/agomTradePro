"""Resolve which read-only target calculation is supported by inspected evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    StrategyPolicyApplicability,
    TargetMode,
)
from apps.simulated_trading.domain.entities import Position
from apps.simulated_trading.domain.temporary_rebalance_targets import TemporarySecurityTargets
from apps.strategy.application.execution_gateway import StrategySelectionState


@dataclass(frozen=True, slots=True)
class RebalanceTargetSelection:
    """Validated strategy applicability and target mode for a preview request."""

    strategy_selection_state: StrategySelectionState
    strategy_policy_applicability: StrategyPolicyApplicability
    target_mode: TargetMode
    block_reason_code: str | None


def resolve_rebalance_target_selection(
    *,
    strategy_selection_state: object,
    strategy_id: int | None,
    position_rule_id: int | None,
    strategy_name: str | None,
    strategy_type: str | None,
    strategy_version: int | None,
    rule_name: str | None,
    max_position_pct: Decimal | None,
    max_total_position_pct: Decimal | None,
    stop_loss_pct: Decimal | None,
    temporary_targets: TemporarySecurityTargets | None,
    checks: tuple[Mapping[str, object], ...],
    summary: Mapping[str, object],
    positions: tuple[Position, ...],
) -> RebalanceTargetSelection:
    """Require consistent selection proof and bind request targets to typed input."""

    state = _normalize_strategy_selection_state(strategy_selection_state)
    if state == "configured" and (type(strategy_id) is not int or strategy_id <= 0):
        state = "unavailable"
    if state == "confirmed_unconfigured" and not _selection_fields_empty(
        strategy_id=strategy_id,
        position_rule_id=position_rule_id,
        strategy_name=strategy_name,
        strategy_type=strategy_type,
        strategy_version=strategy_version,
        rule_name=rule_name,
        max_position_pct=max_position_pct,
        max_total_position_pct=max_total_position_pct,
        stop_loss_pct=stop_loss_pct,
    ):
        state = "unavailable"
    if state == "unavailable":
        return RebalanceTargetSelection(
            state, "unknown", "unavailable", "STRATEGY_SELECTION_UNAVAILABLE"
        )
    if state == "confirmed_unconfigured" and temporary_targets is None:
        return RebalanceTargetSelection(
            state,
            "not_applicable",
            "user_target_difference",
            "TEMPORARY_TARGETS_REQUIRED",
        )
    if temporary_targets is None and _has_temporary_target_evidence(checks, summary):
        return RebalanceTargetSelection(
            state,
            _applicability(state),
            "strategy_rule",
            "TEMPORARY_TARGET_CONTEXT_UNAVAILABLE",
        )
    if temporary_targets is not None and not _temporary_target_context_matches(
        targets=temporary_targets,
        checks=checks,
        summary=summary,
        positions=positions,
    ):
        return RebalanceTargetSelection(
            state,
            _applicability(state),
            "user_target_difference" if state == "confirmed_unconfigured" else "strategy_rule",
            "TEMPORARY_TARGET_BINDING_INVALID",
        )
    target_mode: TargetMode = (
        "user_target_difference" if state == "confirmed_unconfigured" else "strategy_rule"
    )
    return RebalanceTargetSelection(state, _applicability(state), target_mode, None)


def _normalize_strategy_selection_state(value: object) -> StrategySelectionState:
    """Keep unknown and malformed strategy selection states unavailable."""

    if type(value) is not str:
        return "unavailable"
    if value == "configured":
        return "configured"
    if value == "confirmed_unconfigured":
        return "confirmed_unconfigured"
    return "unavailable"


def _applicability(state: StrategySelectionState) -> StrategyPolicyApplicability:
    """Map a verified selection state to its policy applicability marker."""

    if state == "configured":
        return "applicable"
    if state == "confirmed_unconfigured":
        return "not_applicable"
    return "unknown"


def _selection_fields_empty(
    *,
    strategy_id: int | None,
    position_rule_id: int | None,
    strategy_name: str | None,
    strategy_type: str | None,
    strategy_version: int | None,
    rule_name: str | None,
    max_position_pct: Decimal | None,
    max_total_position_pct: Decimal | None,
    stop_loss_pct: Decimal | None,
) -> bool:
    """Reject absence proof that contradicts any copied strategy field."""

    return all(
        value is None
        for value in (
            strategy_id,
            position_rule_id,
            strategy_name,
            strategy_type,
            strategy_version,
            rule_name,
            max_position_pct,
            max_total_position_pct,
            stop_loss_pct,
        )
    )


def _has_temporary_target_evidence(
    checks: tuple[Mapping[str, object], ...],
    summary: Mapping[str, object],
) -> bool:
    """Detect temporary target markers that lack their validated value object."""

    return summary.get("temporary_target") is not None or any(
        check.get("temporary_target_source") == "user_entered_temporary"
        or check.get("scope") == "temporary_target_entry"
        for check in checks
    )


def _temporary_target_context_matches(
    *,
    targets: TemporarySecurityTargets,
    checks: tuple[Mapping[str, object], ...],
    summary: Mapping[str, object],
    positions: tuple[Position, ...],
) -> bool:
    """Bind checked rows, audit row, and summary to the typed target object."""

    if type(targets) is not TemporarySecurityTargets:
        return False
    expected = targets.exact_weight_strings()
    expected_residual = format(targets.residual_cash_weight, "f")
    raw_summary = summary.get("temporary_target")
    if not isinstance(raw_summary, Mapping):
        return False
    raw_summary_weights = raw_summary.get("target_weights")
    if (
        raw_summary.get("source") != "user_entered_temporary"
        or raw_summary.get("residual_cash_weight") != expected_residual
        or not isinstance(raw_summary_weights, Mapping)
        or dict(raw_summary_weights) != expected
    ):
        return False

    audit_rows = [check for check in checks if check.get("scope") == "temporary_target_entry"]
    if len(audit_rows) != 1:
        return False
    audit = audit_rows[0]
    if (
        audit.get("source") != "user_entered_temporary"
        or audit.get("target_weights") != expected
        or audit.get("residual_cash_weight") != expected_residual
    ):
        return False

    held_codes = {
        code
        for position in positions
        if type(position) is Position
        if (code := _normalized_code(position.asset_code)) is not None
    }
    typed_weights = targets.weights_by_code()
    expected_visible = {
        code: weight
        for code, weight in expected.items()
        if typed_weights[code] > 0 or code in held_codes
    }
    target_rows = [
        check
        for check in checks
        if check.get("temporary_target_source") == "user_entered_temporary"
    ]
    actual: dict[str, str] = {}
    for row in target_rows:
        code = _normalized_code(row.get("asset_code"))
        weight = row.get("target_weight")
        if row.get("scope") != "asset" or code is None or code in actual or type(weight) is not str:
            return False
        actual[code] = weight
    return actual == expected_visible


def _normalized_code(value: object) -> str | None:
    """Normalize a canonical target row key without accepting arbitrary objects."""

    if type(value) is not str:
        return None
    code = value.strip().upper()
    return code if code else None


__all__: tuple[str, ...] = ("RebalanceTargetSelection", "resolve_rebalance_target_selection")
