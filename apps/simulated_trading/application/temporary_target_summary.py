"""Assemble temporary inspection targets without inventing computed trade facts."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, localcontext

from apps.simulated_trading.domain.entities import SimulatedAccount
from apps.simulated_trading.domain.temporary_rebalance_targets import TemporarySecurityTargets


def build_temporary_target_summary(
    *,
    account: SimulatedAccount,
    checks_count: int,
    targets: TemporarySecurityTargets,
    strategy_summary_context: Mapping[str, object],
    positions_count: int | None = None,
) -> dict[str, object]:
    """Keep exact target weights, source risk context, and unknown trade facts distinct."""

    risk_profile = strategy_summary_context.get("risk_profile")
    pulse_context = strategy_summary_context.get("pulse")
    strategy_target_allocation = strategy_summary_context.get("target_allocation")
    if type(risk_profile) is not str:
        risk_profile = None
    if not isinstance(pulse_context, dict):
        pulse_context = None
    if not isinstance(strategy_target_allocation, dict):
        strategy_target_allocation = {}
    with localcontext() as context:
        context.prec = 32
        target_weight_total = Decimal("1") - targets.residual_cash_weight
    return {
        "positions_count": positions_count,
        "checks_count": checks_count,
        "rebalance_required_count": None,
        "asset_class_rebalance_required_count": None,
        "asset_rebalance_required_count": None,
        "rebalance_assets": None,
        "rebalance_asset_classes": None,
        "max_abs_drift": None,
        "target_allocation": None,
        "strategy_target_allocation": strategy_target_allocation,
        "risk_profile": risk_profile,
        "pulse": pulse_context,
        "total_value": float(account.total_value or Decimal("0")),
        "current_cash": float(account.current_cash or Decimal("0")),
        "current_market_value": float(account.current_market_value or Decimal("0")),
        "temporary_target": {
            "source": "user_entered_temporary",
            "target_weights": targets.exact_weight_strings(),
            "security_count": len(targets.items),
            "security_weight_total": format(target_weight_total, "f"),
            "residual_cash_weight": format(targets.residual_cash_weight, "f"),
            "assessment": "delegated_to_read_only_preview",
            "rebalance_status": "unknown_until_preview",
            "quantity_status": "unknown_until_preview",
        },
    }
