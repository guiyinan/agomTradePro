"""
估值修复跟踪 API 契约测试

测试所有估值修复相关 API 端点的契约（Content-Type、状态码、响应 schema）。

这些测试使用 Mock 避免依赖真实数据。
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.equity.domain.entities_valuation_repair import (
    PercentilePoint,
    ValuationRepairPhase,
    ValuationRepairStatus,
)

User = get_user_model()


@pytest.fixture
def api_client(db):
    """创建已认证的 API 客户端

    使用 pytest-django 的 db fixture 启用数据库访问。
    """
    client = APIClient()
    user = User.objects.create_user(
        username='testuser',
        email='test@example.com',
        password='testpass123'
    )
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def mock_stock_repo():
    """Mock 股票仓储"""
    repo = MagicMock()
    return repo


@pytest.fixture
def mock_repair_repo():
    """Mock 估值修复仓储"""
    repo = MagicMock()
    return repo


@pytest.fixture
def sample_repair_status():
    """示例估值修复状态"""
    return ValuationRepairStatus(
        stock_code="000001.SZ",
        stock_name="平安银行",
        as_of_date=date.today(),
        phase=ValuationRepairPhase.REPAIRING.value,
        signal="hold",
        current_pe=8.5,
        current_pb=0.9,
        pe_percentile=0.25,
        pb_percentile=0.30,
        composite_percentile=0.28,
        composite_method="pe_pb_blend",
        repair_start_date=date.today() - timedelta(days=30),
        repair_start_percentile=0.10,
        lowest_percentile=0.08,
        lowest_percentile_date=date.today() - timedelta(days=45),
        repair_progress=0.45,
        target_percentile=0.50,
        repair_speed_per_30d=0.08,
        estimated_days_to_target=82,
        is_stalled=False,
        stall_start_date=None,
        stall_duration_trading_days=0,
        repair_duration_trading_days=30,
        lookback_trading_days=756,
        confidence=0.85,
        description="估值修复进行中，已从底部修复约45%",
    )


class TestValuationRepairStatusAPI:
    """估值修复状态 API 测试"""

    def test_status_endpoint_accepts_dot_in_stock_code(self, api_client, mock_stock_repo, sample_repair_status):
        """
        高优先级：测试 stock_code 支持 . 分隔符

        真实股票代码格式如 000001.SZ，接口必须支持。
        """
        with patch('apps.equity.interface.views.DjangoStockRepository') as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_stock_info.return_value = MagicMock(
                stock_code="000001.SZ",
                name="平安银行"
            )
            mock_instance.get_valuation_history.return_value = [
                MagicMock(
                    trade_date=date.today() - timedelta(days=i),
                    pe=8.5 + i * 0.1,
                    pb=0.9 + i * 0.01
                )
                for i in range(100)
            ]

            response = api_client.get('/api/equity/valuation-repair/000001.SZ/')

            # 不应该返回 404
            assert response.status_code != status.HTTP_404_NOT_FOUND, \
                "Stock codes with '.' should be accepted, got 404 for 000001.SZ"

    def test_status_endpoint_invalid_lookback_days_returns_400(self, api_client):
        """
        中高优先级：测试无效 lookback_days 返回 400 而非 500

        传入非数字或超范围值应返回参数错误。
        """
        response = api_client.get('/api/equity/valuation-repair/000001.SZ/?lookback_days=invalid')

        assert response.status_code == status.HTTP_400_BAD_REQUEST, \
            f"Invalid lookback_days should return 400, got {response.status_code}"
        assert 'error' in response.data or 'success' in response.data

    def test_status_endpoint_lookback_days_too_small_returns_400(self, api_client):
        """lookback_days 过小应返回 400"""
        response = api_client.get('/api/equity/valuation-repair/000001.SZ/?lookback_days=10')

        assert response.status_code == status.HTTP_400_BAD_REQUEST, \
            f"lookback_days < 30 should return 400, got {response.status_code}"

    def test_status_endpoint_lookback_days_too_large_returns_400(self, api_client):
        """lookback_days 过大应返回 400"""
        response = api_client.get('/api/equity/valuation-repair/000001.SZ/?lookback_days=5000')

        assert response.status_code == status.HTTP_400_BAD_REQUEST, \
            f"lookback_days > 2520 should return 400, got {response.status_code}"


class TestValuationRepairHistoryAPI:
    """估值修复历史 API 测试"""

    def test_history_endpoint_accepts_dot_in_stock_code(self, api_client):
        """
        高优先级：测试 history 端点支持 . 分隔符
        """
        with patch('apps.equity.interface.views.DjangoStockRepository') as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_valuation_history.return_value = [
                MagicMock(
                    trade_date=date.today() - timedelta(days=i),
                    pe=8.5 + i * 0.1,
                    pb=0.9 + i * 0.01
                )
                for i in range(100)
            ]

            response = api_client.get('/api/equity/valuation-repair/000001.SZ/history/')

            assert response.status_code != status.HTTP_404_NOT_FOUND, \
                "History endpoint should accept stock codes with '.', got 404"

    def test_history_endpoint_invalid_lookback_days_returns_400(self, api_client):
        """无效 lookback_days 应返回 400"""
        response = api_client.get('/api/equity/valuation-repair/000001.SZ/history/?lookback_days=abc')

        assert response.status_code == status.HTTP_400_BAD_REQUEST, \
            f"Invalid lookback_days should return 400, got {response.status_code}"


class TestValuationRepairScanAPI:
    """估值修复扫描 API 测试"""

    def test_scan_endpoint_not_captured_by_status_route(self, api_client):
        """
        高优先级：测试 scan 端点不被 status 路由捕获

        POST /valuation-repair/scan/ 应该到达 scan action，而非被 stock_code 路由拦截。
        """
        with patch('apps.equity.interface.views.DjangoStockRepository') as MockStockRepo, \
             patch('apps.equity.interface.views.DjangoValuationRepairRepository') as MockRepairRepo:

            mock_stock = MockStockRepo.return_value
            mock_stock.list_active_stock_codes.return_value = []  # 空列表避免实际扫描

            response = api_client.post('/api/equity/valuation-repair/scan/', {
                'universe': 'all_active',
                'lookback_days': 756
            })

            # 不应该返回 405 Method Not Allowed
            assert response.status_code != status.HTTP_405_METHOD_NOT_ALLOWED, \
                "Scan endpoint should accept POST, got 405"

            # 也不应该返回 404
            assert response.status_code != status.HTTP_404_NOT_FOUND, \
                "Scan endpoint should exist, got 404"

    def test_scan_endpoint_returns_correct_structure(self, api_client):
        """测试 scan 响应结构"""
        # Mock the use case to avoid needing actual stock data
        with patch('apps.equity.interface.views.ScanValuationRepairsUseCase') as MockUseCase:
            mock_use_case = MockUseCase.return_value
            mock_use_case.execute.return_value = MagicMock(
                success=True,
                universe='all_active',
                as_of_date=date.today(),
                scanned_count=0,
                saved_count=0,
                failed_count=0,
                phase_counts={}
            )

            response = api_client.post('/api/equity/valuation-repair/scan/', {
                'universe': 'all_active',
                'lookback_days': 756
            })

            assert response.status_code == status.HTTP_200_OK
            # 验证响应结构
            assert 'success' in response.data
            assert response.data['success'] is True

    def test_scan_endpoint_blocked_when_quality_gate_not_passed(self, api_client):
        """质量门禁未通过时应阻断 scan。"""
        with patch('apps.equity.interface.views.ScanValuationRepairsUseCase') as MockUseCase:
            mock_use_case = MockUseCase.return_value
            mock_use_case.execute.return_value = MagicMock(
                success=False,
                error='valuation data quality gate not passed'
            )

            response = api_client.post('/api/equity/valuation-repair/scan/', {
                'universe': 'all_active',
                'lookback_days': 756
            })

            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert response.data['success'] is False
            assert 'gate' in response.data['error']


class TestValuationRepairListAPI:
    """估值修复列表 API 测试"""

    def test_list_endpoint_returns_all_required_fields(self, api_client):
        """
        中高优先级：测试 list 端点返回所有必需字段

        响应必须包含：
        - repair_speed_per_30d
        - repair_duration_trading_days
        - estimated_days_to_target
        """
        # 创建模拟快照
        mock_snapshot = MagicMock()
        mock_snapshot.stock_code = "000001.SZ"
        mock_snapshot.stock_name = "平安银行"
        mock_snapshot.as_of_date = date.today()
        mock_snapshot.current_phase = ValuationRepairPhase.REPAIRING.value
        mock_snapshot.signal = "hold"
        mock_snapshot.composite_percentile = 0.28
        mock_snapshot.repair_progress = 0.45
        mock_snapshot.repair_speed_per_30d = 0.08
        mock_snapshot.repair_duration_trading_days = 30
        mock_snapshot.estimated_days_to_target = 82
        mock_snapshot.is_stalled = False
        mock_snapshot.confidence = 0.85

        with patch('apps.equity.interface.views.DjangoValuationRepairRepository') as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.list_active_snapshots.return_value = [mock_snapshot]

            response = api_client.get('/api/equity/valuation-repair-list/')

            assert response.status_code == status.HTTP_200_OK
            assert response.data['success'] is True
            assert len(response.data['results']) > 0

            item = response.data['results'][0]

            # 验证必需字段存在
            required_fields = [
                'stock_code',
                'stock_name',
                'phase',
                'signal',
                'composite_percentile',
                'repair_progress',
                'repair_speed_per_30d',
                'repair_duration_trading_days',
                'estimated_days_to_target',
                'is_stalled',
                'as_of_date',
            ]

            for field in required_fields:
                assert field in item, f"Missing required field: {field}"

    def test_list_endpoint_invalid_limit_returns_400(self, api_client):
        """无效 limit 参数应返回 400"""
        response = api_client.get('/api/equity/valuation-repair-list/?limit=abc')

        assert response.status_code == status.HTTP_400_BAD_REQUEST, \
            f"Invalid limit should return 400, got {response.status_code}"


class TestValuationRepairContentType:
    """Content-Type 测试"""

    def test_status_endpoint_returns_json(self, api_client):
        """验证 Content-Type 是 application/json"""
        with patch('apps.equity.interface.views.DjangoStockRepository') as MockRepo:
            mock_instance = MockRepo.return_value
            mock_instance.get_stock_info.return_value = MagicMock(
                stock_code="000001.SZ",
                name="平安银行"
            )
            mock_instance.get_valuation_history.return_value = [
                MagicMock(
                    trade_date=date.today() - timedelta(days=i),
                    pe=8.5,
                    pb=0.9
                )
                for i in range(100)
            ]

            response = api_client.get('/api/equity/valuation-repair/000001.SZ/')

            assert 'application/json' in response.get('Content-Type', ''), \
                f"Expected JSON response, got {response.get('Content-Type')}"


class TestValuationDataQualityAPI:
    """估值数据质量 API 测试"""

    def test_validate_endpoint_returns_snapshot(self, api_client):
        with patch('apps.equity.interface.views.ValidateEquityValuationQualityUseCase') as MockUseCase:
            mock_use_case = MockUseCase.return_value
            mock_use_case.execute.return_value = MagicMock(
                success=True,
                data={
                    'as_of_date': date.today().isoformat(),
                    'expected_stock_count': 10,
                    'synced_stock_count': 10,
                    'valid_stock_count': 10,
                    'coverage_ratio': 1.0,
                    'valid_ratio': 1.0,
                    'missing_pb_count': 0,
                    'invalid_pb_count': 0,
                    'missing_pe_count': 0,
                    'jump_alert_count': 0,
                    'source_deviation_count': 0,
                    'primary_source': 'akshare',
                    'fallback_used_count': 0,
                    'is_gate_passed': True,
                    'gate_reason': '',
                }
            )

            response = api_client.post('/api/equity/valuation-data/validate/', {})
            assert response.status_code == status.HTTP_200_OK
            assert response.data['is_gate_passed'] is True

    def test_freshness_endpoint_returns_status(self, api_client):
        with patch('apps.equity.interface.views.GetEquityValuationFreshnessUseCase') as MockUseCase:
            mock_use_case = MockUseCase.return_value
            mock_use_case.execute.return_value = MagicMock(
                success=True,
                data={
                    'latest_trade_date': date.today().isoformat(),
                    'lag_days': 0,
                    'freshness_status': 'fresh',
                    'coverage_ratio': 1.0,
                    'is_gate_passed': True,
                }
            )

            response = api_client.get('/api/equity/valuation-data/freshness/')
            assert response.status_code == status.HTTP_200_OK
            assert response.data['freshness_status'] == 'fresh'

    def test_quality_latest_endpoint_returns_snapshot(self, api_client):
        with patch('apps.equity.interface.views.GetLatestEquityValuationQualityUseCase') as MockUseCase:
            mock_use_case = MockUseCase.return_value
            mock_use_case.execute.return_value = MagicMock(
                success=True,
                data={
                    'as_of_date': date.today().isoformat(),
                    'expected_stock_count': 10,
                    'synced_stock_count': 10,
                    'valid_stock_count': 10,
                    'coverage_ratio': 1.0,
                    'valid_ratio': 1.0,
                    'missing_pb_count': 0,
                    'invalid_pb_count': 0,
                    'missing_pe_count': 0,
                    'jump_alert_count': 0,
                    'source_deviation_count': 0,
                    'primary_source': 'akshare',
                    'fallback_used_count': 0,
                    'is_gate_passed': True,
                    'gate_reason': '',
                }
            )

            response = api_client.get('/api/equity/valuation-data/quality-latest/')
            assert response.status_code == status.HTTP_200_OK
            assert 'coverage_ratio' in response.data

    def test_sync_endpoint_returns_statistics(self, api_client):
        with patch('apps.equity.interface.views.SyncEquityValuationUseCase') as MockUseCase:
            mock_use_case = MockUseCase.return_value
            mock_use_case.execute.return_value = MagicMock(
                success=True,
                data={
                    'requested_count': 2,
                    'synced_count': 20,
                    'fallback_used_count': 1,
                    'skipped_count': 0,
                    'error_count': 0,
                    'start_date': date.today().isoformat(),
                    'end_date': date.today().isoformat(),
                    'errors': [],
                }
            )

            response = api_client.post('/api/equity/valuation-data/sync/', {
                'days_back': 1,
                'primary_source': 'akshare',
                'fallback_source': 'tushare',
            }, format='json')

            assert response.status_code == status.HTTP_200_OK
            assert response.data['synced_count'] == 20
