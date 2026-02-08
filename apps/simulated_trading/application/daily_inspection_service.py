"""Daily inspection service for simulated ETF portfolios."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from apps.policy.infrastructure.models import PolicyLog
from apps.regime.infrastructure.models import RegimeLog
from apps.simulated_trading.infrastructure.models import (
    DailyInspectionReportModel,
    PositionModel,
    SimulatedAccountModel,
)
from apps.strategy.application.position_management_service import PositionManagementService
from apps.strategy.infrastructure.models import PositionManagementRuleModel, StrategyModel


@dataclass(frozen=True)
class InspectionSelection:
    strategy: StrategyModel | None
    rule: PositionManagementRuleModel | None


class DailyInspectionService:
    """Generate and persist daily inspection report for one account."""

    DEFAULT_RISK_PER_TRADE_PCT = 0.008
    DEFAULT_ENTRY_BUFFER_PCT = 0.002

    @classmethod
    def run(
        cls,
        account_id: int,
        inspection_date: date | None = None,
        strategy_id: int | None = None,
    ) -> dict[str, Any]:
        as_of = inspection_date or date.today()
        account = SimulatedAccountModel._default_manager.get(id=account_id)
        selection = cls._select_strategy_and_rule(account_id=account_id, strategy_id=strategy_id)

        checks = cls._build_checks(
            account=account,
            rule=selection.rule,
        )
        summary = cls._build_summary(account=account, checks=checks)
        status = "warning" if summary["rebalance_required_count"] > 0 else "ok"

        report, _ = DailyInspectionReportModel._default_manager.update_or_create(
            account=account,
            inspection_date=as_of,
            defaults={
                "strategy": selection.strategy,
                "position_rule": selection.rule,
                "status": status,
                "macro_regime": cls._latest_regime(),
                "policy_gear": cls._latest_policy_gear(),
                "total_value": account.total_value,
                "current_cash": account.current_cash,
                "current_market_value": account.current_market_value,
                "checks": checks,
                "summary": summary,
            },
        )

        return {
            "report_id": report.id,
            "account_id": account.id,
            "inspection_date": as_of.isoformat(),
            "status": report.status,
            "macro_regime": report.macro_regime,
            "policy_gear": report.policy_gear,
            "strategy_id": selection.strategy.id if selection.strategy else None,
            "position_rule_id": selection.rule.id if selection.rule else None,
            "summary": summary,
            "checks": checks,
        }

    @classmethod
    def _select_strategy_and_rule(
        cls,
        account_id: int,
        strategy_id: int | None,
    ) -> InspectionSelection:
        if strategy_id:
            strategy = StrategyModel._default_manager.filter(id=strategy_id).first()
            rule = (
                PositionManagementRuleModel._default_manager.filter(
                    strategy_id=strategy_id,
                    is_active=True,
                )
                .order_by("-updated_at")
                .first()
            )
            return InspectionSelection(strategy=strategy, rule=rule)

        rule = (
            PositionManagementRuleModel._default_manager.filter(
                is_active=True,
                metadata__account_id=account_id,
            )
            .select_related("strategy")
            .order_by("-updated_at")
            .first()
        )
        if rule:
            return InspectionSelection(strategy=rule.strategy, rule=rule)
        return InspectionSelection(strategy=None, rule=None)

    @classmethod
    def _build_checks(
        cls,
        account: SimulatedAccountModel,
        rule: PositionManagementRuleModel | None,
    ) -> list[dict[str, Any]]:
        positions = PositionModel._default_manager.filter(account=account).order_by("-market_value")
        total_value = float(account.total_value or 0)
        checks: list[dict[str, Any]] = []
        rebalance_cfg = (rule.metadata or {}).get("rebalance", {}) if rule else {}
        target_weights = rebalance_cfg.get("target_weights", {})
        drift_threshold = float(rebalance_cfg.get("drift_threshold", 0.05))

        for pos in positions:
            current_price = float(pos.current_price)
            market_value = float(pos.market_value)
            weight = (market_value / total_value) if total_value > 0 else 0.0
            target_weight = float(target_weights.get(pos.asset_code, 0.0))
            drift = weight - target_weight
            rebalance_action = "hold"
            if abs(drift) > drift_threshold:
                rebalance_action = "sell" if drift > 0 else "buy"
            rebalance_qty_suggest = int(((target_weight - weight) * total_value) / max(current_price, 0.01))

            rule_eval = None
            if rule:
                context = cls._build_context(
                    current_price=current_price,
                    entry_price=float(pos.avg_cost),
                    account_equity=total_value,
                )
                rule_eval = PositionManagementService.evaluate(rule=rule, context=context).to_dict()

            checks.append(
                {
                    "asset_code": pos.asset_code,
                    "asset_name": pos.asset_name,
                    "quantity": pos.quantity,
                    "current_price": current_price,
                    "market_value": market_value,
                    "weight": round(weight, 6),
                    "target_weight": round(target_weight, 6),
                    "drift": round(drift, 6),
                    "rebalance_action": rebalance_action,
                    "rebalance_qty_suggest": rebalance_qty_suggest,
                    "rule_eval": rule_eval,
                }
            )
        return checks

    @classmethod
    def _build_context(
        cls,
        current_price: float,
        entry_price: float,
        account_equity: float,
    ) -> dict[str, Any]:
        support_price = current_price * 0.992
        resistance_price = current_price * 1.03
        structure_low = current_price * 0.975
        atr = max(current_price * 0.015, 0.01)
        return {
            "current_price": current_price,
            "entry_price": entry_price,
            "support_price": support_price,
            "resistance_price": resistance_price,
            "structure_low": structure_low,
            "atr": atr,
            "account_equity": account_equity,
            "risk_per_trade_pct": cls.DEFAULT_RISK_PER_TRADE_PCT,
            "entry_buffer_pct": cls.DEFAULT_ENTRY_BUFFER_PCT,
        }

    @classmethod
    def _build_summary(
        cls,
        account: SimulatedAccountModel,
        checks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        rebalance_required = [c for c in checks if c["rebalance_action"] != "hold"]
        return {
            "positions_count": len(checks),
            "rebalance_required_count": len(rebalance_required),
            "rebalance_assets": [c["asset_code"] for c in rebalance_required],
            "total_value": float(account.total_value or Decimal("0")),
            "current_cash": float(account.current_cash or Decimal("0")),
            "current_market_value": float(account.current_market_value or Decimal("0")),
        }

    @staticmethod
    def _latest_regime() -> str:
        latest = RegimeLog._default_manager.order_by("-observed_at").first()
        return latest.dominant_regime if latest else ""

    @staticmethod
    def _latest_policy_gear() -> str:
        latest = PolicyLog._default_manager.order_by("-event_date", "-created_at").first()
        return latest.level if latest else ""
