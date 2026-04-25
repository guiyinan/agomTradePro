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
from apps.strategy.domain.allocation_matrix import get_allocation_target


@dataclass(frozen=True)
class InspectionSelection:
    strategy_id: int | None
    rule_id: int | None
    rule_metadata: dict[str, Any]


class DailyInspectionService:
    """Generate and persist daily inspection report for one account."""

    DEFAULT_RISK_PER_TRADE_PCT = 0.008
    DEFAULT_ENTRY_BUFFER_PCT = 0.002
    DEFAULT_DRIFT_THRESHOLD = 0.05
    DEFAULT_RISK_PROFILE = "moderate"
    ASSET_CLASS_KEYS = ("equity", "fixed_income", "commodity", "cash")
    ASSET_CLASS_DISPLAY = {
        "equity": "权益",
        "fixed_income": "固收",
        "commodity": "商品",
        "cash": "现金",
    }
    ASSET_TYPE_CLASS_MAP = {
        "equity": "equity",
        "stock": "equity",
        "fund": "equity",
        "bond": "fixed_income",
        "fixed_income": "fixed_income",
        "commodity": "commodity",
        "cash": "cash",
    }
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
        macro_regime = cls._latest_regime()
        policy_gear = cls._latest_policy_gear()
        pulse_context = cls._latest_pulse_context(as_of)

        checks = cls._build_checks(
            account=account,
            selection=selection,
            macro_regime=macro_regime,
            policy_gear=policy_gear,
            pulse_context=pulse_context,
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
                "macro_regime": macro_regime,
                "policy_gear": policy_gear,
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
        macro_regime: str,
        policy_gear: str,
        pulse_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        positions = sorted(
            cls.position_repo.get_by_account(account.account_id),
            key=lambda pos: float(pos.market_value),
            reverse=True,
        )
        total_value = float(account.total_value or 0)
        metadata = selection.rule_metadata or {}
        rebalance_cfg = cls._dict_value(metadata.get("rebalance"))
        allocation_cfg = cls._dict_value(metadata.get("allocation"))
        target_weights = cls._dict_value(rebalance_cfg.get("target_weights"))
        drift_threshold = cls._float_value(
            rebalance_cfg.get("drift_threshold"),
            cls.DEFAULT_DRIFT_THRESHOLD,
        )
        class_drift_threshold = cls._float_value(
            allocation_cfg.get("class_drift_threshold"),
            cls.DEFAULT_DRIFT_THRESHOLD,
        )
        risk_profile = str(allocation_cfg.get("risk_profile") or cls.DEFAULT_RISK_PROFILE)
        asset_class_overrides = cls._dict_value(allocation_cfg.get("asset_class_overrides"))
        gateway = get_strategy_execution_gateway()

        checks = cls._build_asset_class_checks(
            account=account,
            positions=positions,
            total_value=total_value,
            macro_regime=macro_regime,
            policy_gear=policy_gear,
            risk_profile=risk_profile,
            drift_threshold=class_drift_threshold,
            asset_class_overrides=asset_class_overrides,
            allocation_cfg=allocation_cfg,
            pulse_context=pulse_context,
        )

        seen_asset_codes: set[str] = set()
        for pos in positions:
            seen_asset_codes.add(pos.asset_code)
            current_price = float(pos.current_price)
            market_value = float(pos.market_value)
            weight = (market_value / total_value) if total_value > 0 else 0.0
            has_asset_target = bool(target_weights)
            target_weight = cls._float_value(target_weights.get(pos.asset_code), 0.0) if has_asset_target else None
            drift = weight - target_weight if target_weight is not None else 0.0
            rebalance_action = "hold"
            if target_weight is not None and abs(drift) > drift_threshold:
                rebalance_action = "sell" if drift > 0 else "buy"
            rebalance_qty_suggest = (
                int(((target_weight - weight) * total_value) / max(current_price, 0.01))
                if target_weight is not None
                else 0
            )
            suggested_amount = abs((target_weight - weight) * total_value) if target_weight is not None else 0.0

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
                    "scope": "asset",
                    "asset_code": pos.asset_code,
                    "asset_name": pos.asset_name,
                    "asset_class": cls._resolve_asset_class(pos, asset_class_overrides),
                    "quantity": pos.quantity,
                    "current_price": current_price,
                    "market_value": market_value,
                    "weight": round(weight, 6),
                    "target_weight": round(target_weight, 6) if target_weight is not None else None,
                    "drift": round(drift, 6),
                    "rebalance_action": rebalance_action,
                    "rebalance_qty_suggest": rebalance_qty_suggest,
                    "suggested_amount": round(suggested_amount, 2),
                    "drift_threshold": drift_threshold,
                    "rule_eval": rule_eval,
                }
            )

        for asset_code, raw_target_weight in target_weights.items():
            if asset_code in seen_asset_codes:
                continue
            target_weight = cls._float_value(raw_target_weight, 0.0)
            if target_weight <= 0:
                continue
            suggested_amount = target_weight * total_value
            checks.append(
                {
                    "scope": "asset",
                    "asset_code": asset_code,
                    "asset_name": asset_code,
                    "asset_class": "",
                    "quantity": 0,
                    "current_price": 1.0,
                    "market_value": 0.0,
                    "weight": 0.0,
                    "target_weight": round(target_weight, 6),
                    "drift": round(-target_weight, 6),
                    "rebalance_action": "buy" if target_weight > drift_threshold else "hold",
                    "rebalance_qty_suggest": int(suggested_amount),
                    "suggested_amount": round(suggested_amount, 2),
                    "drift_threshold": drift_threshold,
                    "rule_eval": None,
                }
            )
        return checks

    @classmethod
    def _build_asset_class_checks(
        cls,
        account,
        positions: list,
        total_value: float,
        macro_regime: str,
        policy_gear: str,
        risk_profile: str,
        drift_threshold: float,
        asset_class_overrides: dict[str, Any],
        allocation_cfg: dict[str, Any],
        pulse_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        try:
            target = get_allocation_target(
                macro_regime,
                risk_profile,
                policy_gear or None,
            ).allocation
        except ValueError:
            return []
        target_weights = {
            "equity": target.equity,
            "fixed_income": target.fixed_income,
            "commodity": target.commodity,
            "cash": target.cash,
        }
        target_weights = cls._apply_pulse_overlay(
            target_weights=target_weights,
            allocation_cfg=allocation_cfg,
            pulse_context=pulse_context,
        )
        effective_drift_threshold = cls._apply_pulse_threshold_overlay(
            drift_threshold=drift_threshold,
            allocation_cfg=allocation_cfg,
            pulse_context=pulse_context,
        )
        current_values = dict.fromkeys(cls.ASSET_CLASS_KEYS, 0.0)
        for pos in positions:
            asset_class = cls._resolve_asset_class(pos, asset_class_overrides)
            current_values[asset_class] += float(pos.market_value)
        current_values["cash"] = max(float(account.current_cash or 0), 0.0)

        checks: list[dict[str, Any]] = []
        for asset_class in cls.ASSET_CLASS_KEYS:
            current_weight = (current_values[asset_class] / total_value) if total_value > 0 else 0.0
            target_weight = target_weights[asset_class]
            drift = current_weight - target_weight
            rebalance_action = "hold"
            if abs(drift) > effective_drift_threshold:
                rebalance_action = "sell" if drift > 0 else "buy"
            suggested_amount = abs((target_weight - current_weight) * total_value)
            checks.append(
                {
                    "scope": "asset_class",
                    "asset_code": f"asset_class:{asset_class}",
                    "asset_name": cls.ASSET_CLASS_DISPLAY.get(asset_class, asset_class),
                    "asset_class": asset_class,
                    "quantity": 0,
                    "current_price": 1.0,
                    "market_value": round(current_values[asset_class], 2),
                    "weight": round(current_weight, 6),
                    "target_weight": round(target_weight, 6),
                    "drift": round(drift, 6),
                    "rebalance_action": rebalance_action,
                    "rebalance_qty_suggest": int((target_weight - current_weight) * total_value),
                    "suggested_amount": round(suggested_amount, 2),
                    "drift_threshold": effective_drift_threshold,
                    "rule_eval": None,
                    "risk_profile": risk_profile,
                    "macro_regime": macro_regime,
                    "policy_gear": policy_gear,
                    "pulse": pulse_context,
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
        class_checks = [c for c in checks if c.get("scope") == "asset_class"]
        asset_checks = [c for c in checks if c.get("scope", "asset") == "asset"]
        class_rebalance_required = [c for c in class_checks if c["rebalance_action"] != "hold"]
        asset_rebalance_required = [c for c in asset_checks if c["rebalance_action"] != "hold"]
        target_allocation = {
            c["asset_class"]: c["target_weight"]
            for c in class_checks
            if c.get("asset_class")
        }
        max_abs_drift = max((abs(float(c.get("drift") or 0)) for c in rebalance_required), default=0.0)
        risk_profile = next((c.get("risk_profile") for c in class_checks if c.get("risk_profile")), None)
        pulse_context = next((c.get("pulse") for c in class_checks if c.get("pulse")), None)
        return {
            "positions_count": len(asset_checks),
            "checks_count": len(checks),
            "rebalance_required_count": len(rebalance_required),
            "asset_class_rebalance_required_count": len(class_rebalance_required),
            "asset_rebalance_required_count": len(asset_rebalance_required),
            "rebalance_assets": [c["asset_code"] for c in asset_rebalance_required],
            "rebalance_asset_classes": [c["asset_class"] for c in class_rebalance_required],
            "max_abs_drift": round(max_abs_drift, 6),
            "target_allocation": target_allocation,
            "risk_profile": risk_profile or cls.DEFAULT_RISK_PROFILE,
            "pulse": pulse_context or cls._empty_pulse_context(),
            "total_value": float(account.total_value or Decimal("0")),
            "current_cash": float(account.current_cash or Decimal("0")),
            "current_market_value": float(account.current_market_value or Decimal("0")),
        }

    @classmethod
    def _dict_value(cls, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @classmethod
    def _float_value(cls, value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _resolve_asset_class(cls, position, overrides: dict[str, Any]) -> str:
        override = overrides.get(position.asset_code)
        if override:
            normalized = cls._normalize_asset_class(str(override))
            if normalized:
                return normalized
        normalized = cls._normalize_asset_class(str(getattr(position, "asset_type", "")))
        return normalized or "equity"

    @classmethod
    def _normalize_asset_class(cls, raw_value: str) -> str | None:
        value = (raw_value or "").strip().lower()
        return cls.ASSET_TYPE_CLASS_MAP.get(value)

    @classmethod
    def _apply_pulse_overlay(
        cls,
        target_weights: dict[str, float],
        allocation_cfg: dict[str, Any],
        pulse_context: dict[str, Any],
    ) -> dict[str, float]:
        if not allocation_cfg.get("pulse_overlay_enabled", True):
            return target_weights
        if not pulse_context.get("available"):
            return target_weights

        multiplier = 1.0
        if pulse_context.get("transition_warning"):
            multiplier = cls._float_value(
                allocation_cfg.get("pulse_warning_equity_multiplier"),
                0.85,
            )
        elif pulse_context.get("regime_strength") == "weak":
            multiplier = cls._float_value(
                allocation_cfg.get("pulse_weak_equity_multiplier"),
                0.90,
            )
        elif pulse_context.get("regime_strength") == "strong":
            multiplier = cls._float_value(
                allocation_cfg.get("pulse_strong_equity_multiplier"),
                1.0,
            )

        multiplier = max(0.0, min(multiplier, 1.5))
        if abs(multiplier - 1.0) < 0.000001:
            return target_weights

        adjusted = dict(target_weights)
        original_equity = adjusted["equity"]
        adjusted_equity = max(0.0, min(original_equity * multiplier, 1.0))
        equity_delta = original_equity - adjusted_equity
        adjusted["equity"] = adjusted_equity

        defensive_total = adjusted["fixed_income"] + adjusted["cash"]
        if defensive_total > 0:
            adjusted["fixed_income"] += equity_delta * (adjusted["fixed_income"] / defensive_total)
            adjusted["cash"] += equity_delta * (adjusted["cash"] / defensive_total)
        else:
            adjusted["fixed_income"] += equity_delta * 0.5
            adjusted["cash"] += equity_delta * 0.5

        total = sum(adjusted.values())
        if total > 0:
            adjusted = {key: value / total for key, value in adjusted.items()}
        return adjusted

    @classmethod
    def _apply_pulse_threshold_overlay(
        cls,
        drift_threshold: float,
        allocation_cfg: dict[str, Any],
        pulse_context: dict[str, Any],
    ) -> float:
        if not allocation_cfg.get("pulse_overlay_enabled", True):
            return drift_threshold
        if not pulse_context.get("available"):
            return drift_threshold
        if not pulse_context.get("transition_warning") and pulse_context.get("regime_strength") != "weak":
            return drift_threshold

        multiplier = cls._float_value(
            allocation_cfg.get("pulse_drift_threshold_multiplier"),
            0.75,
        )
        return max(0.01, drift_threshold * multiplier)

    @classmethod
    def _latest_pulse_context(cls, as_of_date: date) -> dict[str, Any]:
        try:
            from apps.pulse.application.use_cases import GetLatestPulseUseCase

            snapshot = GetLatestPulseUseCase().execute(
                as_of_date=as_of_date,
                require_reliable=False,
                refresh_if_stale=False,
            )
        except Exception:
            snapshot = None

        if snapshot is None:
            return cls._empty_pulse_context()
        return {
            "available": True,
            "observed_at": snapshot.observed_at.isoformat(),
            "composite_score": float(snapshot.composite_score),
            "regime_strength": snapshot.regime_strength,
            "transition_warning": bool(snapshot.transition_warning),
            "transition_direction": snapshot.transition_direction,
            "data_source": snapshot.data_source,
            "stale_indicator_count": snapshot.stale_indicator_count,
        }

    @classmethod
    def _empty_pulse_context(cls) -> dict[str, Any]:
        return {
            "available": False,
            "observed_at": None,
            "composite_score": 0.0,
            "regime_strength": "unknown",
            "transition_warning": False,
            "transition_direction": None,
            "data_source": "unavailable",
            "stale_indicator_count": 0,
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
            estimated_amount = check.get("suggested_amount")
            if estimated_amount is None:
                estimated_amount = abs(qty_suggest * current_price)

            proposal_item = {
                "scope": check.get("scope", "asset"),
                "asset_code": check.get("asset_code"),
                "asset_name": check.get("asset_name"),
                "asset_class": check.get("asset_class", ""),
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
                "risk_profile": summary.get("risk_profile"),
                "target_allocation": summary.get("target_allocation", {}),
                "pulse": summary.get("pulse", cls._empty_pulse_context()),
                "triggered_scopes": sorted({
                    p.get("scope", "asset")
                    for p in proposals
                    if p.get("scope")
                }),
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
        if check.get("scope") == "asset_class":
            asset_name = f"{asset_name}大类"

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
