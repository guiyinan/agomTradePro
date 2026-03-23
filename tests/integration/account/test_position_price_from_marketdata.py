"""
Account Module Integration Tests - 持仓价格来源于行情数据

测试新建持仓价格可追溯到行情源，不再硬编码。

验收标准：
- 新建持仓价格可追溯到行情源，不再硬编码
- 价格来源可验证
- 所有测试通过
"""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import pytest
from django.contrib.auth.models import User

from apps.account.application.use_cases import (
    CreatePositionFromSignalUseCase,
    CreatePositionInput,
    CreatePositionUseCase,
)
from apps.account.domain.entities import PositionSource
from apps.account.infrastructure.market_price_service import MarketPriceService
from apps.account.infrastructure.repositories import (
    AccountRepository,
    AssetMetadataRepository,
    PositionRepository,
)
from apps.signal.infrastructure.models import InvestmentSignalModel


@pytest.fixture
def market_price_service():
    """市场价格服务 fixture"""
    return MarketPriceService(cache_ttl_minutes=30)


@pytest.fixture
def test_user(db):
    """创建测试用户（每个测试独立）"""
    import uuid
    unique_id = str(uuid.uuid4())[:8]
    username = f"testuser_{unique_id}"

    # 使用 get_or_create 避免重复创建
    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            'password': 'testpass123',  # Note: This needs to be hashed properly
        }
    )
    if created:
        user.set_password('testpass123')
        user.save()

    # 使用 get_or_create 创建账户配置
    from apps.account.infrastructure.models import AccountProfileModel
    profile, created = AccountProfileModel.objects.get_or_create(
        user=user,
        defaults={
            'display_name': '测试用户',
            'initial_capital': Decimal("1000000.00"),
            'risk_tolerance': 'moderate',
        }
    )
    return user


@pytest.fixture
def test_signal(db, test_user):
    """创建测试投资信号"""
    signal = InvestmentSignalModel.objects.create(
        user=test_user,
        asset_code="000001.SZ",
        asset_class="equity",
        direction="LONG",
        logic_desc="测试信号",
        target_regime="Recovery",
        status="approved",
    )
    return signal


class TestMarketPriceService:
    """测试市场价格服务"""

    def test_normalize_asset_code_sz(self, market_price_service):
        """测试深圳股票代码规范化"""
        assert market_price_service._normalize_asset_code("000001") == "000001.SZ"
        assert market_price_service._normalize_asset_code("300001") == "300001.SZ"
        assert market_price_service._normalize_asset_code("000001.sz") == "000001.SZ"

    def test_normalize_asset_code_sh(self, market_price_service):
        """测试上海股票代码规范化"""
        assert market_price_service._normalize_asset_code("600001") == "600001.SH"
        assert market_price_service._normalize_asset_code("688001") == "688001.SH"
        assert market_price_service._normalize_asset_code("600001.sh") == "600001.SH"

    def test_normalize_asset_code_bj(self, market_price_service):
        """测试北京股票代码规范化"""
        assert market_price_service._normalize_asset_code("832566") == "832566.BJ"
        assert market_price_service._normalize_asset_code("430047") == "430047.BJ"

    def test_normalize_asset_code_already_formatted(self, market_price_service):
        """测试已格式化的代码保持不变"""
        assert market_price_service._normalize_asset_code("000001.SZ") == "000001.SZ"
        assert market_price_service._normalize_asset_code("600001.SH") == "600001.SH"
        assert market_price_service._normalize_asset_code("832566.BJ") == "832566.BJ"

    def test_get_current_price_with_mock_provider(self, market_price_service):
        """测试从行情接口获取价格（使用 mock）"""
        # Mock MarketDataProvider
        mock_provider = Mock()
        mock_provider.get_price.return_value = 12.50
        market_price_service._provider = mock_provider

        price = market_price_service.get_current_price("000001.SZ")

        assert price == Decimal("12.50")
        mock_provider.get_price.assert_called_once_with("000001.SZ", None)

    def test_get_current_price_failure(self, market_price_service):
        """测试获取价格失败的情况"""
        mock_provider = Mock()
        mock_provider.get_price.return_value = None
        market_price_service._provider = mock_provider

        price = market_price_service.get_current_price("999999.SZ")

        assert price is None

    def test_get_price_with_metadata(self, market_price_service):
        """测试获取价格及元数据"""
        mock_provider = Mock()
        mock_provider.get_price.return_value = 15.75
        market_price_service._provider = mock_provider

        result = market_price_service.get_price_with_metadata("000001.SZ")

        assert result is not None
        assert result["price"] == Decimal("15.75")
        assert result["asset_code"] == "000001.SZ"
        assert result["source"] == "MarketDataProvider"
        assert "timestamp" in result
        assert "trade_date" in result

    def test_get_prices_batch(self, market_price_service):
        """测试批量获取价格"""
        mock_provider = Mock()
        mock_provider.get_price.side_effect = [12.50, 25.30, 10.80]
        market_price_service._provider = mock_provider

        codes = ["000001.SZ", "600001.SH", "300001.SZ"]
        prices = market_price_service.get_prices_batch(codes)

        assert len(prices) == 3
        assert prices["000001.SZ"] == Decimal("12.50")
        assert prices["600001.SH"] == Decimal("25.30")
        assert prices["300001.SZ"] == Decimal("10.80")

    def test_clear_cache(self, market_price_service):
        """测试清空缓存"""
        mock_provider = Mock()
        market_price_service._provider = mock_provider

        market_price_service.clear_cache()

        mock_provider.clear_cache.assert_called_once()

    def test_invalid_asset_code_raises_error(self, market_price_service):
        """测试无效资产代码抛出异常"""
        with pytest.raises(ValueError, match="资产代码不能为空"):
            market_price_service.get_current_price("")


@pytest.mark.django_db(transaction=True)
class TestCreatePositionWithMarketPrice:
    """测试使用行情价格创建持仓"""

    @pytest.fixture
    def use_case(self, market_price_service):
        """创建持仓用例 fixture"""
        return CreatePositionUseCase(
            position_repo=PositionRepository(),
            account_repo=AccountRepository(),
            asset_meta_repo=AssetMetadataRepository(),
            market_price_service=market_price_service,
        )

    def test_create_position_with_market_price(self, use_case, test_user, market_price_service):
        """测试使用行情价格创建持仓"""
        # Mock 行情价格
        mock_provider = Mock()
        mock_provider.get_price.return_value = 18.50
        market_price_service._provider = mock_provider

        input_data = CreatePositionInput(
            user_id=test_user.id,
            asset_code="000001.SZ",
            shares=1000,
            price=None,  # 不指定价格，应从行情接口获取
        )

        output = use_case.execute(input_data)

        assert output.position is not None
        assert output.position.asset_code == "000001.SZ"
        assert output.position.avg_cost == Decimal("18.50")
        assert output.shares == 1000
        assert output.notional == Decimal("18500.00")

        # 验证调用了行情接口
        mock_provider.get_price.assert_called_once()

    def test_create_position_with_explicit_price(self, use_case, test_user, market_price_service):
        """测试使用显式指定价格创建持仓（不调用行情接口）"""
        mock_provider = Mock()
        market_price_service._provider = mock_provider

        input_data = CreatePositionInput(
            user_id=test_user.id,
            asset_code="000001.SZ",
            shares=1000,
            price=Decimal("20.00"),  # 显式指定价格
        )

        output = use_case.execute(input_data)

        assert output.position.avg_cost == Decimal("20.00")

        # 验证没有调用行情接口
        mock_provider.get_price.assert_not_called()

    def test_create_position_market_price_failure_raises_error(self, use_case, test_user, market_price_service):
        """测试行情接口失败时抛出异常"""
        # Mock 行情接口失败
        mock_provider = Mock()
        mock_provider.get_price.return_value = None
        market_price_service._provider = mock_provider

        input_data = CreatePositionInput(
            user_id=test_user.id,
            asset_code="999999.SZ",
            shares=1000,
            price=None,
        )

        with pytest.raises(ValueError, match="无法获取资产.*的价格"):
            use_case.execute(input_data)

    def test_create_position_auto_calculate_shares_with_market_price(self, use_case, test_user, market_price_service):
        """测试使用行情价格自动计算持仓数量"""
        mock_provider = Mock()
        mock_provider.get_price.return_value = 10.0
        market_price_service._provider = mock_provider

        input_data = CreatePositionInput(
            user_id=test_user.id,
            asset_code="000001.SZ",
            shares=None,  # 自动计算
            price=None,   # 从行情获取
        )

        output = use_case.execute(input_data)

        # 默认10%仓位，初始资金1000000，价格10
        # 期望持仓数量 = (1000000 * 0.1) / 10 = 10000
        assert output.shares > 0
        assert output.position.avg_cost == Decimal("10.0")


@pytest.mark.django_db(transaction=True)
class TestCreatePositionFromSignalWithMarketPrice:
    """测试使用行情价格从信号创建持仓"""

    @pytest.fixture
    def use_case(self, market_price_service):
        """从信号创建持仓用例 fixture"""
        return CreatePositionFromSignalUseCase(
            position_repo=PositionRepository(),
            account_repo=AccountRepository(),
            market_price_service=market_price_service,
        )

    def test_create_position_from_signal_with_market_price(
        self, use_case, test_user, test_signal, market_price_service
    ):
        """测试从信号创建持仓时使用行情价格"""
        # Mock 行情价格
        mock_provider = Mock()
        mock_provider.get_price.return_value = 15.80
        market_price_service._provider = mock_provider

        output = use_case.execute(
            user_id=test_user.id,
            signal_id=test_signal.id,
            price=None,  # 不指定价格，应从行情接口获取
        )

        assert output.position is not None
        assert output.position.asset_code == "000001.SZ"
        assert output.position.avg_cost == Decimal("15.80")
        assert output.position.source == PositionSource.SIGNAL

        # 验证调用了行情接口
        mock_provider.get_price.assert_called_once()

    def test_create_position_from_signal_market_price_failure_raises_error(
        self, use_case, test_user, test_signal, market_price_service
    ):
        """测试行情接口失败时抛出异常"""
        mock_provider = Mock()
        mock_provider.get_price.return_value = None
        market_price_service._provider = mock_provider

        with pytest.raises(ValueError, match="无法获取资产.*的价格"):
            use_case.execute(
                user_id=test_user.id,
                signal_id=test_signal.id,
                price=None,
            )


@pytest.mark.django_db(transaction=True)
class TestPriceSourceTraceability:
    """测试价格来源可追溯性"""

    def test_price_metadata_contains_source(self, market_price_service):
        """测试价格元数据包含来源信息"""
        mock_provider = Mock()
        mock_provider.get_price.return_value = 22.50
        market_price_service._provider = mock_provider

        metadata = market_price_service.get_price_with_metadata("600001.SH")

        assert metadata is not None
        assert "price" in metadata
        assert "source" in metadata
        assert "timestamp" in metadata
        assert "trade_date" in metadata

        # 验证价格可追溯到数据源
        assert metadata["source"] == "MarketDataProvider"
        assert isinstance(metadata["timestamp"], datetime)

    def test_price_service_singleton(self):
        """测试市场价格服务单例"""
        # 清除单例
        import apps.account.infrastructure.market_price_service as mps_module
        from apps.account.infrastructure.market_price_service import (
            _price_service_instance,
            get_market_price_service,
        )
        mps_module._price_service_instance = None

        service1 = get_market_price_service()
        service2 = get_market_price_service()

        assert service1 is service2  # 应该是同一个实例


@pytest.mark.django_db
class TestMarketPriceIntegration:
    """集成测试：测试完整的持仓创建流程（使用行情价格）"""

    def test_full_position_creation_workflow_with_market_price(self, test_user):
        """测试完整的持仓创建工作流（价格来源于行情）"""
        # 创建用例
        market_price_service = MarketPriceService()
        use_case = CreatePositionUseCase(
            position_repo=PositionRepository(),
            account_repo=AccountRepository(),
            asset_meta_repo=AssetMetadataRepository(),
            market_price_service=market_price_service,
        )

        # Mock 行情价格
        mock_provider = Mock()
        mock_provider.get_price.return_value = 16.88
        market_price_service._provider = mock_provider

        # 创建持仓
        input_data = CreatePositionInput(
            user_id=test_user.id,
            asset_code="000001.SZ",
            shares=500,
            price=None,  # 从行情接口获取
        )

        output = use_case.execute(input_data)

        # 验证结果
        assert output.position is not None
        assert output.position.asset_code == "000001.SZ"
        assert output.position.avg_cost == Decimal("16.88")
        assert output.position.shares == 500
        assert output.notional == Decimal("8440.00")

        # 验证持仓已保存到数据库
        from apps.account.infrastructure.models import PositionModel
        position_model = PositionModel.objects.get(id=output.position.id)
        assert position_model.avg_cost == Decimal("16.88")
        assert position_model.current_price == Decimal("16.88")

        # 验证价格来源可追溯
        # 在实际应用中，可以通过日志或审计表追踪价格来源
        # 这里我们验证没有使用硬编码的 100.0
        assert position_model.avg_cost != Decimal("100.0")
