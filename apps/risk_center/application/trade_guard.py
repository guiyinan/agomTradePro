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


@dataclass(frozen=True)
class PostInvestmentRiskCheckResult:
    """Result of monitoring an existing account portfolio after trades are filled."""

    status: str
    passed: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    position_alerts: list[dict[str, Any]] = field(default_factory=list)
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


class EvaluatePostInvestmentRiskUseCase:
    """Evaluate current holdings against the resolved risk-center policy."""

    def __init__(
        self,
        resolver: ResolveEffectiveRiskPolicyForAccountUseCase | None = None,
    ) -> None:
        self.resolver = resolver or ResolveEffectiveRiskPolicyForAccountUseCase()

    def execute(
        self,
        *,
        account_id: int,
        account_equity: float,
        cash_balance: float | None = None,
        total_position_value: float | None = None,
        daily_pnl_pct: float | None = None,
        drawdown_pct: float | None = None,
        positions: list[dict[str, Any]] | None = None,
    ) -> PostInvestmentRiskCheckResult:
        """Return a portfolio health snapshot for post-investment tracking."""

        effective_policy = self.resolver.execute(account_id=account_id)
        parameters = effective_policy.get("parameters") or {}
        position_rows = positions or []
        equity = max(float(account_equity), 0.0)
        total_position = (
            max(float(total_position_value), 0.0)
            if total_position_value is not None
            else sum(self._float_or_zero(item.get("market_value")) for item in position_rows)
        )
        cash = (
            max(float(cash_balance), 0.0)
            if cash_balance is not None
            else max(equity - total_position, 0.0)
        )
        total_position_pct = total_position / equity if equity > 0 else 0.0
        cash_pct = cash / equity if equity > 0 else 0.0

        violations: list[str] = []
        warnings: list[str] = []
        position_alerts: list[dict[str, Any]] = []

        if equity <= 0:
            violations.append("account equity must be positive for post-investment checks")

        self._check_upper_limit(
            violations=violations,
            label="max_total_position_pct",
            value=total_position_pct,
            limit=parameters.get("max_total_position_pct"),
        )
        self._check_lower_limit(
            violations=violations,
            label="min_cash_pct",
            value=cash_pct,
            limit=parameters.get("min_cash_pct"),
        )
        if daily_pnl_pct is not None:
            self._check_loss_limit(
                violations=violations,
                label="max_daily_loss_pct",
                loss_pct=-float(daily_pnl_pct),
                limit=parameters.get("max_daily_loss_pct"),
            )
        if drawdown_pct is not None:
            self._check_upper_limit(
                violations=violations,
                label="max_drawdown_pct",
                value=float(drawdown_pct),
                limit=parameters.get("max_drawdown_pct"),
            )

        hard_exclusions = {str(item).upper() for item in parameters.get("hard_exclusions") or []}
        for position in position_rows:
            position_alerts.extend(
                self._evaluate_position(
                    position=position,
                    equity=equity,
                    parameters=parameters,
                    hard_exclusions=hard_exclusions,
                    violations=violations,
                    warnings=warnings,
                )
            )

        status = "breach" if violations else "watch" if warnings or position_alerts else "ok"
        metrics = {
            "account_equity": equity,
            "total_position_value": total_position,
            "cash_balance": cash,
            "total_position_pct": total_position_pct,
            "cash_pct": cash_pct,
            "position_count": float(len(position_rows)),
        }
        if daily_pnl_pct is not None:
            metrics["daily_pnl_pct"] = float(daily_pnl_pct)
        if drawdown_pct is not None:
            metrics["drawdown_pct"] = float(drawdown_pct)

        return PostInvestmentRiskCheckResult(
            status=status,
            passed=not violations,
            violations=violations,
            warnings=warnings,
            position_alerts=position_alerts,
            effective_policy=effective_policy,
            metrics=metrics,
        )

    def _evaluate_position(
        self,
        *,
        position: dict[str, Any],
        equity: float,
        parameters: dict[str, Any],
        hard_exclusions: set[str],
        violations: list[str],
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        symbol = str(position.get("symbol") or position.get("asset_code") or "").upper()
        market_value = self._float_or_zero(position.get("market_value"))
        unrealized_pnl_pct = position.get("unrealized_pnl_pct")
        position_pct = market_value / equity if equity > 0 else 0.0
        alerts: list[dict[str, Any]] = []

        single_limit = self._optional_float(parameters.get("max_single_position_pct"))
        if single_limit is not None and position_pct > single_limit:
            message = (
                f"{symbol} max_single_position_pct exceeded: "
                f"current={position_pct:.4f}, limit={single_limit:.4f}"
            )
            violations.append(message)
            alerts.append(
                {
                    "symbol": symbol,
                    "level": "breach",
                    "type": "concentration",
                    "message": message,
                    "current": position_pct,
                    "limit": single_limit,
                }
            )

        if symbol in hard_exclusions:
            message = f"{symbol} is in risk-center hard exclusions"
            violations.append(message)
            alerts.append(
                {
                    "symbol": symbol,
                    "level": "breach",
                    "type": "hard_exclusion",
                    "message": message,
                }
            )

        if unrealized_pnl_pct is not None:
            pnl_pct = float(unrealized_pnl_pct)
            alerts.extend(
                self._evaluate_position_pnl(
                    symbol=symbol,
                    pnl_pct=pnl_pct,
                    parameters=parameters,
                    violations=violations,
                    warnings=warnings,
                )
            )

        return alerts

    def _evaluate_position_pnl(
        self,
        *,
        symbol: str,
        pnl_pct: float,
        parameters: dict[str, Any],
        violations: list[str],
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        max_stop_loss_pct = self._optional_float(parameters.get("max_stop_loss_pct"))
        force_stop_loss = bool(parameters.get("force_stop_loss"))
        if max_stop_loss_pct is not None and pnl_pct <= -max_stop_loss_pct:
            message = (
                f"{symbol} stop_loss breached: pnl={pnl_pct:.4f}, "
                f"limit=-{max_stop_loss_pct:.4f}"
            )
            alert = {
                "symbol": symbol,
                "level": "breach" if force_stop_loss else "watch",
                "type": "stop_loss",
                "message": message,
                "current": pnl_pct,
                "limit": -max_stop_loss_pct,
                "action": "force_close_or_reduce" if force_stop_loss else "review",
            }
            alerts.append(alert)
            if force_stop_loss:
                violations.append(message)
            else:
                warnings.append(message)

        take_profit_pct = self._optional_float(parameters.get("take_profit_pct"))
        if take_profit_pct is not None and pnl_pct >= take_profit_pct:
            message = (
                f"{symbol} take_profit reached: pnl={pnl_pct:.4f}, "
                f"target={take_profit_pct:.4f}"
            )
            warnings.append(message)
            alerts.append(
                {
                    "symbol": symbol,
                    "level": "watch",
                    "type": "take_profit",
                    "message": message,
                    "current": pnl_pct,
                    "limit": take_profit_pct,
                    "action": "review_profit_taking",
                }
            )
        return alerts

    @staticmethod
    def _check_upper_limit(
        *,
        violations: list[str],
        label: str,
        value: float,
        limit: Any,
    ) -> None:
        numeric_limit = EvaluatePostInvestmentRiskUseCase._optional_float(limit)
        if numeric_limit is not None and value > numeric_limit:
            violations.append(f"{label} exceeded: current={value:.4f}, limit={numeric_limit:.4f}")

    @staticmethod
    def _check_lower_limit(
        *,
        violations: list[str],
        label: str,
        value: float,
        limit: Any,
    ) -> None:
        numeric_limit = EvaluatePostInvestmentRiskUseCase._optional_float(limit)
        if numeric_limit is not None and value < numeric_limit:
            violations.append(f"{label} breached: current={value:.4f}, limit={numeric_limit:.4f}")

    @staticmethod
    def _check_loss_limit(
        *,
        violations: list[str],
        label: str,
        loss_pct: float,
        limit: Any,
    ) -> None:
        numeric_limit = EvaluatePostInvestmentRiskUseCase._optional_float(limit)
        if numeric_limit is not None and loss_pct > numeric_limit:
            violations.append(f"{label} exceeded: loss={loss_pct:.4f}, limit={numeric_limit:.4f}")

    @staticmethod
    def _float_or_zero(value: Any) -> float:
        try:
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
