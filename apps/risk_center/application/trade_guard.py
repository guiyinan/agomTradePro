"""Pre-trade risk checks backed by risk center effective policies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apps.risk_center.application.use_cases import ResolveEffectiveRiskPolicyForAccountUseCase


@dataclass(frozen=True)
class PreTradeRiskCheckResult:
    """Result of evaluating a proposed order against centralized risk controls."""

    passed: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    effective_policy: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)


class EvaluatePreTradeRiskUseCase:
    """Evaluate a proposed order using the resolved risk-center policy for an account."""

    def __init__(
        self,
        resolver: ResolveEffectiveRiskPolicyForAccountUseCase | None = None,
    ) -> None:
        self.resolver = resolver or ResolveEffectiveRiskPolicyForAccountUseCase()

    def execute(
        self,
        *,
        account_id: int,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        account_equity: float,
        total_position_value: float,
        cash_balance: float | None = None,
        current_symbol_position_value: float = 0.0,
    ) -> PreTradeRiskCheckResult:
        """Return whether the proposed trade is allowed by the effective policy."""
        effective_policy = self.resolver.execute(account_id=account_id)
        parameters = effective_policy.get("parameters") or {}
        normalized_side = side.lower()
        order_value = max(float(quantity), 0.0) * max(float(price), 0.0)
        equity = max(float(account_equity), 0.0)
        total_position = max(float(total_position_value), 0.0)
        symbol_position = max(float(current_symbol_position_value), 0.0)
        cash = max(float(cash_balance), 0.0) if cash_balance is not None else equity - total_position

        metrics = {
            "order_value": order_value,
            "projected_total_position_pct": 0.0,
            "projected_single_position_pct": 0.0,
            "projected_cash_pct": 0.0,
        }
        if equity > 0:
            if normalized_side == "buy":
                metrics["projected_total_position_pct"] = (total_position + order_value) / equity
                metrics["projected_single_position_pct"] = (symbol_position + order_value) / equity
                metrics["projected_cash_pct"] = (cash - order_value) / equity
            else:
                metrics["projected_total_position_pct"] = max(total_position - order_value, 0.0) / equity
                metrics["projected_single_position_pct"] = max(symbol_position - order_value, 0.0) / equity
                metrics["projected_cash_pct"] = (cash + order_value) / equity

        violations: list[str] = []
        warnings: list[str] = []
        hard_exclusions = {str(item).upper() for item in parameters.get("hard_exclusions") or []}
        if symbol.upper() in hard_exclusions:
            violations.append(f"{symbol} is in risk-center hard exclusions")

        if equity <= 0:
            violations.append("account equity must be positive for risk-center pre-trade checks")

        if normalized_side == "buy":
            self._check_upper_limit(
                violations=violations,
                label="max_total_position_pct",
                value=metrics["projected_total_position_pct"],
                limit=parameters.get("max_total_position_pct"),
            )
            self._check_upper_limit(
                violations=violations,
                label="max_single_position_pct",
                value=metrics["projected_single_position_pct"],
                limit=parameters.get("max_single_position_pct"),
            )
            self._check_lower_limit(
                violations=violations,
                label="min_cash_pct",
                value=metrics["projected_cash_pct"],
                limit=parameters.get("min_cash_pct"),
            )
            if order_value > cash:
                violations.append("order value exceeds available cash")
        elif normalized_side != "sell":
            warnings.append(f"unknown side {side!r}; only hard exclusions and equity checks applied")

        return PreTradeRiskCheckResult(
            passed=not violations,
            violations=violations,
            warnings=warnings,
            effective_policy=effective_policy,
            metrics=metrics,
        )

    @staticmethod
    def _check_upper_limit(
        *,
        violations: list[str],
        label: str,
        value: float,
        limit: Any,
    ) -> None:
        if limit is None:
            return
        try:
            numeric_limit = float(limit)
        except (TypeError, ValueError):
            return
        if value > numeric_limit:
            violations.append(f"{label} exceeded: projected={value:.4f}, limit={numeric_limit:.4f}")

    @staticmethod
    def _check_lower_limit(
        *,
        violations: list[str],
        label: str,
        value: float,
        limit: Any,
    ) -> None:
        if limit is None:
            return
        try:
            numeric_limit = float(limit)
        except (TypeError, ValueError):
            return
        if value < numeric_limit:
            violations.append(f"{label} breached: projected={value:.4f}, limit={numeric_limit:.4f}")
