"""
Account Domain Services

持仓业务逻辑（纯函数）。
遵循四层架构约束：只使用 Python 标准库。
"""

from decimal import Decimal
from typing import List, Dict, Tuple
from dataclasses import dataclass

from apps.account.domain.entities import (
    Position,
    AccountProfile,
    RiskTolerance,
    AssetClassType,
    Region,
    CrossBorderFlag,
    AssetAllocation,
    RegimeMatchAnalysis,
    InvestmentStyle,
    PositionStatus,
)


@dataclass(frozen=True)
class PositionCalculationResult:
    """持仓计算结果"""
    shares: float              # 建议持仓数量
    notional: Decimal          # 建议投入金额
    cash_required: Decimal     # 所需现金
    max_loss: Decimal          # 最大可能损失（基于证伪阈值）


class PositionService:
    """
    持仓业务逻辑服务

    提供：
    1. 仓位大小计算
    2. Regime匹配度计算
    3. 资产配置分析
    4. 风险评估
    """

    # 准入矩阵（预定义，与 signal/domain/rules.py 保持一致）
    ELIGIBILITY_MATRIX: Dict[Tuple[str, str], Dict[str, str]] = {
        # (asset_class, region) -> {regime: eligibility}
        ("equity", "CN"): {
            "Recovery": "preferred",
            "Overheat": "neutral",
            "Stagflation": "hostile",
            "Deflation": "neutral",
        },
        ("equity", "US"): {
            "Recovery": "preferred",
            "Overheat": "preferred",
            "Stagflation": "neutral",
            "Deflation": "hostile",
        },
        ("equity", "EM"): {
            "Recovery": "preferred",
            "Overheat": "neutral",
            "Stagflation": "hostile",
            "Deflation": "hostile",
        },
        ("fixed_income", "CN"): {
            "Recovery": "neutral",
            "Overheat": "hostile",
            "Stagflation": "neutral",
            "Deflation": "preferred",
        },
        ("fixed_income", "US"): {
            "Recovery": "neutral",
            "Overheat": "hostile",
            "Stagflation": "neutral",
            "Deflation": "preferred",
        },
        ("commodity", "CN"): {
            "Recovery": "neutral",
            "Overheat": "preferred",
            "Stagflation": "hostile",
            "Deflation": "hostile",
        },
        ("fund", "CN"): {
            "Recovery": "preferred",
            "Overheat": "neutral",
            "Stagflation": "neutral",
            "Deflation": "neutral",
        },
        ("cash", "CN"): {
            "Recovery": "hostile",
            "Overheat": "neutral",
            "Stagflation": "preferred",
            "Deflation": "neutral",
        },
    }

    @staticmethod
    def calculate_position_size(
        account_capital: Decimal,
        risk_tolerance: RiskTolerance,
        asset_class: AssetClassType,
        region: Region,
        current_price: Decimal,
    ) -> PositionCalculationResult:
        """
        计算建议仓位大小

        算法：
        - 根据风险偏好确定单一资产最大仓位比例
        - 根据资产类别和地区调整（如波动资产降低仓位）
        - 计算具体股数和所需现金

        Args:
            account_capital: 账户总资金
            risk_tolerance: 风险偏好
            asset_class: 资产大类
            region: 地区
            current_price: 当前价格

        Returns:
            PositionCalculationResult: 建议持仓计算结果
        """
        # 基础最大仓位比例
        max_position_pct = {
            RiskTolerance.CONSERVATIVE: 0.05,   # 5%
            RiskTolerance.MODERATE: 0.10,       # 10%
            RiskTolerance.AGGRESSIVE: 0.20,     # 20%
        }[risk_tolerance]

        # 资产类别调整因子（波动大的资产降低仓位）
        asset_adjustment = {
            AssetClassType.EQUITY: 1.0,
            AssetClassType.FIXED_INCOME: 1.2,   # 债券可以多配
            AssetClassType.COMMODITY: 0.7,      # 商品波动大，少配
            AssetClassType.CURRENCY: 0.6,
            AssetClassType.FUND: 1.0,
            AssetClassType.DERIVATIVE: 0.3,     # 衍生品极高风险
            AssetClassType.CASH: 1.0,
            AssetClassType.OTHER: 0.5,
        }

        # 地区调整因子（新兴市场降低仓位）
        region_adjustment = {
            Region.CN: 1.0,
            Region.US: 1.0,
            Region.EU: 1.0,
            Region.JP: 0.9,
            Region.EM: 0.7,      # 新兴市场降低仓位
            Region.GLOBAL: 1.0,
            Region.OTHER: 0.6,
        }

        # 跨境调整因子
        cross_border_adjustment = {
            CrossBorderFlag.DOMESTIC: 1.0,
            CrossBorderFlag.QDII: 0.8,         # QDII降低仓位
            CrossBorderFlag.DIRECT_FOREIGN: 0.6,  # 境外直投降低仓位
        }

        # 综合调整
        final_pct = (
            max_position_pct *
            asset_adjustment.get(asset_class, 1.0) *
            region_adjustment.get(region, 1.0) *
            cross_border_adjustment.get(CrossBorderFlag.DOMESTIC, 1.0)  # 默认按境内处理
        )

        # 计算投入金额和股数
        notional = float(account_capital) * final_pct
        shares = int(notional / float(current_price))

        # 重新计算实际投入金额（向下取整）
        actual_notional = Decimal(str(shares * float(current_price)))

        return PositionCalculationResult(
            shares=float(shares),
            notional=actual_notional,
            cash_required=actual_notional,
            max_loss=actual_notional * Decimal("0.2"),  # 假设最大止损20%
        )

    @staticmethod
    def calculate_regime_match_score(
        positions: List[Position],
        current_regime: str,
    ) -> RegimeMatchAnalysis:
        """
        计算持仓与当前Regime的匹配度

        算法：
        1. 遍历每个持仓
        2. 根据资产大类和地区查询准入矩阵
        3. preferred = 100分, neutral = 50分, hostile = 0分
        4. 按市值加权计算总分

        Args:
            positions: 持仓列表
            current_regime: 当前Regime

        Returns:
            RegimeMatchAnalysis: Regime匹配分析结果
        """
        if not positions:
            return RegimeMatchAnalysis(
                regime=current_regime,
                total_match_score=100.0,
                preferred_assets=[],
                neutral_assets=[],
                hostile_assets=[],
                recommendations=["暂无持仓，建议根据当前Regime建仓"],
            )

        total_value = 0.0
        matched_value = 0.0
        preferred_assets = []
        neutral_assets = []
        hostile_assets = []

        for pos in positions:
            value = float(pos.market_value)
            total_value += value

            # 查询准入矩阵
            asset_class_key = pos.asset_class.value.lower()
            region_key = pos.region.value.upper()
            matrix_key = (asset_class_key, region_key)

            if matrix_key in PositionService.ELIGIBILITY_MATRIX:
                eligibility = PositionService.ELIGIBILITY_MATRIX[matrix_key].get(current_regime, "neutral")
            else:
                eligibility = "neutral"  # 默认中性

            # 记录资产
            asset_info = f"{pos.asset_code} ({value:.0f})"

            if eligibility == "preferred":
                matched_value += value
                preferred_assets.append(asset_info)
            elif eligibility == "neutral":
                matched_value += value * 0.5
                neutral_assets.append(asset_info)
            else:  # hostile
                hostile_assets.append(asset_info)

        # 计算总分
        total_match_score = (matched_value / total_value * 100) if total_value > 0 else 0

        # 生成建议
        recommendations = PositionService._generate_regime_recommendations(
            current_regime,
            total_match_score,
            preferred_assets,
            neutral_assets,
            hostile_assets,
        )

        return RegimeMatchAnalysis(
            regime=current_regime,
            total_match_score=round(total_match_score, 1),
            preferred_assets=preferred_assets,
            neutral_assets=neutral_assets,
            hostile_assets=hostile_assets,
            recommendations=recommendations,
        )

    @staticmethod
    def _generate_regime_recommendations(
        regime: str,
        score: float,
        preferred: List[str],
        neutral: List[str],
        hostile: List[str],
    ) -> List[str]:
        """生成Regime匹配建议"""
        recommendations = []

        if score >= 80:
            recommendations.append(f"✓ 当前持仓与{regime}象限高度匹配，建议维持配置")
        elif score >= 50:
            recommendations.append(f"△ 当前持仓与{regime}象限基本匹配，可适度优化")
        else:
            recommendations.append(f"⚠ 当前持仓与{regime}象限匹配度较低，建议调整")

        # 针对不匹配资产的建议
        if hostile:
            recommendations.append(f"建议减少或平仓以下不匹配资产: {', '.join([a.split()[0] for a in hostile[:3]])}")

        # 针对优选资产的建议
        if regime == "Recovery":
            recommendations.append("复苏期建议：增加权益仓位至70%以上，关注成长股")
        elif regime == "Overheat":
            recommendations.append("过热期建议：增加商品和通胀对冲，降低久期")
        elif regime == "Stagflation":
            recommendations.append("滞胀期建议：增加现金和短债，关注防御股和黄金")
        elif regime == "Deflation":
            recommendations.append("通缩期建议：增加长久期国债，降低权益仓位")

        return recommendations

    @staticmethod
    def calculate_asset_allocation(
        positions: List[Position],
        dimension: str = "asset_class",
    ) -> List[AssetAllocation]:
        """
        计算资产配置分布

        Args:
            positions: 持仓列表
            dimension: 统计维度 (asset_class, region, cross_border, style, sector)

        Returns:
            List[AssetAllocation]: 资产配置列表
        """
        if not positions:
            return []

        # 按维度分组
        groups: Dict[str, Dict[str, float]] = {}

        for pos in positions:
            # 获取维度值
            if dimension == "asset_class":
                dim_value = pos.asset_class.value
            elif dimension == "region":
                dim_value = pos.region.value
            elif dimension == "cross_border":
                dim_value = pos.cross_border.value
            else:
                dim_value = "other"

            if dim_value not in groups:
                groups[dim_value] = {"value": 0.0, "count": 0, "codes": []}

            groups[dim_value]["value"] += float(pos.market_value)
            groups[dim_value]["count"] += 1
            groups[dim_value]["codes"].append(pos.asset_code)

        # 计算总市值
        total_value = sum(g["value"] for g in groups.values())

        # 转换为AssetAllocation列表
        allocations = []
        for dim_value, data in sorted(groups.items(), key=lambda x: -x[1]["value"]):
            allocations.append(AssetAllocation(
                dimension=dimension,
                dimension_value=dim_value,
                count=data["count"],
                market_value=Decimal(str(data["value"])),
                percentage=(data["value"] / total_value * 100) if total_value > 0 else 0,
                asset_codes=data["codes"],
            ))

        return allocations

    @staticmethod
    def assess_portfolio_risk(
        positions: List[Position],
        account_capital: Decimal,
    ) -> Dict[str, any]:
        """
        评估组合风险

        Returns:
            {
                "total_exposure": float,      # 总敞口
                "concentration_ratio": float, # 集中度（前十大持仓占比）
                "geographic_diversification": float,  # 地区分散度
                "currency_diversification": float,     # 币种分散度
                "risk_level": str,           # 风险等级 (low/medium/high)
            }
        """
        if not positions:
            return {
                "total_exposure": 0.0,
                "concentration_ratio": 0.0,
                "geographic_diversification": 0.0,
                "currency_diversification": 0.0,
                "risk_level": "low",
            }

        total_value = sum(float(pos.market_value) for pos in positions)
        total_exposure = total_value / float(account_capital)

        # 计算集中度（前三大持仓占比）
        sorted_positions = sorted(positions, key=lambda p: float(p.market_value), reverse=True)
        top3_value = sum(float(sorted_positions[i].market_value) for i in range(min(3, len(sorted_positions))))
        concentration_ratio = top3_value / total_value if total_value > 0 else 0

        # 计算地区分散度（使用赫芬达尔指数）
        region_counts: Dict[str, float] = {}
        for pos in positions:
            region = pos.region.value
            region_counts[region] = region_counts.get(region, 0) + float(pos.market_value)

        hhi = sum((v / total_value) ** 2 for v in region_counts.values()) if total_value > 0 else 0
        geographic_diversification = 1 - hhi  # 越高越分散

        # 风险等级判定
        if total_exposure > 0.95 or concentration_ratio > 0.7:
            risk_level = "high"
        elif total_exposure > 0.8 or concentration_ratio > 0.5:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "total_exposure": round(total_exposure, 3),
            "concentration_ratio": round(concentration_ratio, 3),
            "geographic_diversification": round(geographic_diversification, 3),
            "currency_diversification": 0.5,  # 简化处理
            "risk_level": risk_level,
        }
