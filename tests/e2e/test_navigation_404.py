"""
主导航 404 检查测试

目的：确保主导航链接不会产生 404 错误
这是 RC Gate 的关键检查项
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

User = get_user_model()


@pytest.mark.e2e
@pytest.mark.navigation
@pytest.mark.django_db
class TestNavigationNo404:
    """主导航 404 检查"""

    @pytest.fixture
    def authenticated_client(self):
        """创建已认证的客户端"""
        client = Client()
        # 创建测试用户
        user = User.objects.create_user(
            username='test_nav_user',
            password='test_pass_123',
            email='nav@test.com'
        )
        client.force_login(user)
        return client

    def test_dashboard_url_no_404(self, authenticated_client):
        """Dashboard URL 不应返回 404"""
        response = authenticated_client.get('/dashboard/')
        assert response.status_code != 404, "Dashboard should not return 404"

    def test_macro_data_url_no_404(self, authenticated_client):
        """宏观数据 URL 不应返回 404"""
        response = authenticated_client.get('/macro/data/')
        # 允许重定向 (302) 但不允许 404
        assert response.status_code not in [404], "Macro data page should not return 404"

    def test_regime_dashboard_url_no_404(self, authenticated_client):
        """Regime Dashboard URL 不应返回 404"""
        response = authenticated_client.get('/regime/dashboard/')
        assert response.status_code != 404, "Regime dashboard should not return 404"

    def test_signal_manage_url_no_404(self, authenticated_client):
        """Signal 管理 URL 不应返回 404"""
        response = authenticated_client.get('/signal/manage/')
        assert response.status_code != 404, "Signal manage page should not return 404"

    def test_policy_manage_url_no_404(self, authenticated_client):
        """Policy 管理 URL 不应返回 404"""
        response = authenticated_client.get('/policy/manage/')
        assert response.status_code != 404, "Policy manage page should not return 404"

    def test_simulated_trading_dashboard_url_no_404(self, authenticated_client):
        """模拟交易 Dashboard URL 不应返回 404"""
        response = authenticated_client.get('/simulated-trading/dashboard/')
        assert response.status_code != 404, "Simulated trading dashboard should not return 404"

    def test_backtest_create_url_no_404(self, authenticated_client):
        """回测创建 URL 不应返回 404"""
        response = authenticated_client.get('/backtest/create/')
        assert response.status_code != 404, "Backtest create page should not return 404"

    def test_audit_reports_url_no_404(self, authenticated_client):
        """审计报告 URL 不应返回 404"""
        response = authenticated_client.get('/audit/reports/')
        assert response.status_code != 404, "Audit reports page should not return 404"


@pytest.mark.e2e
@pytest.mark.navigation
class TestAPIEndpointsNo404:
    """API 端点 404 检查"""

    @pytest.fixture
    def api_client(self):
        """创建 API 客户端"""
        return Client()

    def test_api_health_check_no_404(self, api_client):
        """健康检查 API 不应返回 404"""
        response = api_client.get('/api/health/')
        # 允许 405 (方法不允许) 但不允许 404
        assert response.status_code != 404, "API health check should not return 404"

    def test_api_regime_current_no_404(self, api_client):
        """Regime 当前状态 API 不应返回 404"""
        response = api_client.get('/api/regime/current/')
        assert response.status_code != 404, "Regime current API should not return 404"

    def test_api_signal_list_no_404(self, api_client):
        """Signal 列表 API 不应返回 404"""
        response = api_client.get('/api/signal/')
        assert response.status_code != 404, "Signal list API should not return 404"

    def test_api_policy_list_no_404(self, api_client):
        """Policy 列表 API 不应返回 404"""
        response = api_client.get('/api/policy/')
        assert response.status_code != 404, "Policy list API should not return 404"
