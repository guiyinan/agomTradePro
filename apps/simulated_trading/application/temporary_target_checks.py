"""Keep temporary target inputs distinct from account-bound rule evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from apps.simulated_trading.domain.entities import Position
from apps.simulated_trading.domain.temporary_rebalance_targets import (
    TemporarySecurityTargets,
)


def attach_temporary_target_checks(
    checks: Sequence[Mapping[str, object]],
    *,
    positions: list[Position],
    targets: TemporarySecurityTargets,
) -> list[dict[str, object]]:
    """Replace strategy allocation suggestions with exact per-request targets."""

    weights = targets.weights_by_code()
    exact_weights = targets.exact_weight_strings()
    held_codes = {position.asset_code.strip().upper() for position in positions}
    account_checks = [
        check for check in checks if check.get("scope") not in {"asset", "asset_class"}
    ]
    asset_checks: dict[str, list[Mapping[str, object]]] = {}
    for check in checks:
        code = check.get("asset_code")
        if check.get("scope") == "asset" and type(code) is str:
            asset_checks.setdefault(code.strip().upper(), []).append(check)

    result: list[dict[str, object]] = [dict(check) for check in account_checks]
    for asset_code, weight in weights.items():
        matching_checks = asset_checks.get(asset_code, [])
        if matching_checks:
            for source_check in matching_checks:
                item = dict(source_check)
                item["strategy_target_weight"] = item.get("target_weight")
                item["strategy_drift"] = item.get("drift")
                item["strategy_rebalance_action"] = item.get("rebalance_action")
                item["strategy_rebalance_qty_suggest"] = item.get("rebalance_qty_suggest")
                item["strategy_suggested_amount"] = item.get("suggested_amount")
                item["strategy_drift_threshold"] = item.get("drift_threshold")
                item["target_weight"] = exact_weights[asset_code]
                item["temporary_target_source"] = "user_entered_temporary"
                item["drift"] = None
                item["rebalance_action"] = None
                item["rebalance_qty_suggest"] = None
                item["suggested_amount"] = None
                result.append(item)
            continue
        if weight == 0 and asset_code not in held_codes:
            continue
        result.append(
            {
                "scope": "asset",
                "asset_code": asset_code,
                "asset_name": asset_code,
                "asset_class": None,
                "quantity": None,
                "current_price": None,
                "market_value": None,
                "weight": None,
                "strategy_target_weight": None,
                "strategy_drift": None,
                "strategy_rebalance_action": None,
                "strategy_rebalance_qty_suggest": None,
                "strategy_suggested_amount": None,
                "strategy_drift_threshold": None,
                "target_weight": exact_weights[asset_code],
                "temporary_target_source": "user_entered_temporary",
                "drift": None,
                "rebalance_action": None,
                "rebalance_qty_suggest": None,
                "suggested_amount": None,
                "drift_threshold": None,
                "rule_eval": None,
                "quantity_available": None,
            }
        )
    result.append(dict(targets.audit_record()))
    return result
