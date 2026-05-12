"""
个股筛选服务单元测试

遵循四层架构规范：
- Domain 层测试不依赖 Django
- 使用纯 Python 测试 Domain 层业务逻辑
"""

from datetime import date
from decimal import Decimal

from apps.equity.domain.entities import FinancialData, StockInfo, ValuationMetrics
from apps.equity.domain.rules import StockScreeningRule
from apps.equity.domain.services import StockScreener


class TestStockScreener:
    """个股筛选服务单元测试"""

    def test_screen_by_roe(self):
        """测试按 ROE 筛选"""
        # 准备数据
        stocks = [
            (
                StockInfo('000001.SZ', '平安银行', '银行', 'SZ', date(2000, 1, 1)),
                FinancialData(
                    '000001.SZ',
                    date(2024, 12, 31),
                    Decimal('150000000000'),
                    Decimal('35000000000'),
                    10.0,
                    15.0,
                    Decimal('3000000000000'),
                    Decimal('2700000000000'),
                    Decimal('300000000000'),
                    18.0,
                    5.0,
                    90.0
                ),
                ValuationMetrics(
                    '000001.SZ',
                    date(2026, 1, 2),
                    8.0,
                    0.8,
                    1.2,
                    Decimal('300000000000'),
                    Decimal('240000000000'),
                    3.5
                )
            ),
            (
                StockInfo('600519.SH', '贵州茅台', '食品饮料', 'SH', date(2001, 8, 27)),
                FinancialData(
                    '600519.SH',
                    date(2024, 12, 31),
                    Decimal('120000000000'),
                    Decimal('60000000000'),
                    15.0,
                    18.0,
                    Decimal('2500000000000'),
                    Decimal('500000000000'),
                    Decimal('2000000000000'),
                    35.0,
                    8.0,
                    20.0
                ),
                ValuationMetrics(
                    '600519.SH',
                    date(2026, 1, 2),
                    30.0,
                    10.0,
                    15.0,
                    Decimal('2500000000000'),
                    Decimal('2500000000000'),
                    1.0
                )
            ),
        ]

        # 定义规则：ROE > 20%, PE < 15
        rule = StockScreeningRule(
            regime='Recovery',
            name='高ROE低估值',
            min_roe=20.0,
            max_pe=15.0,
            max_count=10
        )

        # 执行筛选
        screener = StockScreener()
        result = screener.screen(stocks, rule)

        # 验证结果：贵州茅台 ROE 35% > 20%，但 PE 30 > 15，不满足条件
        # 平安银行 ROE 18% < 20%，不满足条件
        # 因此应该返回空列表
        assert len(result) == 0

    def test_screen_with_matching_criteria(self):
        """测试筛选匹配条件"""
        # 准备数据：一只符合条件的股票
        stocks = [
            (
                StockInfo('600519.SH', '贵州茅台', '食品饮料', 'SH', date(2001, 8, 27)),
                FinancialData(
                    '600519.SH',
                    date(2024, 12, 31),
                    Decimal('120000000000'),
                    Decimal('60000000000'),
                    15.0,
                    18.0,
                    Decimal('2500000000000'),
                    Decimal('500000000000'),
                    Decimal('2000000000000'),
                    25.0,  # ROE > 20%
                    8.0,
                    20.0
                ),
                ValuationMetrics(
                    '600519.SH',
                    date(2026, 1, 2),
                    12.0,  # PE < 15
                    10.0,
                    15.0,
                    Decimal('2500000000000'),
                    Decimal('2500000000000'),
                    1.0
                )
            ),
        ]

        # 定义规则：ROE > 20%, PE < 15
        rule = StockScreeningRule(
            regime='Recovery',
            name='高ROE低估值',
            min_roe=20.0,
            max_pe=15.0,
            max_count=10
        )

        # 执行筛选
        screener = StockScreener()
        result = screener.screen(stocks, rule)

        # 验证结果
        assert len(result) == 1
        assert result[0] == '600519.SH'

    def test_screen_by_sector(self):
        """测试按行业筛选"""
        # 准备数据：不同行业的股票
        stocks = [
            (
                StockInfo('000001.SZ', '平安银行', '银行', 'SZ', date(2000, 1, 1)),
                FinancialData(
                    '000001.SZ',
                    date(2024, 12, 31),
                    Decimal('150000000000'),
                    Decimal('35000000000'),
                    10.0,
                    15.0,
                    Decimal('3000000000000'),
                    Decimal('2700000000000'),
                    Decimal('300000000000'),
                    18.0,
                    5.0,
                    90.0
                ),
                ValuationMetrics(
                    '000001.SZ',
                    date(2026, 1, 2),
                    5.0,
                    0.5,
                    0.8,
                    Decimal('300000000000'),
                    Decimal('240000000000'),
                    5.0
                )
            ),
            (
                StockInfo('600030.SH', '中信证券', '证券', 'SH', date(2003, 1, 6)),
                FinancialData(
                    '600030.SH',
                    date(2024, 12, 31),
                    Decimal('200000000000'),
                    Decimal('80000000000'),
                    15.0,
                    20.0,
                    Decimal('4000000000000'),
                    Decimal('3000000000000'),
                    Decimal('1000000000000'),
                    15.0,
                    5.0,
                    75.0
                ),
                ValuationMetrics(
                    '600030.SH',
                    date(2026, 1, 2),
                    12.0,
                    1.2,
                    2.0,
                    Decimal('500000000000'),
                    Decimal('400000000000'),
                    2.0
                )
            ),
        ]

        # 定义规则：只看证券行业
        rule = StockScreeningRule(
            regime='Recovery',
            name='证券行业',
            min_roe=10.0,
            max_pe=20.0,
            sector_preference=['证券'],
            max_count=10
        )

        # 执行筛选
        screener = StockScreener()
        result = screener.screen(stocks, rule)

        # 验证结果：只有中信证券符合
        assert len(result) == 1
        assert result[0] == '600030.SH'

    def test_score_calculation(self):
        """测试评分计算"""
        # 准备数据
        stocks = [
            (
                StockInfo('000001.SZ', '平安银行', '银行', 'SZ', date(2000, 1, 1)),
                FinancialData(
                    '000001.SZ',
                    date(2024, 12, 31),
                    Decimal('150000000000'),
                    Decimal('35000000000'),
                    20.0,  # 营收增长 20%
                    25.0,  # 利润增长 25%
                    Decimal('3000000000000'),
                    Decimal('2700000000000'),
                    Decimal('300000000000'),
                    15.0,  # ROE 15%
                    5.0,
                    90.0
                ),
                ValuationMetrics(
                    '000001.SZ',
                    date(2026, 1, 2),
                    10.0,  # PE 10
                    0.8,
                    1.2,
                    Decimal('300000000000'),
                    Decimal('240000000000'),
                    3.5
                )
            ),
        ]

        # 定义规则
        rule = StockScreeningRule(
            regime='Recovery',
            name='综合评分',
            min_roe=10.0,
            max_pe=20.0,
            max_count=10
        )

        # 执行筛选
        screener = StockScreener()
        result = screener.screen(stocks, rule)

        # 验证结果
        assert len(result) == 1
        assert result[0] == '000001.SZ'
