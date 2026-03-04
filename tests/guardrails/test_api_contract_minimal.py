"""
API 合同最小集测试

这些测试验证所有关键 API 端点的基本契约：
1. 不返回 501 占位符响应
2. 对于成功的响应，返回正确的 Content-Type (application/json)

这是 PR Gate 必须通过的快速验证集合，预计 1-2 分钟完成。
"""

import pytest
from rest_framework.test import APIClient


def _build_authenticated_client() -> APIClient:
    """创建认证的 API 客户端"""
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    user, _ = user_model.objects.get_or_create(
        username="api_contract_tester",
        defaults={"email": "test@example.com"}
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# 测试端点列表：(路径, 描述, 应检查 Content-Type)
API_ENDPOINTS = [
    # 核心端点
    ("/api/health/", "Health endpoint", True),
    ("/api/ready/", "Readiness endpoint", True),

    # 业务 API 端点 - 已确认实现
    ("/api/regime/current/", "Regime current state", True),
    ("/api/policy/events/", "Policy events list", False),  # 可能返回 400
    ("/events/api/query/", "Events query", True),
    ("/events/api/status/", "Events status", True),
    ("/api/alpha/recommendations/", "Alpha recommendations", False),  # 可能返回 400
    ("/api/asset-analysis/screen/", "Asset analysis screen", False),  # POST 接口
    ("/api/realtime/prices/", "Realtime prices", True),

    # 已验证的合同测试
    ("/signal/", "Signal list", False),  # 可能返回 HTML redirect
]


@pytest.mark.django_db
@pytest.mark.parametrize("path,description,check_content_type", API_ENDPOINTS)
def test_api_endpoint_no_501(path, description, check_content_type):
    """
    验证关键 API 端点不返回 501 占位符

    这是最基本的 API 契约验证 - 确保端点已实现，
    而不是返回 501 NotImplemented。
    """
    client = _build_authenticated_client()

    # 对于 POST 接口使用 POST 请求
    if "screen" in path or "analyze" in path:
        response = client.post(path, data={}, format="json")
    else:
        response = client.get(path)

    # 核心断言：不应返回 501
    assert response.status_code != 501, (
        f"{description} at {path} returned 501. "
        f"This endpoint appears to be a placeholder. "
        f"Status: {response.status_code}"
    )

    # 如果需要检查 Content-Type 且响应成功
    if check_content_type and response.status_code == 200:
        assert response.headers.get("Content-Type", "").startswith("application/json"), (
            f"{description} at {path} should return JSON, got "
            f"{response.headers.get('Content-Type', 'no content-type')}"
        )


@pytest.mark.django_db
class TestCoreAPIStructure:
    """测试核心 API 结构完整性"""

    def test_api_schema_accessible(self):
        """OpenAPI schema 端点应可访问"""
        client = _build_authenticated_client()
        response = client.get("/api/schema/")

        assert response.status_code == 200
        # Schema 可能返回 application/vnd.oai.openapi 或 application/json
        content_type = response.headers.get("Content-Type", "")
        assert "json" in content_type or "openapi" in content_type.lower()

    def test_api_docs_accessible(self):
        """API 文档端点应可访问"""
        client = _build_authenticated_client()
        response = client.get("/api/docs/")

        # Swagger UI 应返回 HTML
        assert response.status_code == 200
        assert "html" in response.headers.get("Content-Type", "").lower()


@pytest.mark.django_db
class TestCriticalBusinessAPIs:
    """关键业务 API 的 501 检查"""

    def test_regime_current_api_no_501(self):
        """Regime 当前状态 API 不应返回 501"""
        client = _build_authenticated_client()
        response = client.get("/api/regime/current/")

        assert response.status_code != 501
        if response.status_code == 200:
            assert response.headers["Content-Type"].startswith("application/json")

    def test_policy_events_api_no_501(self):
        """Policy 事件 API 不应返回 501"""
        client = _build_authenticated_client()
        response = client.get("/api/policy/events/")

        assert response.status_code != 501
        if response.status_code in [200, 400]:
            assert response.headers["Content-Type"].startswith("application/json")

    def test_signal_workflow_api_no_501(self):
        """Signal 工作流相关 API 不应返回 501"""
        client = _build_authenticated_client()

        # 测试 signal list
        response = client.get("/api/signal/")
        assert response.status_code != 501

    def test_events_api_no_501(self):
        """Events 系统 API 不应返回 501"""
        client = _build_authenticated_client()

        # 测试 events query
        response = client.get("/events/api/query/")
        assert response.status_code != 501
        if response.status_code == 200:
            assert response.headers["Content-Type"].startswith("application/json")

        # 测试 events status
        response = client.get("/events/api/status/")
        assert response.status_code != 501
        if response.status_code == 200:
            assert response.headers["Content-Type"].startswith("application/json")

    def test_audit_api_no_501(self):
        """审计 API 不应返回 501"""
        client = _build_authenticated_client()
        response = client.get("/api/audit/")

        assert response.status_code != 501

    def test_alpha_api_no_501(self):
        """Alpha 选股 API 不应返回 501"""
        client = _build_authenticated_client()
        response = client.get("/api/alpha/recommendations/")

        assert response.status_code != 501
        if response.status_code == 200:
            assert response.headers["Content-Type"].startswith("application/json")

    def test_backtest_api_no_501(self):
        """回测 API 不应返回 501"""
        client = _build_authenticated_client()
        response = client.get("/api/backtest/")

        assert response.status_code != 501

    def test_account_api_no_501(self):
        """账户 API 不应返回 501"""
        client = _build_authenticated_client()
        response = client.get("/api/account/")

        assert response.status_code != 501

    def test_strategy_api_no_501(self):
        """策略 API 不应返回 501"""
        client = _build_authenticated_client()
        response = client.get("/api/strategy/strategies/")

        assert response.status_code != 501


# API 端点清单（用于文档和验证覆盖）
"""
API 端点覆盖清单：

核心端点:
- /api/health/ - 系统健康检查
- /api/ready/ - 就绪状态检查
- /api/schema/ - OpenAPI schema

业务端点 (Phase 1-3 必须实现):
- /api/regime/current/ - 当前 Regime 状态
- /api/policy/events/ - 政策事件列表
- /api/signal/ - 投资信号
- /events/api/query/ - 事件查询
- /events/api/status/ - 事件系统状态
- /api/audit/ - 审计日志
- /api/alpha/recommendations/ - Alpha 推荐信号
- /api/backtest/ - 回测任务
- /api/account/ - 投资账户
- /api/strategy/strategies/ - 策略管理
"""
