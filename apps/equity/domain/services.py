"""
个股分析模块 Domain 层业务服务

遵循四层架构规范：
- Domain 层禁止导入 django.*、pandas、numpy、requests
- 只使用 Python 标准库和 dataclasses
- 所有金融逻辑必须在此层
"""

from typing import List, Dict, Tuple, Optional
from decimal import Decimal
from datetime import date

from .entities import StockInfo, FinancialData, ValuationMetrics
from .rules import StockScreeningRule


class StockScreener:
    """个股筛选服务（纯 Domain 层逻辑）"""

    def screen(
        self,
        all_stocks: List[Tuple[StockInfo, FinancialData, ValuationMetrics]],
        rule: StockScreeningRule
    ) -> List[str]:
        """
        根据规则筛选个股

        Args:
            all_stocks: 全市场股票数据，每个元素为 (StockInfo, FinancialData, ValuationMetrics)
            rule: 筛选规则

        Returns:
            符合条件的股票代码列表（按评分排序，前 max_count 个）
        """
        matched_stocks = []

        for stock_info, financial, valuation in all_stocks:
            if self._matches_rule(stock_info, financial, valuation, rule):
                score = self._calculate_score(financial, valuation, rule)
                matched_stocks.append((stock_info.stock_code, score))

        # 按评分排序
        matched_stocks.sort(key=lambda x: x[1], reverse=True)

        # 返回前 max_count 个
        return [code for code, score in matched_stocks[:rule.max_count]]

    def _matches_rule(
        self,
        stock_info: StockInfo,
        financial: FinancialData,
        valuation: ValuationMetrics,
        rule: StockScreeningRule
    ) -> bool:
        """判断是否符合规则"""
        # 1. 行业偏好
        if rule.sector_preference and stock_info.sector not in rule.sector_preference:
            return False

        # 2. 财务指标
        if financial.roe < rule.min_roe:
            return False
        if financial.revenue_growth < rule.min_revenue_growth:
            return False
        if financial.net_profit_growth < rule.min_profit_growth:
            return False
        if financial.debt_ratio > rule.max_debt_ratio:
            return False

        # 3. 估值指标
        if rule.max_pe > 0 and (valuation.pe > rule.max_pe or valuation.pe < 0):
            return False
        if rule.max_pb > 0 and (valuation.pb > rule.max_pb or valuation.pb < 0):
            return False
        if valuation.total_mv < rule.min_market_cap:
            return False

        return True

    def _calculate_score(
        self,
        financial: FinancialData,
        valuation: ValuationMetrics,
        rule: StockScreeningRule
    ) -> float:
        """
        计算综合评分

        评分规则：
        - 成长性评分（40%）：营收增长率 + 净利润增长率
        - 盈利能力评分（40%）：ROE
        - 估值评分（20%）：PE 越低越好
        """
        # 成长性评分（40%）
        growth_score = (
            financial.revenue_growth * 0.5 +
            financial.net_profit_growth * 0.5
        )

        # 盈利能力评分（40%）
        profitability_score = financial.roe

        # 估值评分（20%）- PE 越低越好
        if valuation.pe > 0:
            valuation_score = 100 / valuation.pe
        else:
            valuation_score = 0

        # 综合评分
        total_score = (
            growth_score * 0.4 +
            profitability_score * 0.4 +
            valuation_score * 0.2
        )

        return total_score


class ValuationAnalyzer:
    """估值分析服务（纯 Domain 层逻辑）"""

    def calculate_pe_percentile(
        self,
        current_pe: float,
        historical_pe: List[float]
    ) -> float:
        """
        计算 PE 在历史中的分位数

        Args:
            current_pe: 当前 PE
            historical_pe: 历史 PE 列表

        Returns:
            分位数（0.0-1.0），0.5 表示中位数
        """
        if not historical_pe or current_pe <= 0:
            return 0.5  # 无效数据返回中位数

        # 过滤无效值
        valid_pe = [pe for pe in historical_pe if pe > 0]
        if not valid_pe:
            return 0.5

        # 计算分位数
        lower_count = sum(1 for pe in valid_pe if pe < current_pe)
        percentile = lower_count / len(valid_pe)

        return percentile

    def calculate_pb_percentile(
        self,
        current_pb: float,
        historical_pb: List[float]
    ) -> float:
        """
        计算 PB 在历史中的分位数

        Args:
            current_pb: 当前 PB
            historical_pb: 历史 PB 列表

        Returns:
            分位数（0.0-1.0）
        """
        if not historical_pb or current_pb <= 0:
            return 0.5

        # 过滤无效值
        valid_pb = [pb for pb in historical_pb if pb > 0]
        if not valid_pb:
            return 0.5

        # 计算分位数
        lower_count = sum(1 for pb in valid_pb if pb < current_pb)
        percentile = lower_count / len(valid_pb)

        return percentile

    def is_undervalued(
        self,
        pe_percentile: float,
        pb_percentile: float,
        threshold: float = 0.3
    ) -> bool:
        """
        判断是否低估

        Args:
            pe_percentile: PE 分位数
            pb_percentile: PB 分位数
            threshold: 低估阈值（默认 0.3，表示历史 30% 分位以下）

        Returns:
            True 表示低估
        """
        return pe_percentile < threshold and pb_percentile < threshold

    def calculate_dcf_value(
        self,
        latest_fcf: Decimal,
        growth_rate: float = 0.1,
        discount_rate: float = 0.1,
        terminal_growth: float = 0.03,
        projection_years: int = 5
    ) -> Decimal:
        """
        DCF 绝对估值（简化版）

        Args:
            latest_fcf: 最近一年自由现金流（单位：元）
            growth_rate: 未来增长率（默认 10%）
            discount_rate: 折现率（默认 10%）
            terminal_growth: 永续增长率（默认 3%）
            projection_years: 预测年数（默认 5 年）

        Returns:
            企业总价值（单位：元）
        """
        # 1. 预测未来现金流
        projected_fcf = [
            latest_fcf * (Decimal(1 + growth_rate) ** i)
            for i in range(1, projection_years + 1)
        ]

        # 2. 折现现值
        pv = Decimal(0)
        for i, cf in enumerate(projected_fcf, 1):
            pv += cf / (Decimal(1 + discount_rate) ** i)

        # 3. 终值（永续增长模型）
        terminal_fcf = projected_fcf[-1] * Decimal(1 + terminal_growth)
        terminal_value = terminal_fcf / Decimal(discount_rate - terminal_growth)
        pv_terminal = terminal_value / (Decimal(1 + discount_rate) ** projection_years)

        # 4. 总价值
        total_value = pv + pv_terminal

        return total_value


class RegimeCorrelationAnalyzer:
    """Regime 相关性分析服务"""

    def calculate_regime_correlation(
        self,
        stock_returns: Dict[date, float],
        regime_history: Dict[date, str]
    ) -> Dict[str, float]:
        """
        计算个股在不同 Regime 下的平均收益

        Args:
            stock_returns: {日期: 收益率}
            regime_history: {日期: Regime 名称}

        Returns:
            {Regime: 平均收益率}
        """
        # 初始化各 Regime 的收益率列表
        regime_returns = {
            'Recovery': [],
            'Overheat': [],
            'Stagflation': [],
            'Deflation': []
        }

        # 按 Regime 分组收益率
        for trade_date, return_rate in stock_returns.items():
            regime = regime_history.get(trade_date)
            if regime and regime in regime_returns:
                regime_returns[regime].append(return_rate)

        # 计算平均值
        avg_returns = {}
        for regime, returns in regime_returns.items():
            if returns:
                avg_returns[regime] = sum(returns) / len(returns)
            else:
                avg_returns[regime] = 0.0

        return avg_returns

    def calculate_regime_beta(
        self,
        stock_returns: Dict[date, float],
        market_returns: Dict[date, float],
        regime_history: Dict[date, str]
    ) -> Dict[str, float]:
        """
        计算个股在不同 Regime 下的 Beta（相对于市场）

        Args:
            stock_returns: {日期: 个股收益率}
            market_returns: {日期: 市场收益率}
            regime_history: {日期: Regime 名称}

        Returns:
            {Regime: Beta}
        """
        # 按 Regime 分组数据
        regime_data = {
            'Recovery': {'stock': [], 'market': []},
            'Overheat': {'stock': [], 'market': []},
            'Stagflation': {'stock': [], 'market': []},
            'Deflation': {'stock': [], 'market': []}
        }

        for trade_date in stock_returns:
            if trade_date in market_returns and trade_date in regime_history:
                regime = regime_history[trade_date]
                if regime in regime_data:
                    regime_data[regime]['stock'].append(stock_returns[trade_date])
                    regime_data[regime]['market'].append(market_returns[trade_date])

        # 计算各 Regime 下的 Beta
        regime_betas = {}
        for regime, data in regime_data.items():
            if len(data['stock']) > 1 and len(data['market']) > 1:
                beta = self._calculate_beta(data['stock'], data['market'])
                regime_betas[regime] = beta
            else:
                regime_betas[regime] = 1.0  # 默认 Beta

        return regime_betas

    def _calculate_beta(
        self,
        stock_returns: List[float],
        market_returns: List[float]
    ) -> float:
        """
        计算 Beta（协方差 / 市场方差）

        Args:
            stock_returns: 个股收益率列表
            market_returns: 市场收益率列表

        Returns:
            Beta 值
        """
        if len(stock_returns) != len(market_returns) or len(stock_returns) < 2:
            return 1.0

        n = len(stock_returns)

        # 计算平均值
        avg_stock = sum(stock_returns) / n
        avg_market = sum(market_returns) / n

        # 计算协方差
        covariance = sum(
            (stock_returns[i] - avg_stock) * (market_returns[i] - avg_market)
            for i in range(n)
        ) / n

        # 计算市场方差
        variance = sum(
            (market_returns[i] - avg_market) ** 2
            for i in range(n)
        ) / n

        if variance == 0:
            return 1.0

        return covariance / variance
