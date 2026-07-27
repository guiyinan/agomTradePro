"""
Account Module Unit Tests - Market Price Service

单元测试：市场价格服务的基本功能
"""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

from apps.account.application.market_price_contracts import (
    MarketPriceResult,
    PriceFreshness,
)
from apps.account.infrastructure.market_price_service import MarketPriceService


def _price_result(
    price: float,
    *,
    asset_code: str = "000001.SZ",
    as_of: date | None = None,
    source: str = "test_quote",
    freshness: PriceFreshness = "realtime",
    is_fallback: bool = False,
) -> MarketPriceResult:
    """Build a valid canonical provider result for service tests."""

    return MarketPriceResult(
        normalized_code=asset_code,
        price=price,
        as_of=as_of,
        source=source,
        freshness=freshness,
        is_fallback=is_fallback,
    )


@pytest.mark.parametrize("invalid_price", [True, 0, -1, float("nan"), float("inf")])
def test_market_price_result_rejects_nonpositive_or_nonfinite_price(invalid_price):
    """Account price contract rejects values unsafe for position sizing."""

    with pytest.raises(ValueError, match="正有限数"):
        MarketPriceResult(
            normalized_code="000001.SZ",
            price=invalid_price,
            as_of=None,
            source="test_quote",
            freshness="realtime",
        )


@pytest.mark.parametrize("invalid_source", ["", "source\nforged", "x" * 129])
def test_market_price_result_rejects_unauditable_source(invalid_source):
    """Provider source must remain bounded and safe for audit logs."""

    with pytest.raises(ValueError, match="数据来源"):
        MarketPriceResult(
            normalized_code="000001.SZ",
            price=12.5,
            as_of=None,
            source=invalid_source,
            freshness="realtime",
        )


class TestMarketPriceServiceUnit:
    """市场价格服务单元测试"""

    def test_init(self):
        """测试初始化"""
        service = MarketPriceService(cache_ttl_minutes=60)
        assert service.cache_ttl_minutes == 60
        assert service._provider is None  # 延迟初始化

    @pytest.mark.parametrize("invalid_ttl", [True, 0, -1, 1.5, "30"])
    def test_init_rejects_invalid_cache_ttl(self, invalid_ttl):
        """缓存 TTL 必须是非布尔正整数。"""

        with pytest.raises(ValueError, match="正整数"):
            MarketPriceService(cache_ttl_minutes=invalid_ttl)

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
        assert service._normalize_asset_code("920001") == "920001.BJ"

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
        mock_provider.get_price_result.return_value = _price_result(12.50)
        service._provider = mock_provider

        price = service.get_current_price("000001.SZ")

        assert price == Decimal("12.50")
        mock_provider.get_price_result.assert_called_once_with("000001.SZ", None)

    def test_get_current_price_with_trade_date(self):
        """测试指定交易日期"""
        service = MarketPriceService()
        mock_provider = Mock()
        trade_date = date(2024, 1, 15)
        mock_provider.get_price_result.return_value = _price_result(
            12.50,
            as_of=trade_date,
            freshness="historical",
        )
        service._provider = mock_provider

        price = service.get_current_price("000001.SZ", trade_date)

        assert price == Decimal("12.50")
        mock_provider.get_price_result.assert_called_once_with("000001.SZ", trade_date)

    def test_get_current_price_normalizes_code(self):
        """测试获取价格时规范化代码"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price_result.return_value = _price_result(12.50)
        service._provider = mock_provider

        # 输入未格式化的代码
        service.get_current_price("000001")

        # Provider 应该接收到格式化后的代码
        mock_provider.get_price_result.assert_called_once_with("000001.SZ", None)

    def test_get_current_price_returns_none_on_failure(self):
        """测试获取价格失败返回 None"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price_result.return_value = None
        service._provider = mock_provider

        price = service.get_current_price("999999.SZ")

        assert price is None

    def test_get_current_price_handles_decimal_conversion(self):
        """测试 Decimal 转换"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price_result.return_value = _price_result(12.345)
        service._provider = mock_provider

        price = service.get_current_price("000001.SZ")

        assert price == Decimal("12.345")

    def test_get_current_price_invalid_code_raises_error(self):
        """测试无效代码抛出异常"""
        service = MarketPriceService()

        with pytest.raises(ValueError, match="资产代码不能为空"):
            service.get_current_price("")

    @pytest.mark.parametrize(
        "asset_code",
        ["abc", "000001.BAD", "000001.SZ.extra", "00001.SZ", "1234567"],
    )
    def test_get_current_price_rejects_malformed_code_before_provider(self, asset_code):
        """畸形代码不得触发行情查询。"""

        service = MarketPriceService()
        mock_provider = Mock()
        service._provider = mock_provider

        with pytest.raises(ValueError, match="格式无效"):
            service.get_current_price(asset_code)

        mock_provider.get_price_result.assert_not_called()

    def test_get_prices_batch(self):
        """测试批量获取价格"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price_result.side_effect = [
            _price_result(12.50),
            _price_result(25.30, asset_code="600001.SH"),
            _price_result(10.80, asset_code="300001.SZ"),
        ]
        service._provider = mock_provider

        codes = ["000001.SZ", "600001.SH", "300001.SZ"]
        prices = service.get_prices_batch(codes)

        assert len(prices) == 3
        assert prices["000001.SZ"] == Decimal("12.50")
        assert prices["600001.SH"] == Decimal("25.30")
        assert prices["300001.SZ"] == Decimal("10.80")

    def test_get_prices_batch_deduplicates_normalized_codes(self):
        """等价代码只查询一次，同时保留请求键。"""

        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price_result.return_value = _price_result(12.50)
        service._provider = mock_provider

        prices = service.get_prices_batch(["000001", " 000001.sz ", "000001"])

        assert prices == {
            "000001": Decimal("12.50"),
            " 000001.sz ": Decimal("12.50"),
        }
        mock_provider.get_price_result.assert_called_once_with("000001.SZ", None)

    def test_get_prices_batch_validates_full_scope_before_lookup(self):
        """A malformed batch member prevents all provider I/O."""

        service = MarketPriceService()
        mock_provider = Mock()
        service._provider = mock_provider

        with pytest.raises(ValueError, match="格式无效"):
            service.get_prices_batch(["000001.SZ", "not-a-code"])

        mock_provider.get_price_result.assert_not_called()

    def test_get_current_price_rejects_provider_scope_mismatch(self):
        """A provider cannot return a result for another requested asset."""

        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price_result.return_value = _price_result(
            12.5,
            asset_code="600001.SH",
        )
        service._provider = mock_provider

        assert service.get_current_price("000001.SZ") is None

    def test_get_current_price_sanitizes_provider_exception(self, caplog):
        """Provider exception details do not enter logs."""

        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price_result.side_effect = RuntimeError("token=secret-value")
        service._provider = mock_provider

        assert service.get_current_price("000001.SZ") is None
        assert "RuntimeError" in caplog.text
        assert "secret-value" not in caplog.text

    def test_get_price_with_metadata(self):
        """测试获取价格及元数据"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price_result.return_value = _price_result(
            15.75,
            as_of=date(2024, 1, 12),
            source="stored_close",
            freshness="close_fallback",
            is_fallback=True,
        )
        service._provider = mock_provider

        result = service.get_price_with_metadata("000001.SZ")

        assert result is not None
        assert result["price"] == Decimal("15.75")
        assert result["asset_code"] == "000001.SZ"
        assert result["source"] == "stored_close"
        assert isinstance(result["timestamp"], datetime)
        assert result["trade_date"] == date(2024, 1, 12)
        assert result["requested_trade_date"] is None
        assert result["freshness"] == "close_fallback"
        assert result["is_fallback"] is True

    def test_get_price_with_metadata_returns_none_on_failure(self):
        """测试获取价格元数据失败返回 None"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price_result.return_value = None
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
        service._provider = mock_provider

        result = service.is_available()

        assert result is True

    def test_is_available_returns_false_on_failure(self):
        """测试检查可用性返回 False"""
        service = MarketPriceService()
        service._provider = None

        with patch(
            "apps.account.infrastructure.market_price_service.build_market_price_provider",
            side_effect=RuntimeError("provider secret"),
        ):
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
            get_market_price_service,
        )

        mps_module._price_service_instance = None

        service = get_market_price_service()

        assert isinstance(service, MarketPriceService)
        assert mps_module._price_service_instance is service


class TestMarketPriceServiceEdgeCases:
    """测试边界情况"""

    def test_get_current_price_with_float(self):
        """测试处理浮点价格"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price_result.return_value = _price_result(12.50)
        service._provider = mock_provider

        price = service.get_current_price("000001.SZ")

        assert price == Decimal("12.50")

    def test_get_current_price_with_int(self):
        """测试处理整数"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price_result.return_value = _price_result(12.0)
        service._provider = mock_provider

        price = service.get_current_price("000001.SZ")

        assert price == Decimal("12")

    def test_get_current_price_rejects_noncanonical_result(self):
        """Provider 绕过规范结果类型时失败关闭。"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price_result.return_value = {"price": 0}
        service._provider = mock_provider

        price = service.get_current_price("000001.SZ")

        assert price is None

    def test_get_current_price_with_invalid_string_raises_error(self):
        """测试处理无效字符串抛出异常"""
        service = MarketPriceService()
        mock_provider = Mock()
        mock_provider.get_price_result.return_value = "invalid"
        service._provider = mock_provider

        # 应该返回 None，而不是抛出异常
        price = service.get_current_price("000001.SZ")
        assert price is None
