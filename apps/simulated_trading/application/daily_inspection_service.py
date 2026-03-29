"""Daily inspection service for simulated ETF portfolios."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from apps.policy.infrastructure.repositories import DjangoPolicyRepository
from apps.regime.application.current_regime import resolve_current_regime
from apps.simulated_trading.infrastructure.repositories import (
    DjangoInspectionRepository,
    DjangoPositionRepository,
    DjangoSimulatedAccountRepository,
)
from apps.strategy.application.execution_gateway import get_strategy_execution_gateway


@dataclass(frozen=True)
class InspectionSelection:
    strategy_id: int | None
    rule_id: int | None
    rule_metadata: dict[str, Any]


class DailyInspectionService:
    """Generate and persist daily inspection report for one account."""

    DEFAULT_RISK_PER_TRADE_PCT = 0.008
    DEFAULT_ENTRY_BUFFER_PCT = 0.002
    account_repo = DjangoSimulatedAccountRepository()
    position_repo = DjangoPositionRepository()
    inspection_repo = DjangoInspectionRepository()
    policy_repo = DjangoPolicyRepository()

    @classmethod
    def run(
        cls,
        account_id: int,
        inspection_date: date | None = None,
        strategy_id: int | None = None,
    ) -> dict[str, Any]:
        as_of = inspection_date or date.today()
        account = cls.account_repo.get_by_id(account_id)
        if not account:
            raise ValueError(f"账户不存在: {account_id}")
        selection = cls._select_strategy_and_rule(account_id=account_id, strategy_id=strategy_id)

        checks = cls._build_checks(
            account=account,
            selection=selection,
        )
        checks = cls._to_json_safe(checks)
        summary = cls._to_json_safe(cls._build_summary(account=account, checks=checks))
        status = "warning" if summary["rebalance_required_count"] > 0 else "ok"

        report = cls.inspection_repo.upsert_report(
            account_id=account_id,
            inspection_date=as_of,
            defaults={
                "strategy_id": selection.strategy_id,
                "position_rule_id": selection.rule_id,
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
            "report_id": report["report_id"],
            "account_id": account.account_id,
            "inspection_date": as_of.isoformat(),
            "status": report["status"],
            "macro_regime": report["macro_regime"],
            "policy_gear": report["policy_gear"],
            "strategy_id": selection.strategy_id,
            "position_rule_id": selection.rule_id,
            "summary": summary,
            "checks": checks,
        }

    @classmethod
    def _select_strategy_and_rule(
        cls,
        account_id: int,
        strategy_id: int | None,
    ) -> InspectionSelection:
        gateway = get_strategy_execution_gateway()
        selection = gateway.get_inspection_selection(
            account_id=account_id,
            strategy_id=strategy_id,
        )
        return InspectionSelection(
            strategy_id=selection.strategy_id,
            rule_id=selection.position_rule_id,
            rule_metadata=selection.rule_metadata,
        )

    @classmethod
    def _build_checks(
        cls,
        account,
        selection: InspectionSelection,
    ) -> list[dict[str, Any]]:
        positions = sorted(
            cls.position_repo.get_by_account(account.account_id),
            key=lambda pos: float(pos.market_value),
            reverse=True,
        )
        total_value = float(account.total_value or 0)
        checks: list[dict[str, Any]] = []
        rebalance_cfg = (selection.rule_metadata or {}).get("rebalance", {}) if selection.rule_id else {}
        target_weights = rebalance_cfg.get("target_weights", {})
        drift_threshold = float(rebalance_cfg.get("drift_threshold", 0.05))
        gateway = get_strategy_execution_gateway()

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
            if selection.rule_id:
                context = cls._build_context(
                    current_price=current_price,
                    entry_price=float(pos.avg_cost),
                    account_equity=total_value,
                )
                rule_eval = gateway.evaluate_position_rule(selection.rule_id, context)

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
        account,
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

    @classmethod
    def _to_json_safe(cls, value: Any) -> Any:
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, list):
            return [cls._to_json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [cls._to_json_safe(item) for item in value]
        if isinstance(value, dict):
            return {key: cls._to_json_safe(item) for key, item in value.items()}
        return value

    @staticmethod
    def _latest_regime() -> str:
        return resolve_current_regime().dominant_regime

    @staticmethod
    def _latest_policy_gear() -> str:
        latest = DailyInspectionService.policy_repo.get_latest_event()
        return latest.level.value if latest else ""

    @classmethod
    def run_and_create_proposal(
        cls,
        account_id: int,
        inspection_date: date | None = None,
        strategy_id: int | None = None,
        auto_create_proposal: bool = True,
    ) -> dict[str, Any]:
        """
        运行日更巡检并创建再平衡建议草案

        Args:
            account_id: 账户ID
            inspection_date: 巡检日期
            strategy_id: 策略ID
            auto_create_proposal: 是否自动创建再平衡建议

        Returns:
            包含巡检结果和再平衡建议ID的字典
        """
        # 先运行巡检
        inspection_result = cls.run(
            account_id=account_id,
            inspection_date=inspection_date,
            strategy_id=strategy_id,
        )

        result = {
            **inspection_result,
            "proposal_id": None,
            "proposal_created": False,
        }

        # 如果需要自动创建建议且存在需要再平衡的资产
        if auto_create_proposal:
            summary = inspection_result.get("summary", {})
            rebalance_count = summary.get("rebalance_required_count", 0)

            if rebalance_count > 0:
                proposal = cls.create_rebalance_proposal(
                    account_id=account_id,
                    inspection_result=inspection_result,
                )
                result["proposal_id"] = proposal["proposal_id"]
                result["proposal_created"] = True

        return result

    @classmethod
    def create_rebalance_proposal(
        cls,
        account_id: int,
        inspection_result: dict[str, Any],
    ) -> dict[str, Any]:
        """
        根据巡检结果创建再平衡建议草案

        Args:
            account_id: 账户ID
            inspection_result: 巡检结果

        Returns:
            RebalanceProposalModel: 创建的再平衡建议
        """
        account = cls.account_repo.get_by_id(account_id)
        if not account:
            raise ValueError(f"账户不存在: {account_id}")
        checks = inspection_result.get("checks", [])
        summary = inspection_result.get("summary", {})

        # 构建再平衡建议
        proposals = []
        total_buy_amount = 0.0
        total_sell_amount = 0.0

        for check in checks:
            action = check.get("rebalance_action", "hold")

            if action == "hold":
                continue

            current_price = check.get("current_price", 0)
            qty_suggest = check.get("rebalance_qty_suggest", 0)
            estimated_amount = abs(qty_suggest * current_price)

            proposal_item = {
                "asset_code": check.get("asset_code"),
                "asset_name": check.get("asset_name"),
                "action": action,
                "current_quantity": check.get("quantity", 0),
                "current_weight": check.get("weight", 0),
                "target_weight": check.get("target_weight", 0),
                "drift": check.get("drift", 0),
                "suggested_quantity": abs(qty_suggest),
                "estimated_amount": round(estimated_amount, 2),
                "reason": cls._get_rebalance_reason(check),
            }

            proposals.append(proposal_item)

            if action == "buy":
                total_buy_amount += estimated_amount
            else:
                total_sell_amount += estimated_amount

        # 构建汇总信息
        proposal_summary = {
            "total_value": summary.get("total_value", 0),
            "current_cash": summary.get("current_cash", 0),
            "current_market_value": summary.get("current_market_value", 0),
            "rebalance_assets": summary.get("rebalance_assets", []),
            "buy_count": len([p for p in proposals if p["action"] == "buy"]),
            "sell_count": len([p for p in proposals if p["action"] == "sell"]),
            "estimated_buy_amount": round(total_buy_amount, 2),
            "estimated_sell_amount": round(total_sell_amount, 2),
            "estimated_trade_amount": round(total_buy_amount + total_sell_amount, 2),
        }

        # 确定优先级
        priority = cls._determine_priority(summary)

        # 创建再平衡建议
        proposal = cls.inspection_repo.create_rebalance_proposal({
            "account_id": account_id,
            "inspection_report_id": inspection_result.get("report_id"),
            "strategy_id": inspection_result.get("strategy_id"),
            "source": "daily_inspection",
            "source_description": cls._build_source_description(inspection_result),
            "status": "pending",
            "priority": priority,
            "proposals": proposals,
            "summary": proposal_summary,
            "proposed_by": "daily_inspection",
            "metadata": {
                "inspection_date": inspection_result.get("inspection_date"),
                "macro_regime": inspection_result.get("macro_regime"),
                "policy_gear": inspection_result.get("policy_gear"),
                "position_rule_id": inspection_result.get("position_rule_id"),
            },
        })

        return proposal

    @classmethod
    def _get_rebalance_reason(cls, check: dict[str, Any]) -> str:
        """获取再平衡原因"""
        drift = check.get("drift", 0)
        target_weight = check.get("target_weight", 0)
        current_weight = check.get("weight", 0)
        asset_name = check.get("asset_name", "")

        if drift > 0:
            return f"{asset_name} 当前权重 {current_weight:.2%} 超过目标 {target_weight:.2%}，需要减持"
        else:
            return f"{asset_name} 当前权重 {current_weight:.2%} 低于目标 {target_weight:.2%}，需要增持"

    @classmethod
    def _build_source_description(cls, inspection_result: dict[str, Any]) -> str:
        """构建建议来源描述"""
        regime = inspection_result.get("macro_regime", "")
        policy = inspection_result.get("policy_gear", "")
        rebalance_count = inspection_result.get("summary", {}).get("rebalance_required_count", 0)

        parts = ["日更巡检发现"]

        if regime:
            parts.append(f"宏观象限为 {regime}")

        if policy:
            parts.append(f"政策档位为 {policy}")

        parts.append(f"{rebalance_count} 个资产需要再平衡")

        return "，".join(parts) + "。"

    @classmethod
    def _determine_priority(cls, summary: dict[str, Any]) -> str:
        """根据巡检结果确定建议优先级"""
        rebalance_count = summary.get("rebalance_required_count", 0)
        total_value = summary.get("total_value", 0)
        current_cash = summary.get("current_cash", 0)

        # 如果需要再平衡的资产数量超过 3 个，优先级设为高
        if rebalance_count >= 3:
            return "high"

        # 如果现金比例过低（低于 5%），优先级设为高
        if total_value > 0 and (current_cash / total_value) < 0.05:
            return "high"

        # 默认普通优先级
        return "normal"
