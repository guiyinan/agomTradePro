"""
个股筛选评分逻辑单元测试

测试分位数归一化法的正确性
"""

import pytest
from datetime import date
from decimal import Decimal

from apps.equity.domain.services import StockScreener
from apps.equity.domain.entities import StockInfo, FinancialData, ValuationMetrics
from apps.equity.domain.rules import StockScreeningRule


class TestPercentileCalculation:
    """测试分位数计算"""

    def test_percentile_with_valid_reference(self):
        """测试正常参考列表的分位数计算"""
        screener = StockScreener()

        # 测试值在列表中间
        reference = [10, 20, 30, 40, 50]
        assert screener._percentile(30, reference) == 0.4  # 2/5 = 0.4
        assert screener._percentile(40, reference) == 0.6  # 3/5 = 0.6

        # 测试最小值
        assert screener._percentile(10, reference) == 0.0

        # 测试最大值
        assert screener._percentile(50, reference) == 0.8  # 4/5 = 0.8

    def test_percentile_with_empty_reference(self):
        """测试空参考列表"""
        screener = StockScreener()
        assert screener._percentile(30, []) == 0.5

    def test_percentile_with_negative_value(self):
        """测试负值的处理"""
        screener = StockScreener()
        reference = [10, 20, 30]
        assert screener._percentile(-5, reference) == 0.5

    def test_percentile_with_duplicates(self):
        """测试重复值的情况"""
        screener = StockScreener()
        reference = [10, 10, 20, 20, 30, 30]
        # 值为20时，小于20的有2个（两个10），所以分位数是 2/6 ≈ 0.333
        assert screener._percentile(20, reference) == pytest.approx(0.333, rel=0.01)


class TestScoreCalculation:
    """测试评分计算"""

    def create_test_stocks(self) -> list:
        """创建测试用股票数据"""
        base_date = date(2024, 1, 1)

        # 高质量股票：高增长、高ROE、低PE
        high_quality = (
            StockInfo(
                stock_code="000001.SZ",
                name="优质股",
                sector="银行",
                market="SZ",
                list_date=base_date
            ),
            FinancialData(
                stock_code="000001.SZ",
                report_date=base_date,
                revenue=Decimal("1000000000"),
                net_profit=Decimal("100000000"),
                revenue_growth=30.0,
                net_profit_growth=25.0,
                total_assets=Decimal("5000000000"),
                total_liabilities=Decimal("2000000000"),
                equity=Decimal("3000000000"),
                roe=20.0,
                roa=2.0,
                debt_ratio=40.0
            ),
            ValuationMetrics(
                stock_code="000001.SZ",
                trade_date=base_date,
                pe=10.0,
                pb=1.5,
                ps=2.0,
                total_mv=Decimal("10000000000"),
                circ_mv=Decimal("8000000000"),
                dividend_yield=3.0
            )
        )

        # 低质量股票：低增长、低ROE、高PE
        low_quality = (
            StockInfo(
                stock_code="000002.SZ",
                name="劣质股",
                sector="银行",
                market="SZ",
                list_date=base_date
            ),
            FinancialData(
                stock_code="000002.SZ",
                report_date=base_date,
                revenue=Decimal("1000000000"),
                net_profit=Decimal("50000000"),
                revenue_growth=5.0,
                net_profit_growth=3.0,
                total_assets=Decimal("5000000000"),
                total_liabilities=Decimal("2000000000"),
                equity=Decimal("3000000000"),
                roe=5.0,
                roa=1.0,
                debt_ratio=40.0
            ),
            ValuationMetrics(
                stock_code="000002.SZ",
                trade_date=base_date,
                pe=50.0,
                pb=3.0,
                ps=5.0,
                total_mv=Decimal("10000000000"),
                circ_mv=Decimal("8000000000"),
                dividend_yield=1.0
            )
        )

        # 中等质量股票：中等增长、中等ROE、中等PE
        medium_quality = (
            StockInfo(
                stock_code="000003.SZ",
                name="中等股",
                sector="银行",
                market="SZ",
                list_date=base_date
            ),
            FinancialData(
                stock_code="000003.SZ",
                report_date=base_date,
                revenue=Decimal("1000000000"),
                net_profit=Decimal("75000000"),
                revenue_growth=15.0,
                net_profit_growth=12.0,
                total_assets=Decimal("5000000000"),
                total_liabilities=Decimal("2000000000"),
                equity=Decimal("3000000000"),
                roe=12.0,
                roa=1.5,
                debt_ratio=40.0
            ),
            ValuationMetrics(
                stock_code="000003.SZ",
                trade_date=base_date,
                pe=25.0,
                pb=2.0,
                ps=3.0,
                total_mv=Decimal("10000000000"),
                circ_mv=Decimal("8000000000"),
                dividend_yield=2.0
            )
        )

        # 负增长股票（应被过滤）
        negative_growth = (
            StockInfo(
                stock_code="000004.SZ",
                name="负增长股",
                sector="银行",
                market="SZ",
                list_date=base_date
            ),
            FinancialData(
                stock_code="000004.SZ",
                report_date=base_date,
                revenue=Decimal("1000000000"),
                net_profit=Decimal("50000000"),
                revenue_growth=-5.0,
                net_profit_growth=-3.0,
                total_assets=Decimal("5000000000"),
                total_liabilities=Decimal("2000000000"),
                equity=Decimal("3000000000"),
                roe=5.0,
                roa=1.0,
                debt_ratio=40.0
            ),
            ValuationMetrics(
                stock_code="000004.SZ",
                trade_date=base_date,
                pe=20.0,
                pb=2.0,
                ps=3.0,
                total_mv=Decimal("10000000000"),
                circ_mv=Decimal("8000000000"),
                dividend_yield=2.0
            )
        )

        return [high_quality, medium_quality, low_quality, negative_growth]

    def test_high_quality_stock_gets_high_score(self):
        """测试高质量股票获得高分"""
        screener = StockScreener()
        test_stocks = self.create_test_stocks()

        # 收集市场指标
        market_metrics = screener._collect_market_metrics(test_stocks)

        # 创建一个宽松的规则，让所有股票都通过
        rule = StockScreeningRule(
            regime="Recovery",
            name="测试规则",
            min_roe=0.0,
            min_revenue_growth=0.0,
            min_profit_growth=0.0,
            max_debt_ratio=100.0,
            max_pe=999.0,
            max_pb=999.0,
            min_market_cap=Decimal("0"),
            sector_preference=None,
            max_count=10
        )

        # 计算各股票得分（不包括负增长的，因为它会被过滤）
        high_quality_stock = test_stocks[0]
        medium_quality_stock = test_stocks[1]
        low_quality_stock = test_stocks[2]

        high_score = screener._calculate_score(
            high_quality_stock[1], high_quality_stock[2], rule, market_metrics
        )
        medium_score = screener._calculate_score(
            medium_quality_stock[1], medium_quality_stock[2], rule, market_metrics
        )
        low_score = screener._calculate_score(
            low_quality_stock[1], low_quality_stock[2], rule, market_metrics
        )

        # 验证：高质量股票得分 > 中等质量 > 低质量
        assert high_score > medium_score > low_score

        # 验证：分数在合理范围内 [0, 1]
        assert 0 <= high_score <= 1
        assert 0 <= medium_score <= 1
        assert 0 <= low_score <= 1

    def test_screen_filters_and_ranks_correctly(self):
        """测试筛选功能正确过滤和排序"""
        screener = StockScreener()
        test_stocks = self.create_test_stocks()

        rule = StockScreeningRule(
            regime="Recovery",
            name="测试规则",
            min_roe=8.0,  # 过滤掉 ROE < 8% 的股票
            min_revenue_growth=10.0,  # 过滤掉营收增长 < 10% 的股票
            min_profit_growth=10.0,  # 过滤掉净利润增长 < 10% 的股票
            max_debt_ratio=100.0,
            max_pe=999.0,
            max_pb=999.0,
            min_market_cap=Decimal("0"),
            sector_preference=None,
            max_count=10
        )

        # 执行筛选
        result = screener.screen(test_stocks, rule)

        # 验证：只有高增长、高ROE的股票通过
        # 000001.SZ (高质量) 应该通过
        # 000003.SZ (中等质量) 应该通过
        # 000002.SZ (低质量) 会被过滤（增长不达标）
        # 000004.SZ (负增长) 会被过滤（负增长）
        assert "000001.SZ" in result
        assert "000003.SZ" in result
        assert "000002.SZ" not in result
        assert "000004.SZ" not in result

    def test_score_with_extreme_pe_values(self):
        """测试极端PE值的处理"""
        screener = StockScreener()

        base_date = date(2024, 1, 1)

        # 极低PE股票
        low_pe_stock = (
            StockInfo(
                stock_code="000001.SZ",
                name="低PE股",
                sector="银行",
                market="SZ",
                list_date=base_date
            ),
            FinancialData(
                stock_code="000001.SZ",
                report_date=base_date,
                revenue=Decimal("1000000000"),
                net_profit=Decimal("100000000"),
                revenue_growth=10.0,
                net_profit_growth=10.0,
                total_assets=Decimal("5000000000"),
                total_liabilities=Decimal("2000000000"),
                equity=Decimal("3000000000"),
                roe=10.0,
                roa=2.0,
                debt_ratio=40.0
            ),
            ValuationMetrics(
                stock_code="000001.SZ",
                trade_date=base_date,
                pe=5.0,  # 极低PE
                pb=1.0,
                ps=1.0,
                total_mv=Decimal("10000000000"),
                circ_mv=Decimal("8000000000"),
                dividend_yield=5.0
            )
        )

        # 极高PE股票
        high_pe_stock = (
            StockInfo(
                stock_code="000002.SZ",
                name="高PE股",
                sector="科技",
                market="SZ",
                list_date=base_date
            ),
            FinancialData(
                stock_code="000002.SZ",
                report_date=base_date,
                revenue=Decimal("1000000000"),
                net_profit=Decimal("100000000"),
                revenue_growth=10.0,
                net_profit_growth=10.0,
                total_assets=Decimal("5000000000"),
                total_liabilities=Decimal("2000000000"),
                equity=Decimal("3000000000"),
                roe=10.0,
                roa=2.0,
                debt_ratio=40.0
            ),
            ValuationMetrics(
                stock_code="000002.SZ",
                trade_date=base_date,
                pe=100.0,  # 极高PE
                pb=10.0,
                ps=10.0,
                total_mv=Decimal("10000000000"),
                circ_mv=Decimal("8000000000"),
                dividend_yield=0.5
            )
        )

        test_stocks = [low_pe_stock, high_pe_stock]
        market_metrics = screener._collect_market_metrics(test_stocks)

        rule = StockScreeningRule(
            regime="Recovery",
            name="测试规则",
            min_roe=0.0,
            min_revenue_growth=0.0,
            min_profit_growth=0.0,
            max_debt_ratio=100.0,
            max_pe=999.0,
            max_pb=999.0,
            min_market_cap=Decimal("0"),
            sector_preference=None,
            max_count=10
        )

        low_pe_score = screener._calculate_score(
            low_pe_stock[1], low_pe_stock[2], rule, market_metrics
        )
        high_pe_score = screener._calculate_score(
            high_pe_stock[1], high_pe_stock[2], rule, market_metrics
        )

        # 低PE股票的估值得分应该更高
        # 由于其他财务指标相同，低PE股票的总分应该更高
        assert low_pe_score > high_pe_score

    def test_score_dimensional_consistency(self):
        """测试评分的量纲一致性"""
        screener = StockScreener()

        base_date = date(2024, 1, 1)

        # 创建一个股票，ROE=20%（百分比），PE=10
        # 在旧公式中：20 * 0.4 + 100/10 * 0.2 = 8 + 2 = 10
        # 这里有量纲问题：百分比(%) + 1/PE
        stock = (
            StockInfo(
                stock_code="000001.SZ",
                name="测试股",
                sector="银行",
                market="SZ",
                list_date=base_date
            ),
            FinancialData(
                stock_code="000001.SZ",
                report_date=base_date,
                revenue=Decimal("1000000000"),
                net_profit=Decimal("100000000"),
                revenue_growth=20.0,
                net_profit_growth=20.0,
                total_assets=Decimal("5000000000"),
                total_liabilities=Decimal("2000000000"),
                equity=Decimal("3000000000"),
                roe=20.0,
                roa=2.0,
                debt_ratio=40.0
            ),
            ValuationMetrics(
                stock_code="000001.SZ",
                trade_date=base_date,
                pe=10.0,
                pb=1.5,
                ps=2.0,
                total_mv=Decimal("10000000000"),
                circ_mv=Decimal("8000000000"),
                dividend_yield=3.0
            )
        )

        test_stocks = [stock]
        market_metrics = screener._collect_market_metrics(test_stocks)

        rule = StockScreeningRule(
            regime="Recovery",
            name="测试规则",
            min_roe=0.0,
            min_revenue_growth=0.0,
            min_profit_growth=0.0,
            max_debt_ratio=100.0,
            max_pe=999.0,
            max_pb=999.0,
            min_market_cap=Decimal("0"),
            sector_preference=None,
            max_count=10
        )

        score = screener._calculate_score(
            stock[1], stock[2], rule, market_metrics
        )

        # 验证：新公式的分数应该在 [0, 1] 范围内
        assert 0 <= score <= 1

        # 当只有一只股票时，其分位数应该是 0.5（自己和自己比）
        # 但因为我们排除了负值，且只有正值数据，分位数计算需要特殊处理
        # 在单只股票情况下，各维度分位数都是0（没有小于它的值）
        # 所以总分会接近 0 * 0.4 + 0 * 0.4 + 1 * 0.2 = 0.2
        # 实际上 percentile(v, [v]) = 0，valuation = 1 - 0 = 1
        # 总分 = 0*0.4 + 0*0.4 + 1*0.2 = 0.2
        assert score == pytest.approx(0.2, abs=0.01)

    def test_collect_market_metrics_filters_invalid_values(self):
        """测试市场指标收集正确过滤无效值"""
        screener = StockScreener()

        base_date = date(2024, 1, 1)

        # 创建包含无效值的股票数据
        stocks = [
            # 有效股票
            (
                StockInfo(
                    stock_code=f"00000{i}.SZ",
                    name=f"股票{i}",
                    sector="银行",
                    market="SZ",
                    list_date=base_date
                ),
                FinancialData(
                    stock_code=f"00000{i}.SZ",
                    report_date=base_date,
                    revenue=Decimal("1000000000"),
                    net_profit=Decimal("100000000"),
                    revenue_growth=10.0 + i,
                    net_profit_growth=10.0 + i,
                    total_assets=Decimal("5000000000"),
                    total_liabilities=Decimal("2000000000"),
                    equity=Decimal("3000000000"),
                    roe=10.0 + i,
                    roa=2.0,
                    debt_ratio=40.0
                ),
                ValuationMetrics(
                    stock_code=f"00000{i}.SZ",
                    trade_date=base_date,
                    pe=10.0 + i,
                    pb=2.0,
                    ps=3.0,
                    total_mv=Decimal("10000000000"),
                    circ_mv=Decimal("8000000000"),
                    dividend_yield=2.0
                )
            )
            for i in range(1, 4)
        ]

        # 添加包含无效值的股票
        stocks.append((
            StockInfo(
                stock_code="000005.SZ",
                name="无效值股票",
                sector="银行",
                market="SZ",
                list_date=base_date
            ),
            FinancialData(
                stock_code="000005.SZ",
                report_date=base_date,
                revenue=Decimal("1000000000"),
                net_profit=Decimal("100000000"),
                revenue_growth=-5.0,  # 负增长，应被过滤
                net_profit_growth=-3.0,  # 负增长，应被过滤
                total_assets=Decimal("5000000000"),
                total_liabilities=Decimal("2000000000"),
                equity=Decimal("3000000000"),
                roe=-2.0,  # 负ROE，应被过滤
                roa=2.0,
                debt_ratio=40.0
            ),
            ValuationMetrics(
                stock_code="000005.SZ",
                trade_date=base_date,
                pe=-1.0,  # 负PE，应被过滤
                pb=2.0,
                ps=3.0,
                total_mv=Decimal("10000000000"),
                circ_mv=Decimal("8000000000"),
                dividend_yield=2.0
            )
        ))

        market_metrics = screener._collect_market_metrics(stocks)

        # 验证：负值被正确过滤
        assert all(v >= 0 for v in market_metrics['revenue_growth'])
        assert all(v >= 0 for v in market_metrics['profit_growth'])
        assert all(v >= 0 for v in market_metrics['roe'])
        assert all(v > 0 for v in market_metrics['pe'])

        # 验证：只有有效值被收集（前3个股票有正值，第4个是负值被过滤）
        assert len(market_metrics['revenue_growth']) == 3  # 负增长被过滤
        assert len(market_metrics['profit_growth']) == 3  # 负增长被过滤
        assert len(market_metrics['roe']) == 3  # 负ROE被过滤
        assert len(market_metrics['pe']) == 3  # 负PE被过滤


class TestMarketMetricsCollection:
    """测试市场指标收集"""

    def test_empty_stock_list(self):
        """测试空股票列表"""
        screener = StockScreener()
        metrics = screener._collect_market_metrics([])

        assert metrics == {
            'revenue_growth': [],
            'profit_growth': [],
            'roe': [],
            'pe': []
        }

    def test_sector_preference_filtering(self):
        """测试行业偏好过滤"""
        base_date = date(2024, 1, 1)

        stocks = [
            (
                StockInfo(
                    stock_code="000001.SZ",
                    name="银行股",
                    sector="银行",
                    market="SZ",
                    list_date=base_date
                ),
                FinancialData(
                    stock_code="000001.SZ",
                    report_date=base_date,
                    revenue=Decimal("1000000000"),
                    net_profit=Decimal("100000000"),
                    revenue_growth=15.0,
                    net_profit_growth=15.0,
                    total_assets=Decimal("5000000000"),
                    total_liabilities=Decimal("2000000000"),
                    equity=Decimal("3000000000"),
                    roe=15.0,
                    roa=2.0,
                    debt_ratio=40.0
                ),
                ValuationMetrics(
                    stock_code="000001.SZ",
                    trade_date=base_date,
                    pe=10.0,
                    pb=1.5,
                    ps=2.0,
                    total_mv=Decimal("10000000000"),
                    circ_mv=Decimal("8000000000"),
                    dividend_yield=3.0
                )
            ),
            (
                StockInfo(
                    stock_code="000002.SZ",
                    name="科技股",
                    sector="科技",
                    market="SZ",
                    list_date=base_date
                ),
                FinancialData(
                    stock_code="000002.SZ",
                    report_date=base_date,
                    revenue=Decimal("1000000000"),
                    net_profit=Decimal("100000000"),
                    revenue_growth=25.0,
                    net_profit_growth=25.0,
                    total_assets=Decimal("5000000000"),
                    total_liabilities=Decimal("2000000000"),
                    equity=Decimal("3000000000"),
                    roe=20.0,
                    roa=2.0,
                    debt_ratio=30.0
                ),
                ValuationMetrics(
                    stock_code="000002.SZ",
                    trade_date=base_date,
                    pe=30.0,
                    pb=3.0,
                    ps=5.0,
                    total_mv=Decimal("10000000000"),
                    circ_mv=Decimal("8000000000"),
                    dividend_yield=1.0
                )
            )
        ]

        screener = StockScreener()

        # 规则：只选择银行股
        rule = StockScreeningRule(
            regime="Recovery",
            name="测试规则",
            min_roe=0.0,
            min_revenue_growth=0.0,
            min_profit_growth=0.0,
            max_debt_ratio=100.0,
            max_pe=999.0,
            max_pb=999.0,
            min_market_cap=Decimal("0"),
            sector_preference=["银行"],  # 只选择银行
            max_count=10
        )

        result = screener.screen(stocks, rule)

        # 只有银行股应该被选中
        assert len(result) == 1
        assert "000001.SZ" in result
        assert "000002.SZ" not in result
