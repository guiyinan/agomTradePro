"""
主导航 404 检查测试

目的：确保主导航链接不会产生 404 错误
这是 RC Gate 的关键检查项
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.decision_rhythm.infrastructure.models import (
    DecisionRequestModel,
    DecisionResponseModel,
)

User = get_user_model()


def _assert_expected_status(response, expected_statuses, message: str) -> None:
    assert response.status_code in expected_statuses, (
        f"{message}, got {response.status_code}, expected one of {sorted(expected_statuses)}"
    )
    if response.status_code in {301, 302}:
        assert response.headers.get("Location"), f"{message}, redirect missing Location header"


def _response_text(response) -> str:
    """Decode response content for HTML contract assertions."""
    return response.content.decode(response.charset or "utf-8")


def _assert_html_contract(
    response,
    *,
    required_fragments: tuple[str, ...],
    css_assets: tuple[str, ...] = (),
    one_of_fragments: tuple[str, ...] = (),
) -> None:
    """Assert a server-rendered HTML response contains key page contract markers."""
    assert response["Content-Type"].startswith("text/html")
    text = _response_text(response)

    assert text.strip(), "HTML response should not be empty"
    assert "Page not found" not in text
    assert "404" not in text[:4000]

    for fragment in required_fragments:
        assert fragment in text, f"Expected HTML fragment missing: {fragment}"

    for css_asset in css_assets:
        assert css_asset in text, f"Expected CSS asset missing: {css_asset}"

    if one_of_fragments:
        assert any(fragment in text for fragment in one_of_fragments), (
            f"Expected at least one HTML fragment from {one_of_fragments}"
        )


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
        """Dashboard URL 应返回关键页面结构，而不是空壳。"""
        response = authenticated_client.get('/dashboard/')
        _assert_expected_status(response, {200}, "Dashboard should load successfully")
        _assert_html_contract(
            response,
            required_fragments=(
                "投资指挥中心",
                'class="home-title"',
                'class="metric-card"',
                'class="section-link"',
            ),
            css_assets=("/static/css/home.css",),
        )

    def test_dashboard_url_renders_real_pending_request_contract(self, authenticated_client):
        """Dashboard 应能渲染真实待执行 ORM 请求，而不是只接受 dict fixture。"""
        request = DecisionRequestModel.objects.create(
            request_id=f"req_nav_pending_{uuid.uuid4().hex[:8]}",
            asset_code="000003.SH",
            asset_class="a_share",
            direction="BUY",
            priority="HIGH",
            reason="navigation guardrail pending request",
            execution_target="SIMULATED",
            execution_status="PENDING",
        )
        DecisionResponseModel.objects.create(
            request=request,
            approved=True,
            approval_reason="navigation guardrail approved",
        )

        response = authenticated_client.get('/dashboard/')

        _assert_expected_status(response, {200}, "Dashboard pending queue should render successfully")
        text = _response_text(response)
        assert "待执行队列 (1)" in text
        assert "000003.SH" in text
        assert (
            "/decision/workspace/?source=dashboard-pending&amp;security_code=000003.SH&amp;step=5"
            in text
        )
        assert "Internal Server Error" not in text
        assert "Traceback" not in text

    def test_macro_data_url_no_404(self, authenticated_client):
        """宏观数据 URL 应返回图表和指标容器。"""
        response = authenticated_client.get('/macro/data/')
        _assert_expected_status(response, {200}, "Macro data page should load successfully")
        _assert_html_contract(
            response,
            required_fragments=(
                "宏观数据中心",
                'class="stat-card"',
                'id="indicatorInfoBar"',
                'id="mainChart"',
                'id="refreshIndicatorBtn"',
            ),
            css_assets=("/static/css/macro.css",),
        )

    def test_regime_dashboard_url_no_404(self, authenticated_client):
        """Regime Dashboard URL 应返回核心判定区块和样式资源。"""
        response = authenticated_client.get('/regime/dashboard/')
        _assert_expected_status(response, {200}, "Regime dashboard should load successfully")
        _assert_html_contract(
            response,
            required_fragments=(
                "Regime 判定",
                'class="source-badge',
                "同步数据",
            ),
            one_of_fragments=(
                'class="regime-card',
                "暂无 Regime 判定数据",
                'class="empty-state"',
            ),
            css_assets=("/static/css/regime.css",),
        )

    def test_signal_manage_url_no_404(self, authenticated_client):
        """Signal 管理 URL 应返回创建区和统计区。"""
        response = authenticated_client.get('/signal/manage/')
        _assert_expected_status(response, {200}, "Signal manage page should load successfully")
        _assert_html_contract(
            response,
            required_fragments=(
                "投资信号",
                "AI 证伪助手",
                'class="stat-card"',
                'class="condition-builder"',
            ),
            css_assets=("/static/css/signal.css",),
        )

    def test_policy_manage_url_no_404(self, authenticated_client):
        """Policy 管理 URL 应重定向到工作台。"""
        response = authenticated_client.get('/policy/')
        _assert_expected_status(response, {301, 302}, "Policy manage page should redirect")
        assert "/policy/workbench/" in response.headers["Location"]

    def test_policy_workbench_url_contract(self, authenticated_client):
        """Policy 工作台应返回概览卡片与事件表格。"""
        response = authenticated_client.get('/policy/workbench/')
        _assert_expected_status(response, {200}, "Policy workbench should load successfully")
        _assert_html_contract(
            response,
            required_fragments=(
                "政策/情绪/热点工作台",
                'class="overview-card',
                'class="events-table"',
                'id="policy-level-value"',
            ),
            css_assets=("/static/css/policy-workbench.css",),
        )

    def test_equity_screen_url_contract(self, authenticated_client):
        """个股筛选页应返回流程区和推荐区。"""
        response = authenticated_client.get('/equity/screen/')
        _assert_expected_status(response, {200}, "Equity screen should load successfully")
        _assert_html_contract(
            response,
            required_fragments=(
                "个股筛选",
                'class="screen-workflow-step"',
                'id="autoRecommendationStatus"',
                'id="autoRecommendationGrid"',
            ),
        )

    def test_fund_dashboard_url_contract(self, authenticated_client):
        """基金分析页应返回统计卡和评分表。"""
        response = authenticated_client.get('/fund/dashboard/')
        _assert_expected_status(response, {200}, "Fund dashboard should load successfully")
        _assert_html_contract(
            response,
            required_fragments=(
                "基金分析",
                'class="stat-card"',
                'id="multiDimTable"',
                'id="activeSignalsCount"',
            ),
            css_assets=("/static/css/fund.css",),
        )

    def test_asset_analysis_screen_url_contract(self, authenticated_client):
        """资产筛选页应返回资产池卡片和结果表格。"""
        response = authenticated_client.get('/asset-analysis/screen/')
        _assert_expected_status(response, {200}, "Asset analysis screen should load successfully")
        _assert_html_contract(
            response,
            required_fragments=(
                "资产筛选",
                'class="pool-card',
                'id="investableCount"',
                'id="resultsTable"',
            ),
        )

    def test_simulated_trading_dashboard_url_no_404(self, authenticated_client):
        """模拟交易 Dashboard URL 应返回入口卡片和状态区。"""
        response = authenticated_client.get('/simulated-trading/dashboard/')
        _assert_expected_status(
            response,
            {200},
            "Simulated trading dashboard should load successfully",
        )
        _assert_html_contract(
            response,
            required_fragments=(
                "模拟盘交易",
                'class="card-link"',
                'class="status-item-card"',
            ),
            css_assets=("/static/css/simulated-trading.css",),
        )

    def test_backtest_create_url_no_404(self, authenticated_client):
        """回测创建 URL 应返回可用表单和约束字段。"""
        response = authenticated_client.get('/backtest/create/')
        _assert_expected_status(response, {200}, "Backtest create page should load successfully")
        _assert_html_contract(
            response,
            required_fragments=(
                "创建回测",
                'id="backtest-form"',
                'id="start_date"',
                'id="submit-btn"',
            ),
            css_assets=("/static/css/backtest.css",),
        )

    def test_audit_reports_url_no_404(self, authenticated_client):
        """审计报告 URL 应返回报告列表或生成入口。"""
        response = authenticated_client.get('/audit/reports/')
        _assert_expected_status(response, {200}, "Audit reports page should load successfully")
        _assert_html_contract(
            response,
            required_fragments=(
                "审计模块",
                'class="report-grid"',
                "生成归因报告",
            ),
            one_of_fragments=(
                'class="report-card"',
                'class="empty-state"',
                "暂无归因报告",
            ),
        )

    def test_filter_dashboard_url_contract(self, authenticated_client):
        """滤波页面应返回选择器、摘要区和图表容器。"""
        response = authenticated_client.get('/filter/dashboard/')
        _assert_expected_status(response, {200}, "Filter dashboard should load successfully")
        _assert_html_contract(
            response,
            required_fragments=(
                "趋势滤波器",
                'id="filterTypeSelect"',
            ),
            one_of_fragments=(
                'id="mainChart"',
                "暂无滤波数据",
                'class="empty-state"',
            ),
        )

    def test_rotation_assets_url_contract(self, authenticated_client):
        """轮动资产页应返回统计卡和资产卡片。"""
        response = authenticated_client.get('/rotation/assets/')
        _assert_expected_status(response, {200}, "Rotation assets page should load successfully")
        _assert_html_contract(
            response,
            required_fragments=(
                "资产类别",
                'id="assetSearchInput"',
            ),
            one_of_fragments=(
                'class="asset-card"',
                "暂无资产类别数据",
                'class="empty-state"',
            ),
            css_assets=("/static/css/rotation.css",),
        )


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

