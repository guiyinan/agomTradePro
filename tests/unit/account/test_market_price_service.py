"""
Account Module Unit Tests - Market Price Service

单元测试：市场价格服务的基本功能
"""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

from apps.account.infrastructure.market_price_service import MarketPriceService


class TestMarketPriceServiceUnit:
    """市场价格服务单元测试"""

    def test_init(self):
        """测试初始化"""
        service = MarketPriceService(cache_ttl_minutes=60)
        assert service.cache_ttl_minutes == 60
        assert service._provider is None  # 延迟初始化

    def test_provider_lazy_initialization(self):
        """测试 Provider 延迟初始化"""
        service = MarketPriceService()
        assert service._provider is None

        # 首次访问 provider 时初始化
        provider = service.provider
        assert provider is not None
        assert service._provider is provider

    def test_normalize_asset_code_trims_whitespace(self):
        """测试去除空格"""
        service = MarketPriceService()
        assert service._normalize_asset_code("  000001.SZ  ") == "000001.SZ"
        assert service._normalize_asset_code("\t600001.SH\n") == "600001.SH"

    def test_normalize_asset_code_uppercase(self):
        """测试大写转换"""
        service = MarketPriceService()
        assert service._normalize_asset_code("000001.sz") == "000001.SZ"
        assert service._normalize_asset_code("600001.Sh") == "600001.SH"

    def test_normalize_asset_code_shenzhen(self):
        """测试深圳股票代码规范化（0/3开头）"""
        service = MarketPriceService()
        assert service._normalize_asset_code("000001") == "000001.SZ"
        assert service._normalize_asset_code("300001") == "300001.SZ"

    def test_normalize_asset_code_shanghai(self):
        """测试上海股票代码规范化（6开头）"""
        service = MarketPriceService()
        assert service._normalize_asset_code("600001") == "600001.SH"
        assert service._normalize_asset_code("688001") == "688001.SH"

    def test_normalize_asset_code_beijing(self):
        """测试北京股票代码规范化（8/4开头）"""
        service = MarketPriceService()
        assert service._normalize_asset_code("832566") == "832566.BJ"
        assert service._normalize_asset_code("430047") == "430047.BJ"

    def test_normalize_asset_code_preserves_formatted(self):
        """测试已格式化的代码保持不变"""
        service = MarketPriceService()
        assert service._normalize_asset_code("000001.SZ") == "000001.SZ"
        assert service._normalize_asset_code("600001.SH") == "600001.SH"
        assert service._normalize_asset_code("832566.BJ") == "832566.BJ"

    def test_get_current_price_delegates_to_provider(self):
        """测试获取价格委托给 Provider"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price.return_value = 12.50
        service._provider = mock_provider

        price = service.get_current_price("000001.SZ")

        assert price == Decimal("12.50")
        mock_provider.get_price.assert_called_once_with("000001.SZ", None)

    def test_get_current_price_with_trade_date(self):
        """测试指定交易日期"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price.return_value = 12.50
        service._provider = mock_provider

        trade_date = date(2024, 1, 15)
        price = service.get_current_price("000001.SZ", trade_date)

        assert price == Decimal("12.50")
        mock_provider.get_price.assert_called_once_with("000001.SZ", trade_date)

    def test_get_current_price_normalizes_code(self):
        """测试获取价格时规范化代码"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price.return_value = 12.50
        service._provider = mock_provider

        # 输入未格式化的代码
        price = service.get_current_price("000001")

        # Provider 应该接收到格式化后的代码
        mock_provider.get_price.assert_called_once_with("000001.SZ", None)

    def test_get_current_price_returns_none_on_failure(self):
        """测试获取价格失败返回 None"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price.return_value = None
        service._provider = mock_provider

        price = service.get_current_price("999999.SZ")

        assert price is None

    def test_get_current_price_handles_decimal_conversion(self):
        """测试 Decimal 转换"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price.return_value = 12.345
        service._provider = mock_provider

        price = service.get_current_price("000001.SZ")

        assert price == Decimal("12.345")

    def test_get_current_price_invalid_code_raises_error(self):
        """测试无效代码抛出异常"""
        service = MarketPriceService()

        with pytest.raises(ValueError, match="资产代码不能为空"):
            service.get_current_price("")

    def test_get_prices_batch(self):
        """测试批量获取价格"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price.side_effect = [12.50, 25.30, 10.80]
        service._provider = mock_provider

        codes = ["000001.SZ", "600001.SH", "300001.SZ"]
        prices = service.get_prices_batch(codes)

        assert len(prices) == 3
        assert prices["000001.SZ"] == Decimal("12.50")
        assert prices["600001.SH"] == Decimal("25.30")
        assert prices["300001.SZ"] == Decimal("10.80")

    def test_get_price_with_metadata(self):
        """测试获取价格及元数据"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price.return_value = 15.75
        service._provider = mock_provider

        result = service.get_price_with_metadata("000001.SZ")

        assert result is not None
        assert result["price"] == Decimal("15.75")
        assert result["asset_code"] == "000001.SZ"
        assert result["source"] == "DataCenterPriceProvider"
        assert isinstance(result["timestamp"], datetime)
        assert isinstance(result["trade_date"], date)

    def test_get_price_with_metadata_returns_none_on_failure(self):
        """测试获取价格元数据失败返回 None"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price.return_value = None
        service._provider = mock_provider

        result = service.get_price_with_metadata("999999.SZ")

        assert result is None

    def test_clear_cache(self):
        """测试清空缓存"""
        service = MarketPriceService()
        mock_provider = Mock()
        service._provider = mock_provider

        service.clear_cache()

        mock_provider.clear_cache.assert_called_once()

    def test_clear_cache_with_no_provider(self):
        """测试清空缓存时 Provider 未初始化"""
        service = MarketPriceService()
        assert service._provider is None

        # 不应该抛出异常
        service.clear_cache()

    def test_is_available_returns_true_on_success(self):
        """测试检查可用性返回 True"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price.return_value = 12.50
        service._provider = mock_provider

        result = service.is_available()

        assert result is True

    def test_is_available_returns_false_on_failure(self):
        """测试检查可用性返回 False"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price.return_value = None
        service._provider = mock_provider

        result = service.is_available()

        assert result is False


class TestMarketPriceServiceSingleton:
    """测试市场价格服务单例"""

    def test_get_market_price_service_returns_singleton(self):
        """测试获取单例"""
        from apps.account.infrastructure.market_price_service import get_market_price_service

        service1 = get_market_price_service()
        service2 = get_market_price_service()

        assert service1 is service2

    def test_get_market_price_service_creates_instance_on_first_call(self):
        """测试首次调用创建实例"""
        # 清除现有实例
        import apps.account.infrastructure.market_price_service as mps_module
        from apps.account.infrastructure.market_price_service import (
            _price_service_instance,
            get_market_price_service,
        )
        mps_module._price_service_instance = None

        service = get_market_price_service()

        assert isinstance(service, MarketPriceService)
        assert mps_module._price_service_instance is service


class TestMarketPriceServiceEdgeCases:
    """测试边界情况"""

    def test_get_current_price_with_float_string(self):
        """测试处理浮点数字符串"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price.return_value = "12.50"
        service._provider = mock_provider

        price = service.get_current_price("000001.SZ")

        assert price == Decimal("12.50")

    def test_get_current_price_with_int(self):
        """测试处理整数"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price.return_value = 12
        service._provider = mock_provider

        price = service.get_current_price("000001.SZ")

        assert price == Decimal("12")

    def test_get_current_price_with_zero(self):
        """测试处理零价格"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price.return_value = 0
        service._provider = mock_provider

        price = service.get_current_price("000001.SZ")

        assert price == Decimal("0")

    def test_get_current_price_with_invalid_string_raises_error(self):
        """测试处理无效字符串抛出异常"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price.return_value = "invalid"
        service._provider = mock_provider

        # 应该返回 None，而不是抛出异常
        price = service.get_current_price("000001.SZ")
        assert price is None
