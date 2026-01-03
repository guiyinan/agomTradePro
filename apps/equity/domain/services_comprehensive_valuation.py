"""
综合估值判断服务

整合多种估值方法，提供综合的低估/高估判断
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Literal
from decimal import Decimal
from datetime import date

from apps.equity.domain.entities import FinancialData, ValuationMetrics


@dataclass
class ValuationScore:
    """估值评分"""
    method: str  # 估值方法
    score: float  # 评分（0-100）
    signal: Literal['undervalued', 'fair', 'overvalued']  # 信号
    details: Dict  # 详细信息


@dataclass
class ComprehensiveValuationResult:
    """综合估值结果"""
    stock_code: str
    overall_score: float  # 综合评分（0-100）
    overall_signal: Literal['strong_buy', 'buy', 'hold', 'sell', 'strong_sell']
    scores: List[ValuationScore]
    recommendation: str
    confidence: float  # 置信度（0-1）


class ComprehensiveValuationAnalyzer:
    """
    综合估值分析器

    整合多种估值方法：
    1. 相对估值（PE/PB 百分位）
    2. 绝对估值（DCF）
    3. 相对估值（PEG）
    4. 质量评估（ROE、增长率等）
    """

    def analyze(
        self,
        stock_code: str,
        financial: FinancialData,
        valuation: ValuationMetrics,
        historical_pe: List[float],
        historical_pb: List[float],
        industry_avg_pe: float = 20.0,
        industry_avg_pb: float = 2.0,
        risk_free_rate: float = 0.03
    ) -> ComprehensiveValuationResult:
        """
        综合估值分析

        Args:
            stock_code: �股票代码
            financial: 财务数据
            valuation: 估值指标
            historical_pe: 历史 PE 列表
            historical_pb: 历史 PB 列表
            industry_avg_pe: 行业平均 PE
            industry_avg_pb: 行业平均 PB
            risk_free_rate: 无风险利率（默认 3%）

        Returns:
            综合估值结果
        """
        from apps.equity.domain.services import ValuationAnalyzer

        scores = []
        weights = []  # 各方法权重

        # 1. PE/PB 百分位分析（权重：30%）
        pe_pb_score = self._analyze_pe_pb_percentile(
            valuation, historical_pe, historical_pb
        )
        scores.append(pe_pb_score)
        weights.append(0.3)

        # 2. 相对行业估值（权重：20%）
        industry_score = self._analyze_vs_industry(
            valuation, industry_avg_pe, industry_avg_pb
        )
        scores.append(industry_score)
        weights.append(0.2)

        # 3. PEG 估值（权重：20%）
        peg_score = self._analyze_peg(financial, valuation)
        scores.append(peg_score)
        weights.append(0.2)

        # 4. 质量评分（权重：15%）
        quality_score = self._analyze_quality(financial)
        scores.append(quality_score)
        weights.append(0.15)

        # 5. DCF 绝对估值（权重：15%）
        # dcf_score = self._analyze_dcf(financial, valuation, risk_free_rate)
        # scores.append(dcf_score)
        # weights.append(0.15)

        # 计算加权综合评分
        overall_score = sum(s.score * w for s, w in zip(scores, weights))

        # 确定信号
        overall_signal = self._determine_signal(overall_score)

        # 生成推荐
        recommendation = self._generate_recommendation(overall_signal, scores)

        # 计算置信度（基于各方法的一致性）
        confidence = self._calculate_confidence(scores)

        return ComprehensiveValuationResult(
            stock_code=stock_code,
            overall_score=overall_score,
            overall_signal=overall_signal,
            scores=scores,
            recommendation=recommendation,
            confidence=confidence
        )

    def _analyze_pe_pb_percentile(
        self,
        valuation: ValuationMetrics,
        historical_pe: List[float],
        historical_pb: List[float]
    ) -> ValuationScore:
        """PE/PB 百分位分析"""
        from apps.equity.domain.services import ValuationAnalyzer

        analyzer = ValuationAnalyzer()

        pe_percentile = analyzer.calculate_pe_percentile(valuation.pe, historical_pe)
        pb_percentile = analyzer.calculate_pb_percentile(valuation.pb, historical_pb)

        # 综合百分位（平均）
        avg_percentile = (pe_percentile + pb_percentile) / 2

        # 转换为评分（百分位越低，评分越高）
        score = (1 - avg_percentile) * 100

        # 确定信号
        if avg_percentile < 0.2:
            signal = 'undervalued'
        elif avg_percentile < 0.4:
            signal = 'fair'
        else:
            signal = 'overvalued'

        return ValuationScore(
            method='PE/PB 百分位',
            score=score,
            signal=signal,
            details={
                'pe_percentile': pe_percentile,
                'pb_percentile': pb_percentile,
                'avg_percentile': avg_percentile
            }
        )

    def _analyze_vs_industry(
        self,
        valuation: ValuationMetrics,
        industry_avg_pe: float,
        industry_avg_pb: float
    ) -> ValuationScore:
        """相对行业估值分析"""
        # 计算相对比率
        pe_ratio = valuation.pe / industry_avg_pe if industry_avg_pe > 0 else 1.0
        pb_ratio = valuation.pb / industry_avg_pb if industry_avg_pb > 0 else 1.0

        # 平均比率
        avg_ratio = (pe_ratio + pb_ratio) / 2

        # 转换为评分（比率越低，评分越高）
        if avg_ratio <= 0.7:
            score = 100
        elif avg_ratio <= 0.85:
            score = 80
        elif avg_ratio <= 1.0:
            score = 60
        elif avg_ratio <= 1.2:
            score = 40
        else:
            score = 20

        # 确定信号
        if avg_ratio < 0.8:
            signal = 'undervalued'
        elif avg_ratio < 1.2:
            signal = 'fair'
        else:
            signal = 'overvalued'

        return ValuationScore(
            method='相对行业',
            score=score,
            signal=signal,
            details={
                'pe_ratio': pe_ratio,
                'pb_ratio': pb_ratio,
                'avg_ratio': avg_ratio
            }
        )

    def _analyze_peg(
        self,
        financial: FinancialData,
        valuation: ValuationMetrics
    ) -> ValuationScore:
        """PEG 估值分析（PE/增长率）"""
        # 计算增长率（取营收增长率和净利润增长率的平均）
        growth_rate = (financial.revenue_growth + financial.net_profit_growth) / 2

        if growth_rate <= 0 or valuation.pe <= 0:
            # 负增长或无效 PE，无法使用 PEG
            return ValuationScore(
                method='PEG',
                score=50,
                signal='fair',
                details={'peg': None, 'reason': '增长率或PE无效'}
            )

        # 计算 PEG
        peg = valuation.pe / growth_rate

        # PEG 评分（PEG < 1 表示低估）
        if peg < 0.5:
            score = 100
        elif peg < 0.8:
            score = 80
        elif peg < 1.0:
            score = 60
        elif peg < 1.5:
            score = 40
        else:
            score = 20

        # 确定信号
        if peg < 0.8:
            signal = 'undervalued'
        elif peg < 1.2:
            signal = 'fair'
        else:
            signal = 'overvalued'

        return ValuationScore(
            method='PEG',
            score=score,
            signal=signal,
            details={
                'peg': peg,
                'pe': valuation.pe,
                'growth_rate': growth_rate
            }
        )

    def _analyze_quality(
        self,
        financial: FinancialData
    ) -> ValuationScore:
        """质量分析（基于财务指标）"""
        score = 50  # 基础分

        # ROE 评分（30 分）
        if financial.roe >= 20:
            score += 30
        elif financial.roe >= 15:
            score += 20
        elif financial.roe >= 10:
            score += 10

        # 营收增长评分（20 分）
        if financial.revenue_growth >= 30:
            score += 20
        elif financial.revenue_growth >= 20:
            score += 15
        elif financial.revenue_growth >= 10:
            score += 10

        # 净利润增长评分（20 分）
        if financial.net_profit_growth >= 30:
            score += 20
        elif financial.net_profit_growth >= 20:
            score += 15
        elif financial.net_profit_growth >= 10:
            score += 10

        # 资产负债率评分（扣分项）
        if financial.debt_ratio > 70:
            score -= 20
        elif financial.debt_ratio > 50:
            score -= 10

        # 限制评分范围
        score = max(0, min(100, score))

        # 确定信号
        if score >= 80:
            signal = 'undervalued'  # 质量好，隐含低估
        elif score >= 60:
            signal = 'fair'
        else:
            signal = 'overvalued'  # 质量差，隐含高估

        return ValuationScore(
            method='质量评分',
            score=score,
            signal=signal,
            details={
                'roe': financial.roe,
                'revenue_growth': financial.revenue_growth,
                'profit_growth': financial.net_profit_growth,
                'debt_ratio': financial.debt_ratio
            }
        )

    def _determine_signal(
        self,
        overall_score: float
    ) -> Literal['strong_buy', 'buy', 'hold', 'sell', 'strong_sell']:
        """根据综合评分确定信号"""
        if overall_score >= 85:
            return 'strong_buy'
        elif overall_score >= 70:
            return 'buy'
        elif overall_score >= 40:
            return 'hold'
        elif overall_score >= 25:
            return 'sell'
        else:
            return 'strong_sell'

    def _generate_recommendation(
        self,
        overall_signal: str,
        scores: List[ValuationScore]
    ) -> str:
        """生成推荐建议"""
        # 统计各信号的数量
        signal_counts = {'undervalued': 0, 'fair': 0, 'overvalued': 0}
        for s in scores:
            signal_counts[s.signal] += 1

        # 生成建议文本
        recommendations = {
            'strong_buy': f"强烈推荐买入。综合评分显示股票被显著低估，{signal_counts['undervalued']}种方法支持低估判断。",
            'buy': f"推荐买入。股票估值偏低，具有投资价值。",
            'hold': f"持有观望。估值处于合理区间，等待更好的入场时机。",
            'sell': f"建议减仓。股票估值偏高，注意风险。",
            'strong_sell': f"强烈建议卖出。股票被显著高估，{signal_counts['overvalued']}种方法支持高估判断。"
        }

        return recommendations.get(overall_signal, "暂无明确建议")

    def _calculate_confidence(
        self,
        scores: List[ValuationScore]
    ) -> float:
        """
        计算置信度（基于各方法的一致性）

        如果所有方法的信号一致，置信度高
        如果信号不一致，置信度低
        """
        # 统计各信号的数量
        signal_counts = {'undervalued': 0, 'fair': 0, 'overvalued': 0}
        for s in scores:
            signal_counts[s.signal] += 1

        # 计算最大占比
        max_count = max(signal_counts.values())
        consistency_ratio = max_count / len(scores)

        # 一致性越高，置信度越高
        confidence = 0.5 + (consistency_ratio - 0.33) * 0.5

        return max(0.0, min(1.0, confidence))
