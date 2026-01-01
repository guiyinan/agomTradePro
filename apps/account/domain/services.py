"""
Account Domain Services

持仓业务逻辑（纯函数）。
遵循四层架构约束：只使用 Python 标准库。
"""

from decimal import Decimal
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime, date

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


# ============================================================
# 止损止盈服务
# ============================================================

@dataclass(frozen=True)
class StopLossCheckResult:
    """止损检查结果"""
    should_trigger: bool      # 是否应该触发止损
    trigger_reason: str       # 触发原因
    stop_price: float         # 止损价格
    current_price: float      # 当前价格
    unrealized_pnl_pct: float # 未实现盈亏百分比
    highest_price: float      # 最高价（用于移动止损）


class StopLossService:
    """
    止损业务逻辑服务

    提供：
    1. 固定止损检查
    2. 移动止损检查
    3. 时间止损检查
    """

    @staticmethod
    def check_stop_loss(
        entry_price: float,
        current_price: float,
        highest_price: float,
        stop_loss_pct: float,
        stop_loss_type: str,
        trailing_stop_pct: Optional[float] = None,
    ) -> StopLossCheckResult:
        """
        检查是否触发止损

        Args:
            entry_price: 开仓价格
            current_price: 当前价格
            highest_price: 持仓期间最高价
            stop_loss_pct: 止损百分比（负数，如 -0.10）
            stop_loss_type: 止损类型 (fixed/trailing/time_based)
            trailing_stop_pct: 移动止损百分比

        Returns:
            StopLossCheckResult: 检查结果
        """
        unrealized_pnl_pct = (current_price / entry_price - 1)

        if stop_loss_type == "fixed":
            # 固定止损：当前价格跌破止损线
            stop_price = entry_price * (1 + stop_loss_pct)
            should_trigger = current_price <= stop_price
            reason = f"固定止损触发：当前价 {current_price:.2f} 跌破止损价 {stop_price:.2f}"

        elif stop_loss_type == "trailing":
            # 移动止损：当前价格跌破移动止损线（基于最高价）
            trailing_pct = trailing_stop_pct or stop_loss_pct
            stop_price = highest_price * (1 - trailing_pct)
            should_trigger = current_price <= stop_price
            reason = f"移动止损触发：当前价 {current_price:.2f} 跌破止损价 {stop_price:.2f}（基于最高价 {highest_price:.2f}）"

        else:
            # 其他类型暂不处理
            should_trigger = False
            stop_price = entry_price * (1 + stop_loss_pct)
            reason = "未触发"

        return StopLossCheckResult(
            should_trigger=should_trigger,
            trigger_reason=reason,
            stop_price=stop_price,
            current_price=current_price,
            unrealized_pnl_pct=unrealized_pnl_pct,
            highest_price=highest_price,
        )

    @staticmethod
    def check_time_stop_loss(
        opened_at: datetime,
        current_time: datetime,
        max_holding_days: int,
    ) -> StopLossCheckResult:
        """
        检查时间止损

        Args:
            opened_at: 开仓时间
            current_time: 当前时间
            max_holding_days: 最大持仓天数

        Returns:
            StopLossCheckResult: 检查结果
        """
        holding_days = (current_time - opened_at).days
        should_trigger = holding_days >= max_holding_days

        return StopLossCheckResult(
            should_trigger=should_trigger,
            trigger_reason=f"时间止损触发：持仓 {holding_days} 天已达最大持仓天数 {max_holding_days} 天",
            stop_price=0.0,
            current_price=0.0,
            unrealized_pnl_pct=0.0,
            highest_price=0.0,
        )

    @staticmethod
    def update_trailing_stop_highest(
        current_highest: float,
        current_price: float,
        current_price_time: datetime,
        last_update_time: Optional[datetime],
    ) -> tuple[float, datetime]:
        """
        更新移动止损的最高价

        Args:
            current_highest: 当前记录的最高价
            current_price: 当前价格
            current_price_time: 当前价格时间
            last_update_time: 上次更新时间

        Returns:
            (new_highest, new_update_time)
        """
        if current_price > current_highest:
            return current_price, current_price_time
        return current_highest, last_update_time or current_price_time


@dataclass(frozen=True)
class TakeProfitCheckResult:
    """止盈检查结果"""
    should_trigger: bool      # 是否应该触发止盈
    trigger_reason: str       # 触发原因
    take_profit_price: float  # 止盈价格
    current_price: float      # 当前价格
    unrealized_pnl_pct: float # 未实现盈亏百分比
    partial_level: Optional[int] = None  # 分批止盈级别


class TakeProfitService:
    """
    止盈业务逻辑服务
    """

    @staticmethod
    def check_take_profit(
        entry_price: float,
        current_price: float,
        take_profit_pct: float,
        partial_levels: Optional[List[float]] = None,
    ) -> TakeProfitCheckResult:
        """
        检查是否触发止盈

        Args:
            entry_price: 开仓价格
            current_price: 当前价格
            take_profit_pct: 止盈百分比（正数，如 0.20）
            partial_levels: 分批止盈点位

        Returns:
            TakeProfitCheckResult: 检查结果
        """
        unrealized_pnl_pct = (current_price / entry_price - 1)

        if partial_levels:
            # 分批止盈：检查每个级别
            for i, level in enumerate(partial_levels):
                if unrealized_pnl_pct >= level:
                    return TakeProfitCheckResult(
                        should_trigger=True,
                        trigger_reason=f"分批止盈触发级别 {i+1}/{len(partial_levels)}：收益率 {unrealized_pnl_pct:.2%} 达到 {level:.2%}",
                        take_profit_price=entry_price * (1 + level),
                        current_price=current_price,
                        unrealized_pnl_pct=unrealized_pnl_pct,
                        partial_level=i + 1,
                    )

        # 全部止盈
        take_profit_price = entry_price * (1 + take_profit_pct)
        should_trigger = current_price >= take_profit_price

        return TakeProfitCheckResult(
            should_trigger=should_trigger,
            trigger_reason=f"止盈触发：当前价 {current_price:.2f} 达到止盈价 {take_profit_price:.2f}" if should_trigger else "未触发",
            take_profit_price=take_profit_price,
            current_price=current_price,
            unrealized_pnl_pct=unrealized_pnl_pct,
        )


# ============================================================
# 波动率控制服务
# ============================================================

@dataclass(frozen=True)
class VolatilityMetrics:
    """波动率指标"""
    daily_volatility: float      # 日波动率
    annualized_volatility: float # 年化波动率
    window_days: int             # 计算窗口
    as_of_date: date             # 截止日期


@dataclass(frozen=True)
class VolatilityAdjustmentResult:
    """波动率调整结果"""
    current_volatility: float       # 当前波动率（年化）
    target_volatility: float        # 目标波动率
    volatility_ratio: float         # 波动率比率（current / target）
    should_reduce: bool             # 是否需要降仓
    suggested_position_multiplier: float  # 建议仓位乘数
    reduction_reason: str           # 降仓原因


class VolatilityCalculator:
    """
    波动率计算服务

    计算投资组合的历史波动率，用于风险控制。
    """

    @staticmethod
    def calculate_volatility(
        returns: List[float],
        window_days: int = 30,
        annualize: bool = True,
    ) -> VolatilityMetrics:
        """
        计算波动率

        Args:
            returns: 收益率序列（如 [0.01, -0.02, 0.015, ...]）
            window_days: 计算窗口（天数）
            annualize: 是否年化

        Returns:
            VolatilityMetrics: 波动率指标
        """
        if not returns or len(returns) < 2:
            return VolatilityMetrics(
                daily_volatility=0.0,
                annualized_volatility=0.0,
                window_days=window_days,
                as_of_date=date.today(),
            )

        # 计算标准差
        import statistics
        daily_vol = statistics.stdev(returns[-window_days:]) if len(returns) >= window_days else statistics.stdev(returns)

        # 年化（假设252个交易日）
        annualized_vol = daily_vol * (252 ** 0.5) if annualize else daily_vol

        return VolatilityMetrics(
            daily_volatility=daily_vol,
            annualized_volatility=annualized_vol,
            window_days=window_days,
            as_of_date=date.today(),
        )

    @staticmethod
    def calculate_portfolio_volatility(
        daily_snapshots: List[Dict[str, float]],
        window_days: int = 30,
    ) -> List[VolatilityMetrics]:
        """
        计算投资组合滚动波动率

        Args:
            daily_snapshots: 每日快照列表 [{"date": "2024-01-01", "total_value": 1000000}, ...]
            window_days: 滚动窗口天数

        Returns:
            List[VolatilityMetrics]: 每日的波动率指标
        """
        if len(daily_snapshots) < 2:
            return []

        # 计算每日收益率
        returns = []
        for i in range(1, len(daily_snapshots)):
            prev_value = daily_snapshots[i - 1]["total_value"]
            curr_value = daily_snapshots[i]["total_value"]
            daily_return = (curr_value - prev_value) / prev_value
            returns.append(daily_return)

        # 计算滚动波动率
        metrics_list = []
        for i in range(window_days - 1, len(returns)):
            window_returns = returns[max(0, i - window_days + 1):i + 1]
            metrics = VolatilityCalculator.calculate_volatility(
                returns=window_returns,
                window_days=window_days,
                annualize=True,
            )
            metrics_list.append(metrics)

        return metrics_list


class VolatilityTargetService:
    """
    波动率目标控制服务

    根据目标波动率动态调整仓位。
    """

    @staticmethod
    def assess_volatility_adjustment(
        current_volatility: float,
        target_volatility: float,
        tolerance: float = 0.2,
        max_reduction: float = 0.5,
    ) -> VolatilityAdjustmentResult:
        """
        评估是否需要调整仓位

        Args:
            current_volatility: 当前波动率（年化）
            target_volatility: 目标波动率（年化）
            tolerance: 容忍度（如0.2表示超过20%才触发）
            max_reduction: 最大降仓幅度（如0.5表示最多降50%）

        Returns:
            VolatilityAdjustmentResult: 调整建议
        """
        volatility_ratio = current_volatility / target_volatility if target_volatility > 0 else 1.0

        # 判断是否需要降仓（超过容忍度）
        should_reduce = volatility_ratio > (1 + tolerance)

        # 计算建议仓位乘数
        if should_reduce:
            # 目标：使实际波动率回到目标水平
            # 公式：new_position = current_position * (target_vol / actual_vol)
            suggested_multiplier = min(
                target_volatility / current_volatility,
                1.0 - max_reduction,  # 最大降仓限制
            )
            reduction_reason = (
                f"当前波动率 {current_volatility:.2%} 超过目标波动率 {target_volatility:.2%} "
                f"（{volatility_ratio:.2f}倍），建议降仓至 {suggested_multiplier:.1%}"
            )
        else:
            suggested_multiplier = 1.0
            reduction_reason = "波动率正常，无需调整"

        return VolatilityAdjustmentResult(
            current_volatility=current_volatility,
            target_volatility=target_volatility,
            volatility_ratio=volatility_ratio,
            should_reduce=should_reduce,
            suggested_position_multiplier=suggested_multiplier,
            reduction_reason=reduction_reason,
        )

    @staticmethod
    def get_default_target_volatility(risk_tolerance: str) -> float:
        """
        根据风险偏好获取默认目标波动率

        Args:
            risk_tolerance: 风险偏好 (conservative/moderate/aggressive)

        Returns:
            目标波动率（年化）
        """
        defaults = {
            "conservative": 0.10,  # 10%
            "moderate": 0.15,      # 15%
            "aggressive": 0.20,    # 20%
        }
        return defaults.get(risk_tolerance.lower(), 0.15)


# ============================================================
# 多维限额控制服务
# ============================================================

@dataclass(frozen=True)
class LimitCheckResult:
    """限额检查结果"""
    dimension: str                # 维度名称（style, sector, currency）
    dimension_value: str          # 维度值
    current_value: Decimal        # 当前值
    limit_value: Decimal          # 限额值
    current_ratio: float          # 当前占比
    limit_ratio: float            # 限额占比
    exceeds_limit: bool           # 是否超限
    can_add_position: bool        # 是否可以新增持仓
    warning_message: str          # 警告消息


@dataclass(frozen=True)
class MultiDimensionLimits:
    """多维限额配置"""
    # 风格限额（单一风格最大占比）
    max_style_ratio: float = 0.40       # 40%
    # 行业限额（单一行业最大占比）
    max_sector_ratio: float = 0.25      # 25%
    # 币种限额（非本币资产最大占比）
    max_foreign_currency_ratio: float = 0.30  # 30%
    # 地区限额
    max_region_ratio: float = 0.50      # 50%


class LimitCheckService:
    """
    限额检查服务

    检查多维度持仓限额，防止过度集中。
    """

    @staticmethod
    def check_style_limit(
        positions: List[Position],
        new_position_style: str,
        limits: MultiDimensionLimits = None,
    ) -> LimitCheckResult:
        """
        检查投资风格限额

        Args:
            positions: 当前持仓列表
            new_position_style: 新增持仓的风格
            limits: 限额配置

        Returns:
            LimitCheckResult: 限额检查结果
        """
        if limits is None:
            limits = MultiDimensionLimits()

        # 计算当前该风格的市值
        total_value = sum(float(pos.market_value) for pos in positions)
        style_value = sum(
            float(pos.market_value) for pos in positions
            if hasattr(pos, 'style') and pos.style.value.lower() == new_position_style.lower()
        )

        current_ratio = style_value / total_value if total_value > 0 else 0
        limit_ratio = limits.max_style_ratio
        exceeds_limit = current_ratio >= limit_ratio

        return LimitCheckResult(
            dimension='style',
            dimension_value=new_position_style,
            current_value=Decimal(str(style_value)),
            limit_value=Decimal(str(total_value * limit_ratio)),
            current_ratio=current_ratio,
            limit_ratio=limit_ratio,
            exceeds_limit=exceeds_limit,
            can_add_position=not exceeds_limit,
            warning_message=(
                f"投资风格 '{new_position_style}' 当前占比 {current_ratio:.1%}，"
                f"已达限额 {limit_ratio:.1%}，建议减少该风格持仓或选择其他风格"
                if exceeds_limit else ""
            ),
        )

    @staticmethod
    def check_sector_limit(
        positions: List[Position],
        new_position_sector: str,
        limits: MultiDimensionLimits = None,
    ) -> LimitCheckResult:
        """
        检查行业板块限额

        Args:
            positions: 当前持仓列表
            new_position_sector: 新增持仓的行业
            limits: 限额配置

        Returns:
            LimitCheckResult: 限额检查结果
        """
        if limits is None:
            limits = MultiDimensionLimits()

        # 计算当前该行业的市值
        total_value = sum(float(pos.market_value) for pos in positions)

        # 从 sector 属性获取行业信息（如果有的话）
        sector_value = 0.0
        for pos in positions:
            # 假设 sector 信息存储在某处，这里简化处理
            # 实际应从 AssetMetadata 或 Position 获取
            pass

        # 暂时返回不超限（需要更完善的行业分类数据）
        current_ratio = sector_value / total_value if total_value > 0 else 0
        limit_ratio = limits.max_sector_ratio

        return LimitCheckResult(
            dimension='sector',
            dimension_value=new_position_sector,
            current_value=Decimal(str(sector_value)),
            limit_value=Decimal(str(total_value * limit_ratio)),
            current_ratio=current_ratio,
            limit_ratio=limit_ratio,
            exceeds_limit=False,
            can_add_position=True,
            warning_message="",
        )

    @staticmethod
    def check_currency_limit(
        positions: List[Position],
        new_position_currency: str,
        base_currency: str = "CNY",
        limits: MultiDimensionLimits = None,
    ) -> LimitCheckResult:
        """
        检查币种限额

        Args:
            positions: 当前持仓列表
            new_position_currency: 新增持仓的币种
            base_currency: 基准货币
            limits: 限额配置

        Returns:
            LimitCheckResult: 限额检查结果
        """
        if limits is None:
            limits = MultiDimensionLimits()

        # 计算当前该币种的市值
        total_value = sum(float(pos.market_value) for pos in positions)

        # 汇总非本币资产
        foreign_value = 0.0
        for pos in positions:
            # 简化处理：假设 region 可推断币种
            if pos.region.value != "CN":  # 非中国资产视为外币
                foreign_value += float(pos.market_value)

        # 如果新增的是外币持仓
        if new_position_currency != base_currency:
            current_ratio = foreign_value / total_value if total_value > 0 else 0
            limit_ratio = limits.max_foreign_currency_ratio
            exceeds_limit = current_ratio >= limit_ratio
        else:
            current_ratio = foreign_value / total_value if total_value > 0 else 0
            limit_ratio = limits.max_foreign_currency_ratio
            exceeds_limit = False  # 增加持仓本币不会增加外币占比

        return LimitCheckResult(
            dimension='currency',
            dimension_value=new_position_currency,
            current_value=Decimal(str(foreign_value)),
            limit_value=Decimal(str(total_value * limit_ratio)),
            current_ratio=current_ratio,
            limit_ratio=limit_ratio,
            exceeds_limit=exceeds_limit,
            can_add_position=not exceeds_limit,
            warning_message=(
                f"外币资产占比 {current_ratio:.1%}，已达限额 {limit_ratio:.1%}，"
                f"建议控制外币资产敞口"
                if exceeds_limit else ""
            ),
        )

    @staticmethod
    def check_all_limits(
        positions: List[Position],
        new_asset_code: str,
        new_style: str,
        new_sector: str,
        new_currency: str,
        limits: MultiDimensionLimits = None,
    ) -> List[LimitCheckResult]:
        """
        检查所有限额

        Args:
            positions: 当前持仓列表
            new_asset_code: 新资产代码
            new_style: 新资产风格
            new_sector: 新资产行业
            new_currency: 新资产币种
            limits: 限额配置

        Returns:
            List[LimitCheckResult]: 所有限额检查结果
        """
        results = []

        # 检查风格限额
        style_result = LimitCheckService.check_style_limit(
            positions=positions,
            new_position_style=new_style,
            limits=limits,
        )
        results.append(style_result)

        # 检查行业限额
        sector_result = LimitCheckService.check_sector_limit(
            positions=positions,
            new_position_sector=new_sector,
            limits=limits,
        )
        results.append(sector_result)

        # 检查币种限额
        currency_result = LimitCheckService.check_currency_limit(
            positions=positions,
            new_position_currency=new_currency,
            limits=limits,
        )
        results.append(currency_result)

        return results

    @staticmethod
    def should_reject_position(
        limit_results: List[LimitCheckResult],
    ) -> tuple[bool, str]:
        """
        判断是否应该拒绝新增持仓

        Args:
            limit_results: 限额检查结果列表

        Returns:
            (should_reject, reason): 是否拒绝及原因
        """
        rejected_results = [r for r in limit_results if r.exceeds_limit]

        if not rejected_results:
            return False, ""

        reasons = [r.warning_message for r in rejected_results if r.warning_message]
        return True, "; ".join(reasons)
