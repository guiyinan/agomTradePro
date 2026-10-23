"""Typed binding checks for target-difference preview selection."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.simulated_trading.application.rebalance_plan_preview_assembly import (
    finish_rebalance_plan_preview,
)
from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    RebalancePlanPreview,
    RebalancePlanPreviewItem,
    StrategyPolicyApplicability,
    TargetMode,
)
from apps.simulated_trading.application.rebalance_preview_context import (
    build_rebalance_plan_risk_context,
)
from apps.simulated_trading.application.rebalance_target_selection import (
    RebalanceTargetSelection,
    resolve_rebalance_target_selection,
)
from apps.simulated_trading.domain.temporary_rebalance_targets import (
    TemporarySecurityTargets,
    TemporarySecurityTargetWeight,
)
from apps.strategy.application.execution_gateway import StrategySelectionState


def _targets() -> TemporarySecurityTargets:
    return TemporarySecurityTargets(
        items=(TemporarySecurityTargetWeight("600000.SH", Decimal("0.10")),),
        residual_cash_weight=Decimal("0.90"),
    )


def _target_rows(targets: TemporarySecurityTargets) -> tuple[dict[str, object], ...]:
    weights = targets.exact_weight_strings()
    return (
        {
            "scope": "asset",
            "asset_code": "600000.SH",
            "target_weight": weights["600000.SH"],
            "temporary_target_source": "user_entered_temporary",
        },
        {
            "scope": "temporary_target_entry",
            "source": "user_entered_temporary",
            "target_weights": weights,
            "residual_cash_weight": "0.90",
        },
    )


def _resolve(
    *,
    state: object,
    targets: TemporarySecurityTargets | None,
    strategy_id: int | None = None,
    summary_weights: dict[str, str] | None = None,
) -> RebalanceTargetSelection:
    request = targets or _targets()
    weights = request.exact_weight_strings()
    summary = {
        "temporary_target": {
            "source": "user_entered_temporary",
            "target_weights": summary_weights if summary_weights is not None else weights,
            "residual_cash_weight": "0.90",
        }
    }
    return resolve_rebalance_target_selection(
        strategy_selection_state=state,
        strategy_id=strategy_id,
        position_rule_id=None,
        strategy_name=None,
        strategy_type=None,
        strategy_version=None,
        rule_name=None,
        max_position_pct=None,
        max_total_position_pct=None,
        stop_loss_pct=None,
        temporary_targets=targets,
        checks=_target_rows(request),
        summary=summary,
        positions=(),
    )


class _StringLikeState:
    def __eq__(self, other: object) -> bool:
        return other == "confirmed_unconfigured"


def test_confirmed_absence_requires_typed_targets_and_n_marks_strategy_policy() -> None:
    selection = _resolve(state="confirmed_unconfigured", targets=_targets())

    assert selection.strategy_selection_state == "confirmed_unconfigured"
    assert selection.strategy_policy_applicability == "not_applicable"
    assert selection.target_mode == "user_target_difference"
    assert selection.block_reason_code is None


def test_unavailable_or_contradictory_selection_cannot_enable_manual_difference() -> None:
    unavailable = _resolve(state="unavailable", targets=_targets())
    contradiction = _resolve(
        state="confirmed_unconfigured",
        targets=_targets(),
        strategy_id=4,
    )

    assert unavailable.block_reason_code == "STRATEGY_SELECTION_UNAVAILABLE"
    assert unavailable.target_mode == "unavailable"
    assert contradiction.strategy_selection_state == "unavailable"
    assert contradiction.block_reason_code == "STRATEGY_SELECTION_UNAVAILABLE"


def test_non_string_state_cannot_claim_confirmed_absence() -> None:
    selection = _resolve(state=_StringLikeState(), targets=_targets())

    assert selection.strategy_selection_state == "unavailable"
    assert selection.block_reason_code == "STRATEGY_SELECTION_UNAVAILABLE"


def test_unconfigured_selection_without_typed_targets_is_blocked() -> None:
    selection = _resolve(state="confirmed_unconfigured", targets=None)

    assert selection.block_reason_code == "TEMPORARY_TARGETS_REQUIRED"


def test_typed_target_and_serialized_summary_must_match() -> None:
    selection = _resolve(
        state="confirmed_unconfigured",
        targets=_targets(),
        summary_weights={"600000.SH": "0.15"},
    )

    assert selection.block_reason_code == "TEMPORARY_TARGET_BINDING_INVALID"


def test_incomplete_configured_strategy_keeps_strategy_policy_applicable() -> None:
    selection = _resolve(
        state="configured",
        strategy_id=27,
        targets=None,
    )

    assert selection.strategy_selection_state == "configured"
    assert selection.strategy_policy_applicability == "applicable"
    assert selection.target_mode == "strategy_rule"


def test_configured_strategy_keeps_rule_mode_for_typed_temporary_targets() -> None:
    selection = _resolve(
        state="configured",
        strategy_id=27,
        targets=_targets(),
    )

    assert selection.strategy_policy_applicability == "applicable"
    assert selection.target_mode == "strategy_rule"
    assert selection.block_reason_code is None


def test_risk_context_keeps_account_limits_separate_from_strategy_n_a() -> None:
    risk = build_rebalance_plan_risk_context(
        summary={},
        strategy_id=None,
        position_rule_id=None,
        strategy_name=None,
        strategy_type=None,
        strategy_version=None,
        rule_name=None,
        max_position_pct=None,
        max_total_position_pct=None,
        stop_loss_pct=None,
        strategy_selection_state="confirmed_unconfigured",
        account_max_position_pct=Decimal("20"),
        account_max_total_position_pct=Decimal("95"),
        account_stop_loss_pct=None,
        macro_regime="neutral",
        policy_gear="normal",
    )

    payload = risk.to_payload()
    assert payload["strategy_selection_state"] == "confirmed_unconfigured"
    assert payload["strategy_policy_applicability"] == "not_applicable"
    assert payload["strategy_max_position_pct"] is None
    assert payload["strategy_max_total_position_pct"] is None
    assert payload["account_max_position_pct"] == "20"
    assert payload["account_max_total_position_pct"] == "95"


def _preview_asset_item(
    *, action: str, status: str, target_mode: TargetMode
) -> RebalancePlanPreviewItem:
    """Build a typed target row for final preview aggregation checks."""

    return RebalancePlanPreviewItem(
        scope="asset",
        action=action,
        asset_code="600000.SH",
        asset_name="示例标的",
        asset_type="equity",
        currency_unit=None,
        quantity_unit="shares",
        current_weight=None,
        target_weight=Decimal("0.10"),
        portfolio_value=Decimal("100000.00"),
        current_amount=None,
        target_amount=None,
        suggested_amount=None,
        actionable_amount=None,
        current_quantity=None,
        target_quantity=None,
        suggested_quantity=None,
        actionable_quantity=None,
        remaining_quantity=None,
        sellable_quantity=None,
        reference_price=None,
        price_source=None,
        price_as_of=None,
        price_freshness=None,
        price_is_fallback=None,
        price_observed_at=None,
        identity=None,
        fee=None,
        drift_threshold=None,
        risk_rule_result=None,
        risk_rule_reason_code=None,
        risk_rule_entry_price_basis=None,
        status=status,
        reason_codes=("PREVIEW_INPUT_UNAVAILABLE",) if action == "blocked" else (),
        target_mode=target_mode,
    )


def _finish_preview_for_target(item: RebalancePlanPreviewItem) -> RebalancePlanPreview:
    """Run production final aggregation with known current cash facts."""

    cutoff = datetime(2026, 10, 22, 1, 30, tzinfo=UTC)
    strategy_mode = item.target_mode == "strategy_rule"
    selection_state: StrategySelectionState = (
        "configured" if strategy_mode else "confirmed_unconfigured"
    )
    risk_context = build_rebalance_plan_risk_context(
        summary={},
        strategy_id=27 if strategy_mode else None,
        position_rule_id=9 if strategy_mode else None,
        strategy_name="fixture strategy" if strategy_mode else None,
        strategy_type="rule_based" if strategy_mode else None,
        strategy_version=1 if strategy_mode else None,
        rule_name="fixture rule" if strategy_mode else None,
        max_position_pct=Decimal("20") if strategy_mode else None,
        max_total_position_pct=Decimal("95") if strategy_mode else None,
        stop_loss_pct=None,
        strategy_selection_state=selection_state,
        account_max_position_pct=Decimal("20"),
        account_max_total_position_pct=Decimal("95"),
        account_stop_loss_pct=None,
        macro_regime="neutral",
        policy_gear="normal",
    )
    applicability: StrategyPolicyApplicability = "applicable" if strategy_mode else "not_applicable"
    return finish_rebalance_plan_preview(
        cutoff=cutoff,
        financial_snapshot_read_at=cutoff,
        portfolio_value=Decimal("100000.00"),
        cash_before=Decimal("100000.00"),
        reserved_cash=Decimal("0.00"),
        available_cash_before=Decimal("100000.00"),
        projected_position_amount=Decimal("10000.00"),
        max_total_position_pct=Decimal("95") if strategy_mode else None,
        account_max_total_position_pct=Decimal("95"),
        strategy_policy_applicability=applicability,
        reason_codes=(),
        allocation_items=(),
        items=[item],
        risk_context=risk_context,
    )


@pytest.mark.parametrize("target_mode", ("strategy_rule", "user_target_difference"))
def test_blocked_target_keeps_unresolved_funding_projection_unknown(
    target_mode: TargetMode,
) -> None:
    preview = _finish_preview_for_target(
        _preview_asset_item(action="blocked", status="blocked", target_mode=target_mode)
    )

    assert preview.cash_before == Decimal("100000.00")
    assert preview.available_cash_before == Decimal("100000.00")
    assert preview.projected_cash_after_sells is None
    assert preview.projected_cash_after_buys is None
    assert preview.estimated_sell_gross is None
    assert preview.estimated_buy_gross is None
    assert preview.funding_status == "unknown"


@pytest.mark.parametrize("target_mode", ("strategy_rule", "user_target_difference"))
def test_known_hold_keeps_zero_trade_cash_projection_known(target_mode: TargetMode) -> None:
    preview = _finish_preview_for_target(
        _preview_asset_item(
            action="hold",
            status="no_rebalance_required",
            target_mode=target_mode,
        )
    )

    assert preview.status == "no_rebalance_required"
    assert preview.projected_cash_after_sells == Decimal("100000.00")
    assert preview.projected_cash_after_buys == Decimal("100000.00")
    assert preview.funding_status == "known"
