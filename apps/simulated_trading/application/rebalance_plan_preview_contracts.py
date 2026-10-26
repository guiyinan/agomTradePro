"""Typed response contracts for a read-only simulated rebalance preview."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from apps.risk_center.domain.m1_rebalance_risk_policy import M1RiskFalsification
from apps.strategy.application.execution_gateway import StrategySelectionState

StrategyPolicyApplicability = Literal["applicable", "not_applicable", "unknown"]
TargetMode = Literal["strategy_rule", "user_target_difference", "unavailable"]


@dataclass(frozen=True, slots=True)
class RebalancePlanPreviewItem:
    """One instrument or amount-only allocation row in a plan preview."""

    scope: Literal["asset", "asset_class"]
    action: str
    asset_code: str
    asset_name: str
    asset_type: str | None
    currency_unit: str | None
    quantity_unit: str
    current_weight: Decimal | None
    target_weight: Decimal | None
    portfolio_value: Decimal | None
    current_amount: Decimal | None
    target_amount: Decimal | None
    suggested_amount: Decimal | None
    actionable_amount: Decimal | None
    current_quantity: Decimal | None
    target_quantity: Decimal | None
    suggested_quantity: Decimal | None
    actionable_quantity: Decimal | None
    remaining_quantity: Decimal | None
    sellable_quantity: Decimal | None
    reference_price: Decimal | None
    price_source: str | None
    price_as_of: date | None
    price_freshness: str | None
    price_is_fallback: bool | None
    price_observed_at: datetime | None
    identity: dict[str, object] | None
    fee: dict[str, object] | None
    drift_threshold: Decimal | None
    risk_rule_result: dict[str, object] | None
    risk_rule_reason_code: str | None
    risk_rule_entry_price_basis: str | None
    status: str
    reason_codes: tuple[str, ...]
    quantity_rule: dict[str, object] | None = None
    reserved_sell_quantity: Decimal | None = None
    classification_evidence: dict[str, object] | None = None
    target_mode: TargetMode | None = None

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-safe view while preserving absent evidence as null."""

        return {
            "scope": self.scope,
            "action": self.action,
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "asset_type": self.asset_type,
            "currency_unit": self.currency_unit,
            "quantity_unit": self.quantity_unit,
            "current_weight": _decimal_text(self.current_weight),
            "target_weight": _decimal_text(self.target_weight),
            "portfolio_value": _decimal_text(self.portfolio_value),
            "current_amount": _decimal_text(self.current_amount),
            "target_amount": _decimal_text(self.target_amount),
            "suggested_amount": _decimal_text(self.suggested_amount),
            "actionable_amount": _decimal_text(self.actionable_amount),
            "current_quantity": _decimal_text(self.current_quantity),
            "target_quantity": _decimal_text(self.target_quantity),
            "suggested_quantity": _decimal_text(self.suggested_quantity),
            "actionable_quantity": _decimal_text(self.actionable_quantity),
            "remaining_quantity": _decimal_text(self.remaining_quantity),
            "sellable_quantity": _decimal_text(self.sellable_quantity),
            "reserved_sell_quantity": _decimal_text(self.reserved_sell_quantity),
            "reference_price": _decimal_text(self.reference_price),
            "price_source": self.price_source,
            "price_as_of": self.price_as_of.isoformat() if self.price_as_of else None,
            "price_freshness": self.price_freshness,
            "price_is_fallback": self.price_is_fallback,
            "price_observed_at": _datetime_text(self.price_observed_at),
            "identity": dict(self.identity) if self.identity is not None else None,
            "fee": dict(self.fee) if self.fee is not None else None,
            "drift_threshold": _decimal_text(self.drift_threshold),
            "risk_rule_result": (
                dict(self.risk_rule_result) if self.risk_rule_result is not None else None
            ),
            "risk_rule_reason_code": self.risk_rule_reason_code,
            "risk_rule_entry_price_basis": self.risk_rule_entry_price_basis,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "quantity_rule": dict(self.quantity_rule) if self.quantity_rule is not None else None,
            "classification_evidence": (
                dict(self.classification_evidence)
                if self.classification_evidence is not None
                else None
            ),
            "target_mode": self.target_mode,
        }


@dataclass(frozen=True, slots=True)
class RebalancePlanRiskContext:
    """Risk inputs copied from the persisted inspection report without inference."""

    strategy_id: int | None
    position_rule_id: int | None
    strategy_name: str | None
    strategy_type: str | None
    strategy_version: int | None
    rule_name: str | None
    risk_profile: str | None
    macro_regime: str | None
    policy_gear: str | None
    max_position_pct: Decimal | None
    max_total_position_pct: Decimal | None
    stop_loss_pct: Decimal | None
    account_max_position_pct: Decimal | None
    account_max_total_position_pct: Decimal | None
    account_stop_loss_pct: Decimal | None
    target_allocation: dict[str, str] | None
    pulse: dict[str, object] | None
    rule_version: str | None
    rule_effective_from: date | None
    rule_effective_until: date | None
    strategy_selection_state: StrategySelectionState = "unavailable"
    strategy_policy_applicability: StrategyPolicyApplicability = "unknown"
    risk_policy_version: str | None = None
    risk_policy_effective_from: datetime | None = None
    risk_policy_effective_until: datetime | None = None
    risk_policy_known_at: datetime | None = None
    risk_policy_qualification_status: str = "missing"
    risk_policy_reason_codes: tuple[str, ...] = ()
    risk_falsification: M1RiskFalsification | None = None

    def to_payload(self) -> dict[str, object]:
        """Return the exact existing report evidence and explicit unknown rule metadata."""

        return {
            "strategy_id": self.strategy_id,
            "position_rule_id": self.position_rule_id,
            "strategy_name": self.strategy_name,
            "strategy_type": self.strategy_type,
            "strategy_version": self.strategy_version,
            "rule_name": self.rule_name,
            "risk_profile": self.risk_profile,
            "macro_regime": self.macro_regime,
            "policy_gear": self.policy_gear,
            "max_position_pct": _decimal_text(self.max_position_pct),
            "max_total_position_pct": _decimal_text(self.max_total_position_pct),
            "stop_loss_pct": _decimal_text(self.stop_loss_pct),
            "strategy_max_position_pct": _decimal_text(self.max_position_pct),
            "strategy_max_total_position_pct": _decimal_text(self.max_total_position_pct),
            "strategy_stop_loss_pct": _decimal_text(self.stop_loss_pct),
            "account_max_position_pct": _decimal_text(self.account_max_position_pct),
            "account_max_total_position_pct": _decimal_text(self.account_max_total_position_pct),
            "account_stop_loss_pct": _decimal_text(self.account_stop_loss_pct),
            "target_allocation": (
                dict(self.target_allocation) if self.target_allocation is not None else None
            ),
            "pulse": dict(self.pulse) if self.pulse is not None else None,
            "rule_version": self.rule_version,
            "rule_effective_from": (
                self.rule_effective_from.isoformat() if self.rule_effective_from else None
            ),
            "rule_effective_until": (
                self.rule_effective_until.isoformat() if self.rule_effective_until else None
            ),
            "risk_policy_version": self.risk_policy_version,
            "risk_policy_effective_from": _datetime_text(self.risk_policy_effective_from),
            "risk_policy_effective_until": _datetime_text(self.risk_policy_effective_until),
            "risk_policy_known_at": _datetime_text(self.risk_policy_known_at),
            "risk_policy_qualification_status": self.risk_policy_qualification_status,
            "risk_policy_reason_codes": list(self.risk_policy_reason_codes),
            "risk_falsification": _risk_falsification_payload(self.risk_falsification),
            "strategy_selection_state": self.strategy_selection_state,
            "strategy_policy_applicability": self.strategy_policy_applicability,
        }


@dataclass(frozen=True, slots=True)
class RebalancePlanPreview:
    """Read-only, per-account preview; it is not an executable TransitionPlan."""

    status: str
    reason_codes: tuple[str, ...]
    as_of: datetime
    financial_snapshot_read_at: datetime | None
    portfolio_value: Decimal | None
    cash_before: Decimal | None
    reserved_cash: Decimal | None
    available_cash_before: Decimal | None
    projected_cash_after_sells: Decimal | None
    estimated_sell_gross: Decimal | None
    estimated_sell_fees: Decimal | None
    estimated_sell_net: Decimal | None
    estimated_buy_gross: Decimal | None
    estimated_buy_fees: Decimal | None
    estimated_buy_total: Decimal | None
    projected_cash_after_buys: Decimal | None
    funding_status: str
    sell_before_buy: dict[str, object]
    risk_context: RebalancePlanRiskContext
    allocation_items: tuple[RebalancePlanPreviewItem, ...]
    asset_items: tuple[RebalancePlanPreviewItem, ...]

    def to_payload(self) -> dict[str, object]:
        """Return the complete user-facing, JSON-safe preview."""

        return {
            "plan_kind": "rebalance_preview",
            "read_only": True,
            "execution_submitted": False,
            "must_not_execute": True,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "as_of": self.as_of.isoformat(),
            "financial_snapshot_read_at": _datetime_text(self.financial_snapshot_read_at),
            "portfolio_value": _decimal_text(self.portfolio_value),
            "cash_before": _decimal_text(self.cash_before),
            "reserved_cash": _decimal_text(self.reserved_cash),
            "available_cash_before": _decimal_text(self.available_cash_before),
            "currency_unit": None,
            "projected_cash_after_sells": _decimal_text(self.projected_cash_after_sells),
            "estimated_sell_gross": _decimal_text(self.estimated_sell_gross),
            "estimated_sell_fees": _decimal_text(self.estimated_sell_fees),
            "estimated_sell_net": _decimal_text(self.estimated_sell_net),
            "estimated_buy_gross": _decimal_text(self.estimated_buy_gross),
            "estimated_buy_fees": _decimal_text(self.estimated_buy_fees),
            "estimated_buy_total": _decimal_text(self.estimated_buy_total),
            "projected_cash_after_buys": _decimal_text(self.projected_cash_after_buys),
            "funding_status": self.funding_status,
            "sell_before_buy": dict(self.sell_before_buy),
            "risk_context": self.risk_context.to_payload(),
            "allocation_items": [item.to_payload() for item in self.allocation_items],
            "asset_items": [item.to_payload() for item in self.asset_items],
        }


def _decimal_text(value: Decimal | None) -> str | None:
    """Serialize optional finite decimal values without converting them to floats."""

    return str(value) if value is not None and value.is_finite() else None


def _datetime_text(value: datetime | None) -> str | None:
    """Preserve the source timezone and absence of every optional clock."""

    return value.isoformat() if value is not None else None


def _risk_falsification_payload(
    evidence: M1RiskFalsification | None,
) -> dict[str, object] | None:
    """Serialize actual policy conditions and observations as JSON-safe values."""

    if evidence is None:
        return None
    return {
        "risk_policy_version": evidence.risk_policy_version,
        "effective_from": _datetime_text(evidence.effective_from),
        "effective_until": _datetime_text(evidence.effective_until),
        "known_at": _datetime_text(evidence.known_at),
        "revoked_at": _datetime_text(evidence.revoked_at),
        "status": evidence.status,
        "reason_codes": list(evidence.reason_codes),
        "conditions": [
            {
                "dimension": condition.dimension,
                "policy_applicability": condition.policy_applicability.value,
                "observation_applicability": condition.observation_applicability.value,
                "predicate": condition.predicate,
                "threshold_pct": _decimal_text(condition.threshold_pct),
                "observed_pct": _decimal_text(condition.observed_pct),
                "outcome": condition.outcome.value,
            }
            for condition in evidence.conditions
        ],
    }


__all__: tuple[str, ...] = (
    "RebalancePlanPreview",
    "RebalancePlanPreviewItem",
    "RebalancePlanRiskContext",
    "StrategyPolicyApplicability",
    "TargetMode",
)
