"""
主导航 404 检查测试

目的：确保主导航链接不会产生 404 错误
这是 RC Gate 的关键检查项
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

User = get_user_model()


def _assert_expected_status(response, expected_statuses, message: str) -> None:
    assert response.status_code in expected_statuses, (
        f"{message}, got {response.status_code}, expected one of {sorted(expected_statuses)}"
    )
    if response.status_code in {301, 302}:
        assert response.headers.get("Location"), f"{message}, redirect missing Location header"


@pytest.mark.e2e
@pytest.mark.navigation
@pytest.mark.django_db
class TestNavigationNo404:
    """主导航 404 检查"""

    @pytest.fixture
    def authenticated_client(self):
        """创建已认证的客户端"""
        client = Client()
        user = User.objects.create_user(
            username=f"test_nav_user_{uuid.uuid4().hex[:8]}",
            password='test_pass_123',
            email='nav@test.com'
        )
        client.force_login(user)
        return client

    def test_dashboard_url_no_404(self, authenticated_client):
        """Dashboard URL 应返回成功状态。"""
        response = authenticated_client.get('/dashboard/')
        _assert_expected_status(response, {200}, "Dashboard should load successfully")

    def test_macro_data_url_no_404(self, authenticated_client):
        """宏观数据 URL 应返回成功状态。"""
        response = authenticated_client.get('/macro/data/')
        _assert_expected_status(response, {200}, "Macro data page should load successfully")

    def test_regime_dashboard_url_no_404(self, authenticated_client):
        """Regime Dashboard URL 应返回成功状态。"""
        response = authenticated_client.get('/regime/dashboard/')
        _assert_expected_status(response, {200}, "Regime dashboard should load successfully")

    def test_signal_manage_url_no_404(self, authenticated_client):
        """Signal 管理 URL 应返回成功状态。"""
        response = authenticated_client.get('/signal/manage/')
        _assert_expected_status(response, {200}, "Signal manage page should load successfully")

    def test_policy_manage_url_no_404(self, authenticated_client):
        """Policy 管理 URL 应重定向到工作台。"""
        response = authenticated_client.get('/policy/manage/')
        _assert_expected_status(response, {301, 302}, "Policy manage page should redirect")
        assert "/policy/workbench/" in response.headers["Location"]

    def test_simulated_trading_dashboard_url_no_404(self, authenticated_client):
        """模拟交易 Dashboard URL 应返回成功状态。"""
        response = authenticated_client.get('/simulated-trading/dashboard/')
        _assert_expected_status(
            response,
            {200},
            "Simulated trading dashboard should load successfully",
        )

    def test_backtest_create_url_no_404(self, authenticated_client):
        """回测创建 URL 应返回成功状态。"""
        response = authenticated_client.get('/backtest/create/')
        _assert_expected_status(response, {200}, "Backtest create page should load successfully")

    def test_audit_reports_url_no_404(self, authenticated_client):
        """审计报告 URL 应返回成功状态。"""
        response = authenticated_client.get('/audit/reports/')
        _assert_expected_status(response, {200}, "Audit reports page should load successfully")


@pytest.mark.e2e
@pytest.mark.navigation
class TestAPIEndpointsNo404:
    """API 端点 404 检查"""

    @pytest.fixture
    def api_client(self):
        """创建 API 客户端"""
        return Client()

    def test_api_health_check_no_404(self, api_client):
        """健康检查 API 应返回成功状态。"""
        response = api_client.get('/api/health/')
        _assert_expected_status(response, {200}, "API health check should be available")
        assert response["Content-Type"].startswith("application/json")

    def test_api_regime_current_no_404(self, api_client):
        """Regime 当前状态 API 应要求认证或返回成功。"""
        response = api_client.get('/api/regime/current/')
        _assert_expected_status(
            response,
            {200, 401, 403},
            "Regime current API should be reachable",
        )

    def test_api_signal_list_no_404(self, api_client):
        """Signal 列表 API 应要求认证或返回成功。"""
        response = api_client.get('/api/signal/')
        _assert_expected_status(
            response,
            {200, 401, 403, 405},
            "Signal list API should be reachable",
        )

    def test_api_policy_list_no_404(self, api_client):
        """Policy 列表 API 应要求认证或返回成功。"""
        response = api_client.get('/api/policy/')
        _assert_expected_status(
            response,
            {200, 401, 403, 405},
            "Policy list API should be reachable",
        )
