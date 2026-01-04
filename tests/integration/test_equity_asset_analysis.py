"""
Equity 模块集成测试（通用资产分析框架）

测试 Equity 模块与 asset_analysis 模块的集成。
"""

import pytest
from decimal import Decimal
from datetime import date, timedelta

from apps.equity.domain.entities import (
    StockInfo,
    EquityAssetScore,
    ValuationMetrics,
    FinancialData,
    TechnicalIndicators,
)
from apps.equity.infrastructure.repositories import DjangoEquityAssetRepository
from apps.equity.application.services import EquityMultiDimScorer
from apps.asset_analysis.domain.value_objects import ScoreContext
from apps.equity.infrastructure.models import (
    StockInfoModel,
    StockDailyModel,
    FinancialDataModel,
    ValuationModel,
)


@pytest.fixture
def sample_stock_data(db):
    """创建测试股票数据"""
    stock = StockInfoModel.objects.create(
        stock_code="000001",
        name="平安银行",
        sector="银行",
        market="SZ",
        list_date=date(1991, 4, 3),
        is_active=True,
    )

    # 创建估值数据
    ValuationModel.objects.create(
        stock_code="000001",
        trade_date=date.today(),
        pe=8.5,
        pb=0.8,
        ps=1.5,
        total_mv=Decimal("200000000000"),
        circ_mv=Decimal("150000000000"),
        dividend_yield=5.5,
    )

    # 创建财务数据
    FinancialDataModel.objects.create(
        stock_code="000001",
        report_date=date.today() - timedelta(days=30),
        report_type="4Q",
        revenue=Decimal("100000000000"),
        net_profit=Decimal("50000000000"),
        revenue_growth=8.0,
        net_profit_growth=10.0,
        total_assets=Decimal("1000000000000"),
        total_liabilities=Decimal("900000000000"),
        equity=Decimal("100000000000"),
        roe=18.0,
        roa=1.5,
        debt_ratio=90.0,
    )

    # 创建日线数据
    StockDailyModel.objects.create(
        stock_code="000001",
        trade_date=date.today(),
        open=Decimal("12.0"),
        high=Decimal("12.5"),
        low=Decimal("11.8"),
        close=Decimal("12.3"),
        volume=1000000,
        amount=Decimal("12300000"),
        ma5=Decimal("12.1"),
        ma20=Decimal("11.9"),
        ma60=Decimal("11.5"),
        rsi=55.0,
    )

    return stock


@pytest.fixture
def sample_stocks_data(db):
    """创建多个测试股票"""
    stock1 = StockInfoModel.objects.create(
        stock_code="000001",
        name="平安银行",
        sector="银行",
        market="SZ",
        list_date=date(1991, 4, 3),
        is_active=True,
    )

    stock2 = StockInfoModel.objects.create(
        stock_code="600000",
        name="浦发银行",
        sector="银行",
        market="SH",
        list_date=date(1999, 11, 10),
        is_active=True,
    )

    # 为每个股票创建估值和财务数据
    for stock in [stock1, stock2]:
        ValuationModel.objects.create(
            stock_code=stock.stock_code,
            trade_date=date.today(),
            pe=8.5 if stock.stock_code == "000001" else 9.0,
            pb=0.8,
            ps=1.5,
            total_mv=Decimal("200000000000"),
            circ_mv=Decimal("150000000000"),
            dividend_yield=5.5,
        )

        FinancialDataModel.objects.create(
            stock_code=stock.stock_code,
            report_date=date.today() - timedelta(days=30),
            report_type="4Q",
            revenue=Decimal("100000000000"),
            net_profit=Decimal("50000000000"),
            revenue_growth=8.0,
            net_profit_growth=10.0,
            total_assets=Decimal("1000000000000"),
            total_liabilities=Decimal("900000000000"),
            equity=Decimal("100000000000"),
            roe=18.0,
            roa=1.5,
            debt_ratio=90.0,
        )

    return [stock1, stock2]


@pytest.mark.django_db
class TestEquityAssetScore:
    """测试个股资产评分实体"""

    def test_from_stock_info_basic(self):
        """测试从 StockInfo 创建 EquityAssetScore（仅基本信息）"""
        stock_info = StockInfo(
            stock_code="000001.SZ",
            name="平安银行",
            sector="银行",
            market="SZ",
            list_date=date(1991, 4, 3),
        )

        asset_score = EquityAssetScore.from_stock_info(stock_info)

        assert asset_score.stock_code == "000001.SZ"
        assert asset_score.stock_name == "平安银行"
        assert asset_score.sector == "银行"
        assert asset_score.market == "SZ"
        # 没有估值数据，style 和 size 应该为 None
        assert asset_score.style is None
        assert asset_score.size is None

    def test_from_stock_info_with_valuation(self):
        """测试从 StockInfo 创建 EquityAssetScore（含估值数据）"""
        stock_info = StockInfo(
            stock_code="000001.SZ",
            name="平安银行",
            sector="银行",
            market="SZ",
            list_date=date(1991, 4, 3),
        )

        valuation = ValuationMetrics(
            stock_code="000001.SZ",
            trade_date=date.today(),
            pe=8.5,  # 低PE
            pb=0.8,
            ps=1.5,
            total_mv=Decimal("200000000000"),  # 2000亿 - large
            circ_mv=Decimal("150000000000"),
            dividend_yield=5.5,
        )

        financial = FinancialData(
            stock_code="000001.SZ",
            report_date=date.today() - timedelta(days=30),
            revenue=Decimal("100000000000"),
            net_profit=Decimal("50000000000"),
            revenue_growth=8.0,
            net_profit_growth=10.0,
            total_assets=Decimal("1000000000000"),
            total_liabilities=Decimal("900000000000"),
            equity=Decimal("100000000000"),
            roe=18.0,  # 高ROE
            roa=1.5,
            debt_ratio=90.0,
        )

        asset_score = EquityAssetScore.from_stock_info(
            stock_info, valuation=valuation, financial=financial
        )

        assert asset_score.stock_code == "000001.SZ"
        # PE < 15 且 ROE > 15 应该是 value
        assert asset_score.style == "value"
        # 2000亿以上应该是 large
        assert asset_score.size == "large"
        assert asset_score.pe_ratio == 8.5
        assert asset_score.pb_ratio == 0.8
        assert asset_score.roe == 18.0

    def test_get_custom_scores(self):
        """测试获取自定义得分"""
        stock_score = EquityAssetScore(
            stock_code="000001.SZ",
            stock_name="平安银行",
            sector="银行",
            market="SZ",
            list_date=date(1991, 4, 3),
            technical_score=75.0,
            fundamental_score=80.0,
            valuation_score=70.0,
        )

        custom_scores = stock_score.get_custom_scores()

        assert custom_scores["technical"] == 75.0
        assert custom_scores["fundamental"] == 80.0
        assert custom_scores["valuation"] == 70.0

    def test_to_dict(self):
        """测试转换为字典"""
        stock_score = EquityAssetScore(
            stock_code="000001.SZ",
            stock_name="平安银行",
            sector="银行",
            market="SZ",
            list_date=date(1991, 4, 3),
            pe_ratio=8.5,
            pb_ratio=0.8,
            market_cap=Decimal("200000000000"),
            roe=18.0,
            current_price=Decimal("12.50"),
            style="value",
            size="large",
            regime_score=85.0,
            policy_score=80.0,
            sentiment_score=75.0,
            signal_score=70.0,
            total_score=78.0,
            rank=1,
            allocation_percent=15.0,
            risk_level="中低风险",
        )

        d = stock_score.to_dict()

        assert d["stock_code"] == "000001.SZ"
        assert d["stock_name"] == "平安银行"
        assert d["sector"] == "银行"
        assert d["pe_ratio"] == 8.5
        assert d["market_cap"] == "2000.00亿"
        assert d["regime_score"] == 85.0
        assert d["total_score"] == 78.0
        assert d["allocation"] == "15.0%"
        assert d["risk_level"] == "中低风险"


@pytest.mark.django_db
class TestDjangoEquityAssetRepository:
    """测试个股资产仓储"""

    def test_get_assets_by_filter_empty_filters(self, sample_stock_data):
        """测试不带过滤条件的查询"""
        repo = DjangoEquityAssetRepository()

        # 不带过滤条件
        stocks = repo.get_assets_by_filter(
            asset_type="equity",
            filters={},
            max_count=10,
        )

        # 返回列表
        assert isinstance(stocks, list)
        assert all(isinstance(s, EquityAssetScore) for s in stocks)
        assert len(stocks) >= 1

    def test_get_assets_by_filter_with_sector(self, sample_stock_data):
        """测试按行业过滤"""
        repo = DjangoEquityAssetRepository()

        stocks = repo.get_assets_by_filter(
            asset_type="equity",
            filters={"sector": "银行"},
            max_count=10,
        )

        assert isinstance(stocks, list)
        for stock in stocks:
            assert stock.sector == "银行"

    def test_get_asset_by_code_found(self, sample_stock_data):
        """测试查询存在的股票"""
        repo = DjangoEquityAssetRepository()

        stock = repo.get_asset_by_code("equity", "000001")

        assert stock is not None
        assert stock.stock_code == "000001"
        assert stock.stock_name == "平安银行"
        assert stock.pe_ratio == 8.5
        assert stock.roe == 18.0

    def test_get_asset_by_code_not_found(self):
        """测试查询不存在的股票"""
        repo = DjangoEquityAssetRepository()

        stock = repo.get_asset_by_code("equity", "999999")

        assert stock is None

    def test_get_assets_by_filter_wrong_type(self, sample_stock_data):
        """测试错误的资产类型"""
        repo = DjangoEquityAssetRepository()

        stocks = repo.get_assets_by_filter(
            asset_type="bond",  # 错误类型
            filters={},
            max_count=10,
        )

        assert stocks == []


@pytest.mark.django_db
class TestEquityMultiDimScorer:
    """测试个股多维度评分服务"""

    def test_score_batch_empty(self):
        """测试空列表评分"""
        # Mock repo
        class MockRepo:
            pass

        scorer = EquityMultiDimScorer(MockRepo())

        context = ScoreContext(
            current_regime="Recovery",
            policy_level="P0",
            sentiment_index=0.0,
            active_signals=[],
        )

        result = scorer.score_batch([], context)

        assert result == []

    def test_score_single_stock(self):
        """测试单个股票评分"""
        class MockRepo:
            pass

        scorer = EquityMultiDimScorer(MockRepo())

        stock = EquityAssetScore(
            stock_code="000001",
            stock_name="平安银行",
            sector="银行",
            market="SZ",
            list_date=date(1991, 4, 3),
            market_cap=Decimal("200000000000"),
            style="value",
            size="large",
            technical_score=70.0,
            fundamental_score=75.0,
            valuation_score=80.0,
        )

        context = ScoreContext(
            current_regime="Recovery",
            policy_level="P0",
            sentiment_index=0.5,
            active_signals=[],
        )

        result = scorer.score_batch([stock], context)

        assert len(result) == 1
        assert result[0].regime_score > 0  # Recovery + 股票应该得分
        assert result[0].total_score > 0
        assert result[0].rank == 1

    def test_calculate_risk_level(self):
        """测试风险等级计算"""
        # 银行股
        bank_stock = EquityAssetScore(
            stock_code="000001",
            stock_name="平安银行",
            sector="银行",
            market="SZ",
            list_date=date(1991, 4, 3),
            size="large",
        )

        scorer = EquityMultiDimScorer(None)
        risk = scorer._calculate_risk_level(bank_stock)

        assert risk == "中低风险"  # 银行大盘股

        # 小盘科技股
        tech_stock = EquityAssetScore(
            stock_code="300001",
            stock_name="特锐德",
            sector="电子",
            market="SZ",
            list_date=date(2009, 10, 30),
            size="small",
        )

        risk = scorer._calculate_risk_level(tech_stock)

        # 电子行业基准是"中高风险"，小盘保持不变
        assert risk == "中高风险"


@pytest.mark.django_db
class TestEquityIntegration:
    """个股模块集成测试"""

    def test_full_screening_flow(self, sample_stocks_data):
        """
        测试完整的筛选流程

        模拟从获取股票到评分的完整流程。
        """
        # 1. 创建评分上下文
        context = ScoreContext(
            current_regime="Recovery",
            policy_level="P0",
            sentiment_index=0.5,
            active_signals=[],
        )

        # 2. 获取股票
        repo = DjangoEquityAssetRepository()
        stocks = repo.get_assets_by_filter(
            asset_type="equity",
            filters={"sector": "银行"},
            max_count=30,
        )

        # 3. 评分
        scorer = EquityMultiDimScorer(repo)
        scored_stocks = scorer.score_batch(stocks, context)

        # 4. 验证结果
        assert len(scored_stocks) >= 2
        assert scored_stocks[0].rank == 1
        assert scored_stocks[0].total_score >= scored_stocks[1].total_score

        # 验证推荐比例
        assert scored_stocks[0].allocation_percent > 0

        # 验证风险等级
        for stock in scored_stocks:
            assert stock.risk_level in ["低风险", "中低风险", "中风险", "中高风险", "高风险"]
