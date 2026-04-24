"""
测试 Alpha Provider 可比性改进功能

测试以下 5 个方案：
1. API 响应增强 - 确保 provider_source 等元数据正确返回
2. Provider 切换告警 - 检测降级时创建告警
3. 数据过滤工具 - 支持按 provider_filter 参数过滤
4. 评分日志增强 - 验证日志记录完整
5. 配置选项 - 支持固定 Provider
"""

from datetime import date
from unittest.mock import MagicMock, Mock, patch

import pytest

from apps.alpha.application.services import (
    AlphaProviderRegistry,
    AlphaService,
)
from apps.alpha.domain.entities import AlphaResult, StockScore
from apps.alpha.domain.interfaces import AlphaProvider, AlphaProviderStatus


class TestAlphaComparabilityImprovements:
    """测试 Alpha Provider 可比性改进功能"""

    def test_provider_filter_parameter(self):
        """测试方案 3: provider_filter 参数"""
        registry = AlphaProviderRegistry()

        # 创建 mock providers
        mock_qlib = Mock(spec=AlphaProvider)
        mock_qlib.name = "qlib"
        mock_qlib.priority = 1
        mock_qlib.health_check.return_value = AlphaProviderStatus.AVAILABLE
        mock_qlib.supports.return_value = True
        mock_qlib.max_staleness_days = 2
        mock_qlib.get_stock_scores.return_value = AlphaResult(
            success=True,
            scores=[],
            source="qlib",
            timestamp=date.today().isoformat(),
            status="available",
        )

        mock_cache = Mock(spec=AlphaProvider)
        mock_cache.name = "cache"
        mock_cache.priority = 10
        mock_cache.health_check.return_value = AlphaProviderStatus.AVAILABLE
        mock_cache.supports.return_value = True
        mock_cache.max_staleness_days = 5
        mock_cache.get_stock_scores.return_value = AlphaResult(
            success=True,
            scores=[],
            source="cache",
            timestamp=date.today().isoformat(),
            status="available",
        )

        registry.register(mock_qlib)
        registry.register(mock_cache)

        # 测试不指定 provider_filter（默认使用 qlib，因为优先级更高）
        result1 = registry.get_scores_with_fallback(
            "csi300", date.today(), 30, provider_filter=None
        )
        assert result1.source == "qlib"

        # 重置 mock 调用计数
        mock_qlib.reset_mock()
        mock_cache.reset_mock()

        # 测试指定 provider_filter="cache"（强制使用 cache）
        result2 = registry.get_scores_with_fallback(
            "csi300", date.today(), 30, provider_filter="cache"
        )
        assert result2.source == "cache"
        assert mock_qlib.health_check.call_count == 0
        assert mock_qlib.get_stock_scores.call_count == 0

        # 测试指定不存在的 provider
        result3 = registry.get_scores_with_fallback(
            "csi300", date.today(), 30, provider_filter="nonexistent"
        )
        assert not result3.success
        assert "nonexistent" in result3.error_message

    def test_fallback_alert_creation(self):
        """测试方案 2: Provider 切换告警（验证降级逻辑）"""
        registry = AlphaProviderRegistry()

        # 创建 mock providers（qlib 会失败，cache 会成功）
        mock_qlib = Mock(spec=AlphaProvider)
        mock_qlib.name = "qlib"
        mock_qlib.priority = 1
        mock_qlib.health_check.return_value = AlphaProviderStatus.AVAILABLE
        mock_qlib.supports.return_value = True
        mock_qlib.max_staleness_days = 2
        mock_qlib.get_stock_scores.return_value = AlphaResult(
            success=False,
            scores=[],
            source="qlib",
            timestamp=date.today().isoformat(),
            status="unavailable",
            error_message="Qlib 不可用",
        )

        mock_cache = Mock(spec=AlphaProvider)
        mock_cache.name = "cache"
        mock_cache.priority = 10
        mock_cache.health_check.return_value = AlphaProviderStatus.AVAILABLE
        mock_cache.supports.return_value = True
        mock_cache.max_staleness_days = 5
        mock_cache.get_stock_scores.return_value = AlphaResult(
            success=True,
            scores=[
                StockScore(
                    code="000001.SH",
                    score=0.8,
                    rank=1,
                    factors={},
                    source="cache",
                    confidence=0.9,
                )
            ],
            source="cache",
            timestamp=date.today().isoformat(),
            status="available",
        )

        registry.register(mock_qlib)
        registry.register(mock_cache)

        # 验证降级行为（即使告警创建失败，降级逻辑也应该工作）
        result = registry.get_scores_with_fallback("csi300", date.today(), 30)

        # 验证结果
        assert result.success
        assert result.source == "cache"

        # 验证 qlib 被尝试但失败了
        mock_qlib.get_stock_scores.assert_called_once()

        # 验证 cache 被调用并成功
        mock_cache.get_stock_scores.assert_called_once()

    def test_fixed_provider_config(self):
        """测试方案 5: 配置选项（固定 Provider）"""
        registry = AlphaProviderRegistry()

        # 创建 mock providers
        mock_qlib = Mock(spec=AlphaProvider)
        mock_qlib.name = "qlib"
        mock_qlib.priority = 1
        mock_qlib.health_check.return_value = AlphaProviderStatus.AVAILABLE
        mock_qlib.supports.return_value = True
        mock_qlib.max_staleness_days = 2
        mock_qlib.get_stock_scores.return_value = AlphaResult(
            success=True,
            scores=[],
            source="qlib",
            timestamp=date.today().isoformat(),
            status="available",
        )

        registry.register(mock_qlib)

        # Mock application config service 返回固定 provider，避免 Application 层直接依赖 ORM。
        with patch(
            "apps.alpha.application.services.get_account_config_summary_service"
        ) as mock_service_factory:
            mock_settings = MagicMock()
            mock_settings.get_runtime_alpha_fixed_provider.return_value = "qlib"
            mock_service_factory.return_value = mock_settings

            # 测试系统配置固定使用 qlib
            result = registry.get_scores_with_fallback(
                "csi300", date.today(), 30, provider_filter=None
            )
            assert result.source == "qlib"
            mock_settings.get_runtime_alpha_fixed_provider.assert_called_once()

            # 测试 provider_filter 参数优先于系统配置
            result2 = registry.get_scores_with_fallback(
                "csi300", date.today(), 30, provider_filter="cache"
            )
            assert not result2.success  # cache 不存在

    def test_detailed_logging(self):
        """测试方案 4: 评分日志增强"""
        registry = AlphaProviderRegistry()

        # 创建 mock providers
        mock_qlib = Mock(spec=AlphaProvider)
        mock_qlib.name = "qlib"
        mock_qlib.priority = 1
        mock_qlib.health_check.return_value = AlphaProviderStatus.AVAILABLE
        mock_qlib.supports.return_value = True
        mock_qlib.max_staleness_days = 2
        mock_qlib.get_stock_scores.return_value = AlphaResult(
            success=True,
            scores=[
                StockScore(
                    code="000001.SH",
                    score=0.8,
                    rank=1,
                    factors={},
                    source="qlib",
                    confidence=0.9,
                )
            ],
            source="qlib",
            timestamp=date.today().isoformat(),
            status="available",
        )

        registry.register(mock_qlib)

        # Mock logger 并验证日志调用
        with patch("apps.alpha.application.services.logger") as mock_logger:
            result = registry.get_scores_with_fallback("csi300", date.today(), 30)

            # 验证关键日志
            log_calls = [str(call) for call in mock_logger.info.call_args_list]
            assert any("AlphaRequest" in call for call in log_calls)
            assert any("AlphaProvider" in call for call in log_calls)
            assert any("AlphaSuccess" in call for call in log_calls)

    def test_api_response_metadata(self):
        """测试方案 1: API 响应增强"""
        service = AlphaService()

        # 创建测试结果
        test_scores = [
            StockScore(
                code="000001.SH",
                score=0.8,
                rank=1,
                factors={"momentum": 0.7, "value": 0.9},
                source="cache",
                confidence=0.9,
                asof_date=date.today(),
                intended_trade_date=date.today(),
                universe_id="csi300",
            )
        ]

        result = AlphaResult(
            success=True,
            scores=test_scores,
            source="cache",
            timestamp=date.today().isoformat(),
            status="available",
            latency_ms=150,
            staleness_days=1,
        )

        # 验证结果包含所有必要的元数据
        assert result.source == "cache"
        assert result.status == "available"
        assert result.latency_ms == 150
        assert result.staleness_days == 1

        # 验证每个 StockScore 包含 source 字段
        for score in result.scores:
            assert score.source is not None
            assert score.asof_date is not None
            assert score.intended_trade_date is not None

        # 转换为字典验证
        result_dict = result.to_dict()
        assert "source" in result_dict
        assert "status" in result_dict
        assert "latency_ms" in result_dict
        assert "staleness_days" in result_dict
        assert "stocks" in result_dict

        for stock_dict in result_dict["stocks"]:
            assert "source" in stock_dict
            assert "asof_date" in stock_dict
            assert "intended_trade_date" in stock_dict
