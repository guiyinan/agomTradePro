"""
Asset Allocation Service Application Layer

Provides business logic for calculating asset allocation recommendations
based on current portfolio, regime, and risk profile.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from django.conf import settings

from apps.strategy.domain.allocation_matrix import (
    AllocationTarget,
    AssetAllocation,
    get_allocation_target,
)
from apps.strategy.domain.protocols import AssetNameResolverProtocol, PositionLikeProtocol


@dataclass
class TradeAction:
    """交易操作建议"""
    asset_code: str
    asset_name: str
    action: str  # "buy" 或 "sell"
    amount: float  # 交易金额（元）
    reason: str  # 操作理由
    asset_class: str  # 资产大类
    priority: int = 1  # 优先级（1=最高，数字越大优先级越低）


@dataclass
class AllocationAdvice:
    """资产配置建议"""
    # 当前配置
    current_allocation: dict[str, float]  # {"equity": 0.65, "fixed_income": 0.20, ...}

    # 目标配置
    target_allocation: dict[str, float]

    # 配置差异
    allocation_diff: dict[str, float]  # {"equity": -0.45, "fixed_income": 0.20, ...}

    # 具体操作建议
    trade_actions: list[TradeAction]

    # 配置摘要
    summary: str

    # 预期效果
    expected_return: float | None = None
    expected_volatility: float | None = None
    sharpe_ratio: float | None = None

    # 元数据
    regime: str = ""
    risk_profile: str = ""
    policy_level: str = ""


class AllocationService:
    """
    资产配置服务

    根据当前Regime、用户风险偏好、Policy档位和当前持仓，
    计算目标配置和具体调仓操作。
    """

    @classmethod
    def calculate_allocation_advice(
        cls,
        current_regime: str,
        risk_profile: str,
        policy_level: str | None,
        total_assets: float,
        current_positions: list[PositionLikeProtocol],
        asset_name_resolver: AssetNameResolverProtocol | None = None,
    ) -> AllocationAdvice:
        """
        计算资产配置建议

        Args:
            current_regime: 当前Regime
            risk_profile: 用户风险偏好
            policy_level: 当前Policy档位
            total_assets: 总资产
            current_positions: 当前持仓列表

        Returns:
            AllocationAdvice: 配置建议
        """
        # 1. 获取目标配置
        target = get_allocation_target(current_regime, risk_profile, policy_level)

        # 2. 计算当前配置
        current_allocation = cls._calculate_current_allocation(current_positions, total_assets)

        # 3. 计算配置差异
        allocation_diff = cls._calculate_allocation_diff(current_allocation, target.allocation)

        # 4. 生成具体操作建议
        trade_actions = cls._generate_trade_actions(
            current_positions,
            current_allocation,
            target.allocation,
            total_assets,
            current_regime,
            asset_name_resolver=asset_name_resolver,
        )

        # 5. 生成摘要
        summary = cls._generate_summary(
            current_regime,
            risk_profile,
            policy_level,
            current_allocation,
            target.allocation,
            trade_actions,
        )

        return AllocationAdvice(
            current_allocation={k: round(v, 3) for k, v in current_allocation.items()},
            target_allocation=target.allocation.to_percentage_dict(),
            allocation_diff=allocation_diff,
            trade_actions=trade_actions,
            summary=summary,
            expected_return=target.expected_return,
            expected_volatility=target.expected_volatility,
            sharpe_ratio=target.sharpe_ratio,
            regime=current_regime,
            risk_profile=risk_profile,
            policy_level=policy_level or "P0",
        )

    @classmethod
    def _calculate_current_allocation(
        cls,
        positions: list[PositionLikeProtocol],
        total_assets: float,
    ) -> dict[str, float]:
        """计算当前资产配置"""
        if total_assets <= 0:
            return {"equity": 0.0, "fixed_income": 0.0, "commodity": 0.0, "cash": 1.0}

        # 按资产大类汇总市值
        allocation = {"equity": 0.0, "fixed_income": 0.0, "commodity": 0.0, "cash": 0.0}

        for pos in positions:
            asset_class = pos.asset_class.value
            if asset_class in allocation:
                allocation[asset_class] += float(pos.market_value)

        # 计算现金余额（总资产 - 已投资市值）
        invested_value = sum(allocation.values())
        cash_balance = total_assets - invested_value
        allocation["cash"] = max(0, cash_balance)

        # 转换为比例
        allocation_ratio = {
            k: round(v / total_assets, 3) if total_assets > 0 else 0.0
            for k, v in allocation.items()
        }

        return allocation_ratio

    @classmethod
    def _calculate_allocation_diff(
        cls,
        current: dict[str, float],
        target: AssetAllocation,
    ) -> dict[str, float]:
        """计算配置差异"""
        target_dict = {
            "equity": target.equity,
            "fixed_income": target.fixed_income,
            "commodity": target.commodity,
            "cash": target.cash,
        }

        diff = {
            k: round(target_dict[k] - current.get(k, 0.0), 3)
            for k in target_dict.keys()
        }

        return diff

    @classmethod
    def _generate_trade_actions(
        cls,
        positions: list[PositionLikeProtocol],
        current_allocation: dict[str, float],
        target_allocation: AssetAllocation,
        total_assets: float,
        regime: str,
        asset_name_resolver: AssetNameResolverProtocol | None = None,
    ) -> list[TradeAction]:
        """生成具体操作建议"""
        actions = []
        target_dict = {
            "equity": target_allocation.equity,
            "fixed_income": target_allocation.fixed_income,
            "commodity": target_allocation.commodity,
            "cash": target_allocation.cash,
        }

        # 按优先级处理：先处理需要减仓的资产，再处理需要加仓的
        asset_classes = sorted(
            ["equity", "fixed_income", "commodity", "cash"],
            key=lambda x: (target_dict[x] - current_allocation.get(x, 0)),
        )

        priority = 1
        recommended_assets_map = cls._get_recommended_assets()
        all_candidate_codes = {p.asset_code for p in positions}
        for assets_by_class in recommended_assets_map.get(regime, {}).values():
            all_candidate_codes.update(assets_by_class)
        asset_name_map = cls._resolve_asset_names(
            list(all_candidate_codes),
            asset_name_resolver=asset_name_resolver,
        )

        for asset_class in asset_classes:
            diff = target_dict[asset_class] - current_allocation.get(asset_class, 0.0)

            # 忽略微小差异（小于5%）
            if abs(diff) < 0.05:
                continue

            diff_amount = diff * total_assets

            if diff < 0:  # 需要减仓
                # 找出该资产类别中需要卖出的持仓
                class_positions = [p for p in positions if p.asset_class.value == asset_class]

                if class_positions:
                    # 按市值从大到小排序，优先卖出大仓位
                    class_positions.sort(key=lambda p: float(p.market_value), reverse=True)

                    for pos in class_positions:
                        if diff_amount >= 0:  # 已经减够了
                            break

                        # 计算卖出金额（最多卖出全部）
                        sell_amount = min(abs(diff_amount), float(pos.market_value))
                        diff_amount += sell_amount  # 更新剩余需要减仓的金额

                        actions.append(TradeAction(
                            asset_code=pos.asset_code,
                            asset_name=asset_name_map.get(pos.asset_code, pos.asset_code),
                            action="sell",
                            amount=sell_amount,
                            reason=cls._get_sell_reason(asset_class, regime),
                            asset_class=asset_class,
                            priority=priority,
                        ))
                        priority += 1

            elif diff > 0:  # 需要加仓
                # 获取推荐的资产代码
                recommended_codes = recommended_assets_map.get(regime, {}).get(asset_class, [])

                if not recommended_codes:
                    continue

                # 按推荐顺序买入
                for code in recommended_codes:
                    if diff_amount <= 0:
                        break

                    # 平均分配到推荐的资产
                    buy_amount = diff_amount / len(recommended_codes)

                    actions.append(TradeAction(
                        asset_code=code,
                        asset_name=asset_name_map.get(code, code),
                        action="buy",
                        amount=buy_amount,
                        reason=cls._get_buy_reason(asset_class, regime),
                        asset_class=asset_class,
                        priority=priority,
                    ))
                    diff_amount -= buy_amount

        return actions

    @classmethod
    def _get_recommended_assets(cls) -> dict[str, dict[str, list[str]]]:
        """
        从配置读取 Regime 到资产代码的映射。

        未配置时默认返回空映射，避免在运行时注入硬编码证券代码。
        """
        configured = getattr(settings, "ALLOCATION_RECOMMENDED_ASSETS", {}) or {}
        if not isinstance(configured, dict):
            return {}
        return configured

    @classmethod
    def _resolve_asset_names(
        cls,
        codes: list[str],
        asset_name_resolver: AssetNameResolverProtocol | None = None,
    ) -> dict[str, str]:
        """批量解析证券名称，由调用方注入解析器。"""
        code_set = {code for code in codes if code}
        if not code_set or asset_name_resolver is None:
            return {}
        return asset_name_resolver.resolve_asset_names(list(code_set))

    @classmethod
    def _get_sell_reason(cls, asset_class: str, regime: str) -> str:
        """获取卖出理由"""
        reasons = {
            "equity": {
                "Recovery": "获利了结，适度降低权益仓位",
                "Overheat": "政策收紧风险，降低权益敞口",
                "Stagflation": "滞胀期权益资产承压，建议减仓",
                "Deflation": "经济衰退，权益资产风险较高",
            },
            "fixed_income": {
                "Recovery": "经济复苏期，可适度降低债券仓位",
                "Overheat": "通胀上升，债券实际收益下降",
                "Stagflation": "通胀压力下，债券表现不佳",
                "Deflation": "债券已经超配，适度获利",
            },
            "commodity": {
                "Recovery": "通胀温和，降低商品配置",
                "Overheat": "商品已有可观涨幅，适度止盈",
                "Stagflation": "商品已经超配，适度降低",
                "Deflation": "通缩压力，商品表现不佳",
            },
            "cash": {
                "Recovery": "经济复苏期，降低现金比例",
                "Overheat": "适度降低现金，参与市场",
                "Stagflation": "现金已经充足，适度使用",
                "Deflation": "适度降低现金，增加债券配置",
            },
        }
        return reasons.get(asset_class, {}).get(regime, "调仓至目标配置")

    @classmethod
    def _get_buy_reason(cls, asset_class: str, regime: str) -> str:
        """获取买入理由"""
        reasons = {
            "equity": {
                "Recovery": "经济复苏，企业盈利改善，权益资产表现优异",
                "Overheat": "适度参与股市，把握结构性机会",
                "Stagflation": "少量配置优质权益，等待机会",
                "Deflation": "低估值配置，等待经济复苏",
            },
            "fixed_income": {
                "Recovery": "配置债券提供稳定收益",
                "Overheat": "增加债券配置，防御市场波动",
                "Stagflation": "配置短债，防御风险",
                "Deflation": "经济衰退期，债券表现优异",
            },
            "commodity": {
                "Recovery": "适度配置商品，对冲通胀风险",
                "Overheat": "通胀上升，商品表现优异",
                "Stagflation": "商品是滞胀期最佳资产之一",
                "Deflation": "通缩期降低商品配置",
            },
            "cash": {
                "Recovery": "保持适度现金，等待加仓机会",
                "Overheat": "增加现金，应对市场波动",
                "Stagflation": "现金是滞胀期避风港",
                "Deflation": "保持现金，把握未来机会",
            },
        }
        return reasons.get(asset_class, {}).get(regime, "调仓至目标配置")

    @classmethod
    def _generate_summary(
        cls,
        regime: str,
        risk_profile: str,
        policy_level: str | None,
        current_allocation: dict[str, float],
        target_allocation: AssetAllocation,
        trade_actions: list[TradeAction],
    ) -> str:
        """生成配置摘要"""
        regime_display = {
            "Recovery": "复苏期",
            "Overheat": "过热期",
            "Stagflation": "滞胀期",
            "Deflation": "衰退期",
        }.get(regime, regime)

        policy_display = f"（{policy_level}）" if policy_level and policy_level != "P0" else ""

        # 统计需要操作的资产
        sells = [a for a in trade_actions if a.action == "sell"]
        buys = [a for a in trade_actions if a.action == "buy"]

        summary_parts = [
            f"基于当前【{regime_display}】{policy_display}环境，",
            f"{'激进型' if risk_profile == 'aggressive' else '稳健型' if risk_profile == 'moderate' else '保守型' if risk_profile == 'conservative' else '防御型'}投资者的目标配置为：",
        ]

        # 添加目标配置
        target_dict = target_allocation.to_percentage_dict()
        summary_parts.append(
            f"权益{target_dict['equity']}%、债券{target_dict['fixed_income']}%、"
            f"商品{target_dict['commodity']}%、现金{target_dict['cash']}%"
        )

        # 添加操作建议
        if sells or buys:
            summary_parts.append("。建议操作：")

            if sells:
                sell_summary = ", ".join([f"卖出{a.asset_code} {a.amount:,.0f}元" for a in sells[:2]])
                if len(sells) > 2:
                    sell_summary += f"等{len(sells)}项"
                summary_parts.append(sell_summary)

            if buys:
                buy_summary = ", ".join([f"买入{a.asset_code} {a.amount:,.0f}元" for a in buys[:2]])
                if len(buys) > 2:
                    buy_summary += f"等{len(buys)}项"
                summary_parts.append(buy_summary)

        return "".join(summary_parts)
