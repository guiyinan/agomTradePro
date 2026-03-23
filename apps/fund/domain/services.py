"""
基金分析模块 - Domain 层服务

遵循项目架构约束：
- 纯业务逻辑，不依赖 Django ORM
- 不依赖外部库（pandas、numpy 等）
- 通过依赖注入接收数据
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Tuple

from .entities import (
    FundHolding,
    FundInfo,
    FundNetValue,
    FundPerformance,
    FundScore,
    FundSectorAllocation,
)


class FundScreener:
    """基金筛选服务（纯 Domain 层逻辑）

    职责：
    1. 基于 Regime 筛选基金类型
    2. 计算基金综合评分
    3. 排序和排名
    """

    def screen_by_regime(
        self,
        all_funds: list[tuple[FundInfo, FundPerformance, list[FundSectorAllocation]]],
        preferred_types: list[str],
        preferred_styles: list[str],
        min_scale: Decimal = Decimal(0),
        max_count: int = 30
    ) -> list[str]:
        """基于 Regime 筛选基金

        Args:
            all_funds: [(基金信息, 业绩, 行业配置)] 列表
            preferred_types: 偏好的基金类型列表（由 Application 层注入）
            preferred_styles: 偏好的投资风格列表（由 Application 层注入）
            min_scale: 最低基金规模（元）
            max_count: 最多返回基金数量

        Returns:
            符合条件的基金代码列表（按评分降序）

        Examples:
            >>> fund_info = FundInfo('110011', '易方达中小盘', '混合型', '成长')
            >>> fund_perf = FundPerformance('110011', date(2024,1,1), date(2024,12,31), 15.5)
            >>> screener = FundScreener()
            >>> codes = screener.screen_by_regime(
            ...     [(fund_info, fund_perf, [])],
            ...     preferred_types=['混合型'],
            ...     preferred_styles=['成长']
            ... )
        """
        matched_funds = []

        for fund_info, fund_perf, sector_alloc in all_funds:
            # 1. 基金类型过滤
            if fund_info.fund_type not in preferred_types:
                continue

            # 2. 投资风格过滤
            if fund_info.investment_style and fund_info.investment_style not in preferred_styles:
                continue

            # 3. 基金规模过滤
            if fund_info.fund_scale and fund_info.fund_scale < min_scale:
                continue

            # 4. 计算评分
            score = self._calculate_fund_score(fund_info, fund_perf)
            matched_funds.append((fund_info.fund_code, score))

        # 按评分降序排序
        matched_funds.sort(key=lambda x: x[1], reverse=True)

        return [code for code, score in matched_funds[:max_count]]

    def rank_funds(
        self,
        funds_data: list[tuple[FundInfo, FundPerformance, list[FundSectorAllocation]]],
        regime_weights: dict[str, float],
        performance_weight: float = 0.4,
        regime_fit_weight: float = 0.3,
        risk_weight: float = 0.2,
        scale_weight: float = 0.1
    ) -> list[FundScore]:
        """对基金进行综合评分和排名

        Args:
            funds_data: [(基金信息, 业绩, 行业配置)] 列表
            regime_weights: Regime 权重配置（由 Application 层注入）
            performance_weight: 业绩评分权重
            regime_fit_weight: Regime 适配度权重
            risk_weight: 风险评分权重
            scale_weight: 规模评分权重

        Returns:
            按综合评分降序排列的 FundScore 列表
        """
        fund_scores = []

        for fund_info, fund_perf, sector_alloc in funds_data:
            # 1. 业绩评分（年化收益率映射到 0-100）
            perf_score = self._normalize_score(
                fund_perf.annualized_return or fund_perf.total_return,
                -20.0, 50.0  # 假设年化收益范围 -20% 到 50%
            )

            # 2. Regime 适配度评分
            # 根据基金类型和风格匹配 Regime 权重
            regime_fit = self._calculate_regime_fit_score(
                fund_info.fund_type,
                fund_info.investment_style,
                regime_weights
            )

            # 3. 风险评分（回撤越小越好，夏普越大越好）
            # 最大回撤映射（假设范围 0% 到 50%，越小越好）
            drawdown_score = 100 - self._normalize_score(
                fund_perf.max_drawdown or 0,
                0, 50
            )
            # 夏普比率映射（假设范围 -1 到 3）
            sharpe_score = self._normalize_score(
                fund_perf.sharpe_ratio or 0,
                -1, 3
            )
            risk_score = (drawdown_score + sharpe_score) / 2

            # 4. 规模评分（适中规模最好，假设 10-100 亿为理想规模）
            scale = fund_info.fund_scale or Decimal(0)
            scale_score = self._calculate_scale_score(scale)

            # 5. 综合评分
            total_score = (
                perf_score * performance_weight +
                regime_fit * regime_fit_weight +
                risk_score * risk_weight +
                scale_score * scale_weight
            )

            fund_scores.append(FundScore(
                fund_code=fund_info.fund_code,
                fund_name=fund_info.fund_name,
                score_date=fund_perf.end_date,
                performance_score=perf_score,
                regime_fit_score=regime_fit,
                risk_score=risk_score,
                scale_score=scale_score,
                total_score=total_score,
                rank=0
            ))

        # 按综合评分降序排序
        fund_scores.sort(key=lambda x: x.total_score, reverse=True)

        # 更新排名
        for i, score in enumerate(fund_scores, 1):
            fund_scores[i-1] = FundScore(
                fund_code=score.fund_code,
                fund_name=score.fund_name,
                score_date=score.score_date,
                performance_score=score.performance_score,
                regime_fit_score=score.regime_fit_score,
                risk_score=score.risk_score,
                scale_score=score.scale_score,
                total_score=score.total_score,
                rank=i
            )

        return fund_scores

    def _calculate_fund_score(
        self,
        fund_info: FundInfo,
        fund_perf: FundPerformance
    ) -> float:
        """计算基金单一评分（简化版）

        Args:
            fund_info: 基金信息
            fund_perf: 基金业绩

        Returns:
            综合评分
        """
        # 业绩评分（70%）
        perf_score = fund_perf.annualized_return or fund_perf.total_return

        # 风险调整后的收益（夏普比率，30%）
        risk_adj_score = (fund_perf.sharpe_ratio or 0) * 10

        total_score = perf_score * 0.7 + risk_adj_score * 0.3
        return total_score

    def _calculate_regime_fit_score(
        self,
        fund_type: str,
        investment_style: str,
        regime_weights: dict[str, float]
    ) -> float:
        """计算 Regime 适配度评分

        Args:
            fund_type: 基金类型
            investment_style: 投资风格
            regime_weights: Regime 权重配置

        Returns:
            适配度评分（0-100）
        """
        # 构造查找键
        type_key = f"{fund_type}"
        style_key = f"{fund_type}_{investment_style}" if investment_style else None

        # 获取权重
        weight = 0.5  # 默认权重
        if style_key and style_key in regime_weights:
            weight = regime_weights[style_key]
        elif type_key in regime_weights:
            weight = regime_weights[type_key]

        return weight * 100

    def _calculate_scale_score(self, scale: Decimal) -> float:
        """计算规模评分

        适中规模最好：10-100 亿为理想范围

        Args:
            scale: 基金规模（元）

        Returns:
            规模评分（0-100）
        """
        # 转换为亿元
        scale_yi = float(scale) / 100_000_000

        # 理想范围：10-100 亿
        if scale_yi < 1:
            # 规模过小，评分较低
            return 30.0
        elif scale_yi < 10:
            # 规模偏小
            return 50.0 + (scale_yi / 10) * 20
        elif 10 <= scale_yi <= 100:
            # 理想规模
            return 90.0
        elif scale_yi <= 500:
            # 规模偏大
            return 80.0 - ((scale_yi - 100) / 400) * 30
        else:
            # 规模过大
            return 50.0

    def _normalize_score(
        self,
        value: float,
        min_val: float,
        max_val: float
    ) -> float:
        """将值归一化到 0-100 范围

        Args:
            value: 原始值
            min_val: 最小值
            max_val: 最大值

        Returns:
            归一化后的值（0-100）
        """
        if max_val == min_val:
            return 50.0

        normalized = (value - min_val) / (max_val - min_val)
        return max(0.0, min(100.0, normalized * 100))


class FundStyleAnalyzer:
    """基金投资风格分析服务

    职责：
    1. 分析持仓风格（成长/价值）
    2. 分析行业配置
    3. 计算风格漂移
    """

    def analyze_holding_style(
        self,
        holdings: list[FundHolding]
    ) -> dict[str, float]:
        """分析持仓风格

        基于持仓股票的估值指标判断风格：
        - 成长：PE、PB 较高
        - 价值：PE、PB 较低
        - 平衡：介于两者之间

        Args:
            holdings: 基金持仓列表

        Returns:
            {风格: 权重} 字典，如 {'成长': 0.6, '价值': 0.3, '平衡': 0.1}
        """
        # 这里需要获取持仓股票的估值数据
        # 简化版：基于行业判断风格
        style_weights = {'成长': 0.0, '价值': 0.0, '平衡': 0.0}

        growth_sectors = {'电子', '计算机', '通信', '医药生物', '电气设备'}
        value_sectors = {'银行', '房地产', '建筑材料', '建筑装饰', '钢铁'}

        for holding in holdings:
            if not holding.holding_ratio:
                continue

            # 基于行业判断（这里简化，实际需要更复杂的逻辑）
            # 从 stock_name 提取行业信息（简化版）
            stock_name = holding.stock_name

            if any(sector in stock_name for sector in growth_sectors):
                style_weights['成长'] += holding.holding_ratio
            elif any(sector in stock_name for sector in value_sectors):
                style_weights['价值'] += holding.holding_ratio
            else:
                style_weights['平衡'] += holding.holding_ratio

        # 归一化
        total = sum(style_weights.values()) or 1
        for style in style_weights:
            style_weights[style] = style_weights[style] / total if total > 0 else 0

        return style_weights

    def analyze_sector_concentration(
        self,
        sector_alloc: list[FundSectorAllocation]
    ) -> dict[str, float]:
        """分析行业集中度

        Args:
            sector_alloc: 行业配置列表

        Returns:
            {
                'herfindahl_index': 赫芬达尔指数（0-1，越大越集中）,
                'top3_concentration': 前3大行业占比（%）
            }
        """
        if not sector_alloc:
            return {'herfindahl_index': 0.0, 'top3_concentration': 0.0}

        # 按配置比例降序排序
        sorted_alloc = sorted(sector_alloc, key=lambda x: x.allocation_ratio, reverse=True)

        # 赫芬达尔指数
        herfindahl = sum((alloc.allocation_ratio / 100) ** 2 for alloc in sorted_alloc)

        # 前3大行业占比
        top3_concentration = sum(alloc.allocation_ratio for alloc in sorted_alloc[:3])

        return {
            'herfindahl_index': herfindahl,
            'top3_concentration': top3_concentration
        }


class FundPerformanceCalculator:
    """基金业绩计算服务

    职责：
    1. 计算区间收益率
    2. 计算年化收益率
    3. 计算波动率和夏普比率
    4. 计算最大回撤
    """

    def calculate_total_return(
        self,
        nav_series: list[FundNetValue]
    ) -> float:
        """计算区间收益率

        Args:
            nav_series: 净值序列（按时间升序）

        Returns:
            区间收益率（%）
        """
        if len(nav_series) < 2:
            return 0.0

        start_nav = nav_series[0].unit_nav
        end_nav = nav_series[-1].unit_nav

        if start_nav <= 0:
            return 0.0

        total_return = (float(end_nav) / float(start_nav) - 1) * 100
        return total_return

    def calculate_annualized_return(
        self,
        total_return: float,
        days: int
    ) -> float:
        """计算年化收益率

        Args:
            total_return: 区间收益率（%）
            days: 持有天数

        Returns:
            年化收益率（%）
        """
        if days <= 0:
            return 0.0

        years = days / 365.25
        if years <= 0:
            return 0.0

        annualized = ((1 + total_return / 100) ** (1 / years) - 1) * 100
        return annualized

    def calculate_volatility(
        self,
        daily_returns: list[float]
    ) -> float:
        """计算波动率（年化）

        Args:
            daily_returns: 日收益率列表（%）

        Returns:
            年化波动率（%）
        """
        if len(daily_returns) < 2:
            return 0.0

        n = len(daily_returns)
        mean = sum(daily_returns) / n

        # 计算方差
        variance = sum((r - mean) ** 2 for r in daily_returns) / (n - 1)

        # 年化波动率（假设252个交易日）
        volatility = (variance ** 0.5) * (252 ** 0.5)
        return volatility

    def calculate_sharpe_ratio(
        self,
        annualized_return: float,
        volatility: float,
        risk_free_rate: float = 3.0
    ) -> float:
        """计算夏普比率

        Args:
            annualized_return: 年化收益率（%）
            volatility: 年化波动率（%）
            risk_free_rate: 无风险收益率（%，默认3%）

        Returns:
            夏普比率
        """
        if volatility == 0:
            return 0.0

        sharpe = (annualized_return - risk_free_rate) / volatility
        return sharpe

    def calculate_max_drawdown(
        self,
        nav_series: list[FundNetValue]
    ) -> float:
        """计算最大回撤

        Args:
            nav_series: 净值序列（按时间升序）

        Returns:
            最大回撤（%）
        """
        if len(nav_series) < 2:
            return 0.0

        max_drawdown = 0.0
        peak_nav = float(nav_series[0].unit_nav)

        for nav in nav_series:
            current_nav = float(nav.unit_nav)

            # 更新峰值
            if current_nav > peak_nav:
                peak_nav = current_nav

            # 计算回撤
            drawdown = (peak_nav - current_nav) / peak_nav * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        return max_drawdown
