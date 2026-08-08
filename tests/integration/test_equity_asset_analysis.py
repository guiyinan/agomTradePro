"""
Equity 模块集成测试（通用资产分析框架）

测试 Equity 模块与 asset_analysis 模块的集成。
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.asset_analysis.domain.value_objects import ScoreContext
from apps.data_center.infrastructure.models import (
    AssetMasterModel,
    FinancialFactModel,
    PriceBarModel,
    ValuationFactModel,
)
from apps.equity.application.services import EquityMultiDimScorer
from apps.equity.domain.entities import (
    EquityAssetScore,
    FinancialData,
    StockInfo,
    ValuationMetrics,
)
from apps.equity.infrastructure.repositories import DjangoEquityAssetRepository
from tests.integration.support.canonical_publications import publish_canonical_rows


@pytest.fixture
def sample_stock_data(db):
    """创建测试股票数据"""
    stock, valuations, financials, prices = _seed_canonical_stock(
        code="000001.SZ",
        name="平安银行",
        exchange="SZSE",
        list_date=date(1991, 4, 3),
        pe=8.5,
    )
    _publish_canonical_stock_facts(valuations, financials, prices)
    return stock


def _seed_canonical_stock(
    *,
    code: str,
    name: str,
    exchange: str,
    list_date: date,
    pe: float,
) -> tuple[
    AssetMasterModel,
    list[ValuationFactModel],
    list[FinancialFactModel],
    list[PriceBarModel],
]:
    """Create one canonical asset and its D4/D5/D1 facts for integration tests."""

    period_end = date.today() - timedelta(days=30)
    asset = AssetMasterModel.objects.create(
        code=code,
        name=name,
        short_name=name,
        asset_type="stock",
        exchange=exchange,
        is_active=True,
        list_date=list_date,
        sector="银行",
    )
    observed_at = datetime.now(UTC)
    valuation = ValuationFactModel.objects.create(
        asset_code=code,
        val_date=date.today(),
        pe_ttm=pe,
        pb=Decimal("0.8"),
        ps_ttm=Decimal("1.5"),
        market_cap=Decimal("200000000000"),
        float_market_cap=Decimal("150000000000"),
        dv_ratio=Decimal("5.5"),
        source="dc-test",
        available_at=observed_at,
    )
    financials: list[FinancialFactModel] = []
    for metric_code, value, unit in (
        ("revenue", Decimal("100000000000"), "元"),
        ("net_profit", Decimal("50000000000"), "元"),
        ("revenue_growth", Decimal("8.0"), "%"),
        ("net_profit_growth", Decimal("10.0"), "%"),
        ("total_assets", Decimal("1000000000000"), "元"),
        ("total_liabilities", Decimal("900000000000"), "元"),
        ("equity", Decimal("100000000000"), "元"),
        ("roe", Decimal("18.0"), "%"),
        ("roa", Decimal("1.5"), "%"),
        ("debt_ratio", Decimal("90.0"), "%"),
    ):
        financials.append(
            FinancialFactModel.objects.create(
                asset_code=code,
                period_end=period_end,
                period_type="annual",
                metric_code=metric_code,
                value=value,
                unit=unit,
                source="dc-test",
                report_date=period_end,
                available_at=observed_at,
            )
        )
    price = PriceBarModel.objects.create(
        asset_code=code,
        bar_date=date.today(),
        freq="1d",
        adjustment="none",
        open=Decimal("12.0"),
        high=Decimal("12.5"),
        low=Decimal("11.8"),
        close=Decimal("12.3"),
        volume=1000000,
        amount=Decimal("12300000"),
        source="dc-test",
    )
    return asset, [valuation], financials, [price]


def _publish_canonical_stock_facts(
    valuations: list[ValuationFactModel],
    financials: list[FinancialFactModel],
    prices: list[PriceBarModel],
) -> None:
    """Expose exact D5/D4/D1 rows through their canonical current gates."""

    publish_canonical_rows(
        dataset_key="equity.valuation.fact",
        publication_key="current",
        fact_table="data_center_valuation_fact",
        observation_field="val_date",
        rows=valuations,
    )
    publish_canonical_rows(
        dataset_key="equity.financial.fact",
        publication_key="current",
        fact_table="data_center_financial_fact",
        observation_field="available_at",
        rows=financials,
    )
    publish_canonical_rows(
        dataset_key="equity.price.bar",
        publication_key="current",
        fact_table="data_center_price_bar",
        observation_field="bar_date",
        rows=prices,
    )


@pytest.fixture
def sample_stocks_data(db):
    """创建多个测试股票"""
    stock1, valuations1, financials1, prices1 = _seed_canonical_stock(
        code="000001.SZ",
        name="平安银行",
        exchange="SZSE",
        list_date=date(1991, 4, 3),
        pe=8.5,
    )
    stock2, valuations2, financials2, prices2 = _seed_canonical_stock(
        code="600000.SH",
        name="浦发银行",
        exchange="SSE",
        list_date=date(1999, 11, 10),
        pe=9.0,
    )
    _publish_canonical_stock_facts(
        valuations1 + valuations2,
        financials1 + financials2,
        prices1 + prices2,
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
        assert stock.stock_code == "000001.SZ"
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

    @pytest.mark.parametrize(
        ("filters", "max_count"),
        (
            ({"sector": ["银行"]}, 10),
            ({"min_market_cap": Decimal("NaN")}, 10),
            ({"min_market_cap": -1}, 10),
            ({"min_market_cap": 20, "max_market_cap": 10}, 10),
            ({"min_pe": float("inf")}, 10),
            ({}, 0),
            ({}, True),
        ),
    )
    def test_get_assets_by_filter_rejects_invalid_dynamic_inputs(
        self,
        filters: dict[str, object],
        max_count: object,
    ) -> None:
        """Repository callers cannot bypass finite and bounded filter contracts."""

        with pytest.raises(ValueError):
            DjangoEquityAssetRepository().get_assets_by_filter(
                asset_type="equity",
                filters=filters,
                max_count=max_count,
            )


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
        assert result[0].total_score <= 100
        expected_score = (
            result[0].regime_score * 0.30
            + result[0].policy_score * 0.20
            + result[0].sentiment_score * 0.20
            + result[0].signal_score * 0.10
            + stock.technical_score * 0.10
            + stock.fundamental_score * 0.10
            + stock.valuation_score * 0.10
        ) / 1.10
        assert result[0].total_score == pytest.approx(expected_score)
        assert result[0].rank == 1

    def test_score_batch_rejects_duplicate_codes_and_invalid_custom_scores(self):
        """One ranking cannot contain duplicate identities or non-finite component scores."""

        class MockRepo:
            pass

        scorer = EquityMultiDimScorer(MockRepo())
        stock = EquityAssetScore(
            stock_code="000001",
            stock_name="平安银行",
            sector="银行",
            market="SZ",
            list_date=date(1991, 4, 3),
        )
        context = ScoreContext(
            current_regime="Recovery",
            policy_level="P0",
            sentiment_index=0.0,
            active_signals=[],
        )

        with pytest.raises(ValueError, match="unique stock_code"):
            scorer.score_batch([stock, stock], context)
        with pytest.raises(ValueError, match="technical_score"):
            scorer.score_batch([replace(stock, technical_score=float("nan"))], context)

    def test_screen_stocks_empty_result_has_stable_shape_and_validates_limit(self):
        """No-match screens remain a 404-ready payload instead of raising on missing count."""

        class MockRepo:
            calls = 0

            def get_assets_by_filter(self, **_kwargs):
                self.calls += 1
                return []

        repo = MockRepo()
        scorer = EquityMultiDimScorer(repo)
        context = ScoreContext(
            current_regime="Recovery",
            policy_level="P0",
            sentiment_index=0.0,
            active_signals=[],
        )

        assert scorer.screen_stocks({}, context) == {
            "success": False,
            "count": 0,
            "message": "未找到符合条件的个股",
            "stocks": [],
        }
        with pytest.raises(ValueError, match="max_count must be a positive integer"):
            scorer.screen_stocks({}, context, max_count=True)
        assert repo.calls == 1

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

        risk = EquityMultiDimScorer._calculate_risk_level(bank_stock)

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

        risk = EquityMultiDimScorer._calculate_risk_level(tech_stock)

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
