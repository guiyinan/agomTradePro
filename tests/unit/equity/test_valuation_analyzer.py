"""
估值分析服务单元测试

测试 Phase 4 功能：
1. PE/PB 百分位分析
2. DCF 绝对估值
3. Regime 相关性分析
"""

import pytest
from decimal import Decimal
from datetime import date

from apps.equity.domain.services import (
    ValuationAnalyzer,
    RegimeCorrelationAnalyzer
)


class TestValuationAnalyzer:
    """估值分析服务单元测试"""

    def test_calculate_pe_percentile_with_valid_data(self):
        """测试计算 PE 百分位（有效数据）"""
        analyzer = ValuationAnalyzer()

        current_pe = 15.0
        historical_pe = [10.0, 12.0, 15.0, 18.0, 20.0]

        percentile = analyzer.calculate_pe_percentile(current_pe, historical_pe)

        # 15.0 在 5 个值中排第 3（从 0 开始），所以百分位是 2/5 = 0.4
        assert percentile == 0.4

    def test_calculate_pe_percentile_at_lowest(self):
        """测试计算 PE 百分位（最低值）"""
        analyzer = ValuationAnalyzer()

        current_pe = 10.0
        historical_pe = [10.0, 12.0, 15.0, 18.0, 20.0]

        percentile = analyzer.calculate_pe_percentile(current_pe, historical_pe)

        # 最低值，百分位是 0
        assert percentile == 0.0

    def test_calculate_pe_percentile_at_highest(self):
        """测试计算 PE 百分位（最高值）"""
        analyzer = ValuationAnalyzer()

        current_pe = 20.0
        historical_pe = [10.0, 12.0, 15.0, 18.0, 20.0]

        percentile = analyzer.calculate_pe_percentile(current_pe, historical_pe)

        # 最高值，百分位是 4/5 = 0.8（没有比它大的）
        assert percentile == 0.8

    def test_calculate_pe_percentile_with_invalid_data(self):
        """测试计算 PE 百分位（无效数据）"""
        analyzer = ValuationAnalyzer()

        # 空列表
        percentile = analyzer.calculate_pe_percentile(15.0, [])
        assert percentile == 0.5

        # 负数当前值
        percentile = analyzer.calculate_pe_percentile(-5.0, [10.0, 12.0, 15.0])
        assert percentile == 0.5

    def test_calculate_pb_percentile(self):
        """测试计算 PB 百分位"""
        analyzer = ValuationAnalyzer()

        current_pb = 1.5
        historical_pb = [1.0, 1.2, 1.5, 1.8, 2.0]

        percentile = analyzer.calculate_pb_percentile(current_pb, historical_pb)

        assert percentile == 0.4

    def test_is_undervalued(self):
        """测试判断是否低估"""
        analyzer = ValuationAnalyzer()

        # 低估（PE 和 PB 都低于 30% 分位）
        assert analyzer.is_undervalued(0.25, 0.28, threshold=0.3) is True

        # 高估（PE 高于阈值）
        assert analyzer.is_undervalued(0.5, 0.28, threshold=0.3) is False

        # 高估（PB 高于阈值）
        assert analyzer.is_undervalued(0.25, 0.5, threshold=0.3) is False

    def test_calculate_dcf_value(self):
        """测试 DCF 估值计算"""
        analyzer = ValuationAnalyzer()

        # 假设自由现金流为 1000 万
        latest_fcf = Decimal(10_000_000)

        # 使用默认参数
        intrinsic_value = analyzer.calculate_dcf_value(
            latest_fcf=latest_fcf,
            growth_rate=0.1,
            discount_rate=0.1,
            terminal_growth=0.03,
            projection_years=5
        )

        # 内在价值应该大于自由现金流
        assert intrinsic_value > latest_fcf

        # 检查计算结果是否合理（大约在 5000 万到 2.5 亿之间）
        assert Decimal(50_000_000) < intrinsic_value < Decimal(250_000_000)

    def test_calculate_dcf_value_with_different_parameters(self):
        """测试不同参数下的 DCF 估值"""
        analyzer = ValuationAnalyzer()

        latest_fcf = Decimal(10_000_000)

        # 高增长率
        value_high_growth = analyzer.calculate_dcf_value(
            latest_fcf=latest_fcf,
            growth_rate=0.2,
            discount_rate=0.1,
            terminal_growth=0.03,
            projection_years=5
        )

        # 低增长率
        value_low_growth = analyzer.calculate_dcf_value(
            latest_fcf=latest_fcf,
            growth_rate=0.05,
            discount_rate=0.1,
            terminal_growth=0.03,
            projection_years=5
        )

        # 高增长率应该产生更高的估值
        assert value_high_growth > value_low_growth


class TestRegimeCorrelationAnalyzer:
    """Regime 相关性分析服务单元测试"""

    def test_calculate_regime_correlation(self):
        """测试计算 Regime 相关性"""
        analyzer = RegimeCorrelationAnalyzer()

        # 模拟股票收益率
        stock_returns = {
            date(2024, 1, 2): 0.01,
            date(2024, 1, 3): 0.02,
            date(2024, 1, 4): -0.01,
            date(2024, 1, 5): 0.015,
        }

        # 模拟 Regime 历史
        regime_history = {
            date(2024, 1, 2): 'Recovery',
            date(2024, 1, 3): 'Recovery',
            date(2024, 1, 4): 'Stagflation',
            date(2024, 1, 5): 'Recovery',
        }

        result = analyzer.calculate_regime_correlation(stock_returns, regime_history)

        # 验证结果
        assert 'Recovery' in result
        assert 'Stagflation' in result
        assert 'Overheat' in result
        assert 'Deflation' in result

        # Recovery 下的平均收益应该是 (0.01 + 0.02 + 0.015) / 3 = 0.015
        assert abs(result['Recovery'] - 0.015) < 0.001

        # Stagflation 下的平均收益应该是 -0.01
        assert abs(result['Stagflation'] - (-0.01)) < 0.001

        # Overheat 和 Deflation 没有数据，应该是 0
        assert result['Overheat'] == 0.0
        assert result['Deflation'] == 0.0

    def test_calculate_regime_beta(self):
        """测试计算 Regime Beta"""
        analyzer = RegimeCorrelationAnalyzer()

        # 模拟股票收益率
        stock_returns = {
            date(2024, 1, 2): 0.02,
            date(2024, 1, 3): 0.03,
            date(2024, 1, 4): -0.01,
            date(2024, 1, 5): 0.025,
        }

        # 模拟市场收益率
        market_returns = {
            date(2024, 1, 2): 0.01,
            date(2024, 1, 3): 0.015,
            date(2024, 1, 4): -0.005,
            date(2024, 1, 5): 0.012,
        }

        # 模拟 Regime 历史
        regime_history = {
            date(2024, 1, 2): 'Recovery',
            date(2024, 1, 3): 'Recovery',
            date(2024, 1, 4): 'Stagflation',
            date(2024, 1, 5): 'Recovery',
        }

        result = analyzer.calculate_regime_beta(
            stock_returns,
            market_returns,
            regime_history
        )

        # 验证结果
        assert 'Recovery' in result
        assert 'Stagflation' in result
        assert 'Overheat' in result
        assert 'Deflation' in result

        # Recovery 下应该有 3 个样本，Beta 应该大于 1（股票波动大于市场）
        assert result['Recovery'] > 1.0

        # Stagflation 下只有 1 个样本，应该返回默认值 1.0
        assert result['Stagflation'] == 1.0

    def test_calculate_beta_with_identical_returns(self):
        """测试计算 Beta（收益率相同）"""
        analyzer = RegimeCorrelationAnalyzer()

        # 股票和市场收益率完全相同
        stock_returns = [0.01, 0.02, 0.015, 0.018]
        market_returns = [0.01, 0.02, 0.015, 0.018]

        beta = analyzer._calculate_beta(stock_returns, market_returns)

        # Beta 应该接近 1.0
        assert abs(beta - 1.0) < 0.01

    def test_calculate_beta_with_high_correlation(self):
        """测试计算 Beta（高相关性）"""
        analyzer = RegimeCorrelationAnalyzer()

        # 股票收益率是市场的 2 倍
        stock_returns = [0.02, 0.04, 0.03, 0.036]
        market_returns = [0.01, 0.02, 0.015, 0.018]

        beta = analyzer._calculate_beta(stock_returns, market_returns)

        # Beta 应该接近 2.0
        assert abs(beta - 2.0) < 0.1
