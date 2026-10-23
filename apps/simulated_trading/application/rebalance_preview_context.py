"""Project existing inspection and strategy evidence into typed preview context."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal

from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    RebalancePlanRiskContext,
    StrategyPolicyApplicability,
)
from apps.simulated_trading.application.rebalance_preview_valuation import (
    _decimal_value,
    _optional_text,
)
from apps.strategy.application.execution_gateway import StrategySelectionState

DEFAULT_RISK_PER_TRADE_PCT = 0.008
DEFAULT_ENTRY_BUFFER_PCT = 0.002


def build_position_rule_context(
    *,
    current_price: float,
    entry_price: float,
    account_equity: float,
) -> dict[str, float]:
    """Return only observed inputs; absent rule variables remain unavailable."""

    return {
        "current_price": current_price,
        "entry_price": entry_price,
        "account_equity": account_equity,
    }


def build_rebalance_plan_risk_context(
    *,
    summary: Mapping[str, object],
    strategy_id: int | None,
    position_rule_id: int | None,
    strategy_name: str | None,
    strategy_type: str | None,
    strategy_version: int | None,
    rule_name: str | None,
    max_position_pct: Decimal | None,
    max_total_position_pct: Decimal | None,
    stop_loss_pct: Decimal | None,
    strategy_selection_state: StrategySelectionState,
    account_max_position_pct: Decimal | None,
    account_max_total_position_pct: Decimal | None,
    account_stop_loss_pct: Decimal | None,
    macro_regime: str,
    policy_gear: str,
) -> RebalancePlanRiskContext:
    """Copy existing inspection and strategy limits without inferring missing metadata."""

    selection_state: StrategySelectionState
    strategy_policy_applicability: StrategyPolicyApplicability
    if strategy_selection_state == "configured":
        selection_state = "configured"
        strategy_policy_applicability = "applicable"
    elif strategy_selection_state == "confirmed_unconfigured":
        selection_state = "confirmed_unconfigured"
        strategy_policy_applicability = "not_applicable"
    else:
        selection_state = "unavailable"
        strategy_policy_applicability = "unknown"

    raw_allocation = summary.get("target_allocation")
    allocation: dict[str, str] | None = None
    if isinstance(raw_allocation, dict):
        allocation = {
            key: str(value)
            for key, value in raw_allocation.items()
            if type(key) is str and _decimal_value(value) is not None
        }
    return RebalancePlanRiskContext(
        strategy_id=strategy_id,
        position_rule_id=position_rule_id,
        strategy_name=strategy_name,
        strategy_type=strategy_type,
        strategy_version=strategy_version,
        rule_name=rule_name,
        risk_profile=_optional_text(summary.get("risk_profile")),
        macro_regime=macro_regime or None,
        policy_gear=policy_gear or None,
        max_position_pct=max_position_pct,
        max_total_position_pct=max_total_position_pct,
        stop_loss_pct=stop_loss_pct,
        account_max_position_pct=account_max_position_pct,
        account_max_total_position_pct=account_max_total_position_pct,
        account_stop_loss_pct=account_stop_loss_pct,
        target_allocation=allocation,
        pulse=object_payload(summary.get("pulse")),
        rule_version=None,
        rule_effective_from=None,
        rule_effective_until=None,
        strategy_selection_state=selection_state,
        strategy_policy_applicability=strategy_policy_applicability,
    )


def object_payload(value: object) -> dict[str, object] | None:
    """Copy a JSON object without passing arbitrary runtime objects to the response."""

    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        return None
    return {key: item for key, item in value.items() if _json_value(item)}


def quantity_unit(asset_type: str | None) -> str:
    """Expose a share label only for an explicit equity position type."""

    return "shares" if asset_type == "equity" else "units" if asset_type else "unknown"


def datetime_text(value: datetime | None) -> str | None:
    """Preserve the source timezone and absence of every optional clock."""

    return value.isoformat() if value is not None else None


def normalize_cutoff(value: datetime) -> datetime:
    """Require one aware cutoff and normalize it to UTC."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("rebalance preview cutoff must be timezone-aware")
    return value.astimezone(UTC)


def string_tuple(value: object) -> tuple[str, ...]:
    """Narrow reason codes from a stored inspection JSON list."""

    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if type(item) is str and item)


def _json_value(value: object) -> bool:
    """Recognize values accepted by the inspection JSON boundary."""

    if value is None or type(value) in (str, int, float, bool):
        return True
    if isinstance(value, list):
        return all(_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(type(key) is str and _json_value(item) for key, item in value.items())
    return False


__all__: tuple[str, ...] = (
    "DEFAULT_ENTRY_BUFFER_PCT",
    "DEFAULT_RISK_PER_TRADE_PCT",
    "build_position_rule_context",
    "build_rebalance_plan_risk_context",
    "datetime_text",
    "normalize_cutoff",
    "object_payload",
    "quantity_unit",
    "string_tuple",
)
