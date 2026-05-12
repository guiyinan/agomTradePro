"""
Fund 模块集成测试（通用资产分析框架）

测试 Fund 模块与 asset_analysis 模块的集成。
"""

from datetime import date
from decimal import Decimal

from apps.asset_analysis.domain.value_objects import ScoreContext
from apps.fund.application.services import FundMultiDimScorer
from apps.fund.domain.entities import FundAssetScore, FundInfo
from apps.fund.infrastructure.repositories import DjangoFundAssetRepository


class TestFundAssetScore:
    """测试基金资产评分实体"""

    def test_from_fund_info(self):
        """测试从 FundInfo 创建 FundAssetScore"""
        fund_info = FundInfo(
            fund_code="000001",
            fund_name="测试基金",
            fund_type="股票型",
            investment_style="成长",
            setup_date=date(2020, 1, 1),
            management_company="测试公司",
            fund_scale=Decimal("5000000000"),  # 50亿
        )

        asset_score = FundAssetScore.from_fund_info(fund_info)

        assert asset_score.fund_code == "000001"
        assert asset_score.fund_name == "测试基金"
        assert asset_score.style == "growth"  # 应该自动映射
        # 50亿 < 100亿，所以是 small
        assert asset_score.size == "small"

    def test_get_custom_scores(self):
        """测试获取自定义得分"""
        fund_score = FundAssetScore(
            fund_code="000001",
            fund_name="测试基金",
            fund_type="股票型",
            manager_score=80.0,
            fund_flow_score=70.0,
            fund_size_score=75.0,
            performance_score=85.0,
        )

        custom_scores = fund_score.get_custom_scores()

        assert custom_scores["manager"] == 80.0
        assert custom_scores["flow"] == 70.0
        assert custom_scores["size"] == 75.0
        assert custom_scores["performance"] == 85.0

    def test_to_dict(self):
        """测试转换为字典"""
        fund_score = FundAssetScore(
            fund_code="000001",
            fund_name="测试基金",
            fund_type="股票型",
            investment_style="成长",
            regime_score=85.0,
            policy_score=80.0,
            sentiment_score=75.0,
            signal_score=70.0,
            total_score=78.0,
            rank=1,
            allocation_percent=20.0,
            risk_level="高风险",
        )

        d = fund_score.to_dict()

        assert d["fund_code"] == "000001"
        assert d["fund_type"] == "股票型"
        assert d["regime_score"] == 85.0
        assert d["total_score"] == 78.0
        assert d["allocation"] == "20.0%"
        assert d["risk_level"] == "高风险"


class TestDjangoFundAssetRepository:
    """测试基金资产仓储"""

    def test_get_assets_by_filter_empty_filters(self, db):
        """测试不带过滤条件的查询"""
        repo = DjangoFundAssetRepository()

        # 不带过滤条件
        funds = repo.get_assets_by_filter(
            asset_type="fund",
            filters={},
            max_count=10,
        )

        # 返回空列表（因为没有数据）
        assert isinstance(funds, list)
        assert all(isinstance(f, FundAssetScore) for f in funds)

    def test_get_assets_by_filter_with_type(self, db):
        """测试按基金类型过滤"""
        repo = DjangoFundAssetRepository()

        funds = repo.get_assets_by_filter(
            asset_type="fund",
            filters={"fund_type": "股票型"},
            max_count=10,
        )

        assert isinstance(funds, list)

    def test_get_asset_by_code_not_found(self, db):
        """测试查询不存在的基金"""
        repo = DjangoFundAssetRepository()

        fund = repo.get_asset_by_code("fund", "999999")

        assert fund is None

    def test_get_assets_by_filter_wrong_type(self, db):
        """测试错误的资产类型"""
        repo = DjangoFundAssetRepository()

        funds = repo.get_assets_by_filter(
            asset_type="equity",  # 错误类型
            filters={},
            max_count=10,
        )

        assert funds == []


class TestFundMultiDimScorer:
    """测试基金多维度评分服务"""

    def test_score_batch_empty(self):
        """测试空列表评分"""
        # Mock repo
        class MockRepo:
            pass

        scorer = FundMultiDimScorer(MockRepo())

        context = ScoreContext(
            current_regime="Recovery",
            policy_level="P0",
            sentiment_index=0.0,
            active_signals=[],
        )

        result = scorer.score_batch([], context)

        assert result == []

    def test_score_single_fund(self):
        """测试单个基金评分"""
        class MockRepo:
            pass

        scorer = FundMultiDimScorer(MockRepo())

        fund = FundAssetScore(
            fund_code="000001",
            fund_name="测试成长基金",
            fund_type="股票型",
            investment_style="成长",
            fund_scale=Decimal("5000000000"),
        )

        context = ScoreContext(
            current_regime="Recovery",
            policy_level="P0",
            sentiment_index=0.5,
            active_signals=[],
        )

        result = scorer.score_batch([fund], context)

        assert len(result) == 1
        assert result[0].regime_score > 0  # Recovery + 股票型应该得分
        assert result[0].total_score > 0
        assert result[0].rank == 1

    def test_calculate_risk_level(self):
        """测试风险等级计算"""
        # 股票型基金
        equity_fund = FundAssetScore(
            fund_code="000001",
            fund_name="股票型基金",
            fund_type="股票型",
        )

        scorer = FundMultiDimScorer(None)
        risk = scorer._calculate_risk_level(equity_fund)

        assert risk == "高风险"

        # 债券型基金
        bond_fund = FundAssetScore(
            fund_code="000002",
            fund_name="债券型基金",
            fund_type="债券型",
        )

        risk = scorer._calculate_risk_level(bond_fund)

        assert risk == "中低风险"


class TestFundIntegration:
    """基金模块集成测试"""

    def test_full_screening_flow(self):
        """
        测试完整的筛选流程

        模拟从获取基金到评分的完整流程。
        """
        # 1. 创建模拟基金数据
        funds = [
            FundAssetScore(
                fund_code="000001",
                fund_name="成长精选",
                fund_type="股票型",
                investment_style="成长",
                fund_scale=Decimal("5000000000"),  # 50亿
            ),
            FundAssetScore(
                fund_code="000002",
                fund_name="价值优选",
                fund_type="股票型",
                investment_style="价值",
                fund_scale=Decimal("8000000000"),  # 80亿
            ),
        ]

        # 2. 创建评分上下文
        context = ScoreContext(
            current_regime="Recovery",
            policy_level="P0",
            sentiment_index=0.5,
            active_signals=[],
        )

        # 3. 评分
        class MockRepo:
            pass

        scorer = FundMultiDimScorer(MockRepo())
        scored_funds = scorer.score_batch(funds, context)

        # 4. 验证结果
        assert len(scored_funds) == 2
        assert scored_funds[0].rank == 1
        assert scored_funds[1].rank == 2
        assert scored_funds[0].total_score >= scored_funds[1].total_score

        # 验证推荐比例
        assert scored_funds[0].allocation_percent > 0
        assert scored_funds[1].allocation_percent > 0

        # 验证风险等级
        for fund in scored_funds:
            assert fund.risk_level in ["低风险", "中低风险", "中风险", "中高风险", "高风险"]
