"""
Integration tests for Operation Audit Log API.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.audit.infrastructure.models import OperationLogModel

pytestmark = [pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _override_cache_and_throttle(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "audit-api-tests",
        }
    }
    settings.REST_FRAMEWORK = {
        **getattr(settings, "REST_FRAMEWORK", {}),
        "DEFAULT_THROTTLE_CLASSES": [],
        "DEFAULT_THROTTLE_RATES": {},
    }


@pytest.fixture
def admin_user():
    """创建管理员用户"""
    user = User.objects.create_user(
        username=f"admin_{uuid.uuid4().hex[:8]}",
        password='admin123',
        is_superuser=True,
    )
    user.rbac_role = 'admin'
    return user


@pytest.fixture
def regular_user():
    """创建普通用户"""
    user = User.objects.create_user(
        username=f"analyst_{uuid.uuid4().hex[:8]}",
        password='analyst123',
    )
    user.rbac_role = 'analyst'
    return user


@pytest.fixture
def api_client():
    """创建 API 客户端"""
    return APIClient()


@pytest.fixture
def sample_log(admin_user):
    """创建示例日志"""
    return OperationLogModel._default_manager.create(
        request_id='req-test-001',
        user_id=admin_user.id,
        username=admin_user.username,
        source='MCP',
        operation_type='MCP_CALL',
        module='signal',
        action='CREATE',
        mcp_tool_name='create_signal',
        request_params={'asset_code': '000001.SH'},
        response_status=200,
        response_message='Success',
        ip_address='127.0.0.1',
        user_agent='Test Agent',
    )


@pytest.mark.django_db
class TestOperationLogAPI:
    """测试操作日志 API"""

    def test_list_logs_as_admin(self, api_client, admin_user, sample_log):
        """测试管理员列出日志"""
        api_client.force_authenticate(user=admin_user)
        response = api_client.get('/audit/api/operation-logs/')

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert len(data['logs']) >= 1
        assert data['total_count'] >= 1

    def test_list_logs_as_regular_user(self, api_client, regular_user):
        """测试普通用户列出日志（仅自己的）"""
        # 创建普通用户的日志
        OperationLogModel._default_manager.create(
            request_id='req-test-002',
            user_id=regular_user.id,
            username=regular_user.username,
            source='MCP',
            operation_type='MCP_CALL',
            module='signal',
            action='READ',
            mcp_tool_name='get_signals',
            request_params={},
            response_status=200,
        )

        api_client.force_authenticate(user=regular_user)
        response = api_client.get('/audit/api/operation-logs/')

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        # 普通用户只能看到自己的日志
        for log in data['logs']:
            assert log['user_id'] == regular_user.id

    def test_get_log_detail_as_owner(self, api_client, regular_user):
        """测试用户查看自己的日志详情"""
        log = OperationLogModel._default_manager.create(
            request_id='req-test-003',
            user_id=regular_user.id,
            username=regular_user.username,
            source='MCP',
            operation_type='MCP_CALL',
            module='signal',
            action='READ',
            mcp_tool_name='get_signals',
            request_params={},
            response_status=200,
        )

        api_client.force_authenticate(user=regular_user)
        response = api_client.get(f'/audit/api/operation-logs/{log.id}/')

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['log']['id'] == str(log.id)

    def test_get_log_detail_forbidden_for_other_user(self, api_client, regular_user, sample_log):
        """测试用户不能查看他人日志"""
        api_client.force_authenticate(user=regular_user)
        response = api_client.get(f'/audit/api/operation-logs/{sample_log.id}/')

        assert response.status_code == 403

    def test_filter_by_module(self, api_client, admin_user, sample_log):
        """测试按模块过滤"""
        api_client.force_authenticate(user=admin_user)
        response = api_client.get('/audit/api/operation-logs/?module=signal')

        assert response.status_code == 200
        data = response.json()
        for log in data['logs']:
            assert log['module'] == 'signal'

    def test_filter_by_status(self, api_client, admin_user):
        """测试按状态码过滤"""
        # 创建不同状态码的日志
        OperationLogModel._default_manager.create(
            request_id='req-test-004',
            user_id=admin_user.id,
            username=admin_user.username,
            source='MCP',
            operation_type='MCP_CALL',
            module='signal',
            action='CREATE',
            mcp_tool_name='create_signal',
            request_params={},
            response_status=500,
            error_code='INTERNAL_ERROR',
        )

        api_client.force_authenticate(user=admin_user)
        response = api_client.get('/audit/api/operation-logs/?response_status=500')

        assert response.status_code == 200
        data = response.json()
        for log in data['logs']:
            assert log['response_status'] == 500

    def test_stats_as_admin(self, api_client, admin_user, sample_log):
        """测试管理员查看统计"""
        api_client.force_authenticate(user=admin_user)
        response = api_client.get('/audit/api/operation-logs/stats/')

        assert response.status_code == 200
        data = response.json()
        assert 'total_count' in data
        assert 'error_count' in data
        assert 'error_rate' in data

    def test_stats_forbidden_for_regular_user(self, api_client, regular_user):
        """测试普通用户不能查看统计"""
        api_client.force_authenticate(user=regular_user)
        response = api_client.get('/audit/api/operation-logs/stats/')

        assert response.status_code == 403

    def test_export_as_admin(self, api_client, admin_user, sample_log):
        """测试管理员导出日志"""
        api_client.force_authenticate(user=admin_user)
        response = api_client.get('/audit/api/operation-logs/export/?format=csv')

        assert response.status_code == 200
        assert 'attachment' in response.get('Content-Disposition', '')

    def test_export_as_admin_can_filter_by_token(self, api_client, admin_user):
        """测试管理员可按 token 导出日志。"""
        OperationLogModel._default_manager.create(
            request_id='req-export-token-a',
            user_id=admin_user.id,
            username=admin_user.username,
            source='MCP',
            operation_type='MCP_CALL',
            module='signal',
            action='READ',
            mcp_tool_name='get_signals',
            mcp_client_id='token-a',
            request_params={'scope': 'a'},
            response_status=200,
        )
        OperationLogModel._default_manager.create(
            request_id='req-export-token-b',
            user_id=admin_user.id,
            username=admin_user.username,
            source='MCP',
            operation_type='MCP_CALL',
            module='signal',
            action='READ',
            mcp_tool_name='get_signals',
            mcp_client_id='token-b',
            request_params={'scope': 'b'},
            response_status=200,
        )

        api_client.force_authenticate(user=admin_user)
        response = api_client.get('/audit/api/operation-logs/export/?format=json&mcp_client_id=token-a')

        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 1
        assert payload[0]['mcp_client_id'] == 'token-a'
        assert payload[0]['request_id'] == 'req-export-token-a'

    def test_export_forbidden_for_regular_user(self, api_client, regular_user):
        """测试普通用户不能导出"""
        api_client.force_authenticate(user=regular_user)
        response = api_client.get('/audit/api/operation-logs/export/')

        assert response.status_code == 403

    def test_decision_trace_list_groups_logs_by_request_id(self, api_client, admin_user):
        """测试决策链列表按 request_id 聚合。"""
        OperationLogModel._default_manager.create(
            request_id='trace-001',
            user_id=admin_user.id,
            username=admin_user.username,
            source='MCP',
            operation_type='MCP_CALL',
            module='regime',
            action='READ',
            mcp_tool_name='get_current_regime',
            request_params={},
            response_status=200,
            response_message='Regime loaded',
        )
        OperationLogModel._default_manager.create(
            request_id='trace-001',
            user_id=admin_user.id,
            username=admin_user.username,
            source='MCP',
            operation_type='MCP_CALL',
            module='policy',
            action='READ',
            mcp_tool_name='get_policy_status',
            request_params={},
            response_status=200,
            response_message='Policy loaded',
        )

        api_client.force_authenticate(user=admin_user)
        response = api_client.get('/audit/api/decision-traces/')

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        trace = next(item for item in data['traces'] if item['request_id'] == 'trace-001')
        assert trace['step_count'] == 2
        assert trace['tools'] == ['get_current_regime', 'get_policy_status']

    def test_decision_trace_detail_returns_ordered_steps(self, api_client, admin_user):
        """测试决策链详情返回步骤序列。"""
        OperationLogModel._default_manager.create(
            request_id='trace-002',
            user_id=admin_user.id,
            username=admin_user.username,
            source='MCP',
            operation_type='MCP_CALL',
            module='regime',
            action='READ',
            mcp_tool_name='get_current_regime',
            request_params={},
            response_status=200,
            response_message='Regime loaded',
        )
        OperationLogModel._default_manager.create(
            request_id='trace-002',
            user_id=admin_user.id,
            username=admin_user.username,
            source='MCP',
            operation_type='MCP_CALL',
            module='strategy',
            action='EXECUTE',
            mcp_tool_name='run_strategy',
            request_params={},
            response_status=200,
            response_message='Strategy executed',
            response_payload={'summary': 'Buy CSI300 ETF'},
        )

        api_client.force_authenticate(user=admin_user)
        response = api_client.get('/audit/api/decision-traces/trace-002/')

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['trace']['step_count'] == 2
        assert data['trace']['steps'][0]['tool_name'] == 'get_current_regime'
        assert data['trace']['steps'][1]['tool_name'] == 'run_strategy'
        assert data['trace']['final_summary'] == 'Buy CSI300 ETF'

    def test_decision_trace_list_separates_same_request_id_by_token(self, api_client, admin_user):
        """测试相同 request_id 但不同 token 会拆成不同决策链。"""
        OperationLogModel._default_manager.create(
            request_id='trace-003',
            user_id=admin_user.id,
            username=admin_user.username,
            source='MCP',
            operation_type='MCP_CALL',
            module='regime',
            action='READ',
            mcp_tool_name='get_current_regime',
            mcp_client_id='token-a',
            request_params={},
            response_status=200,
        )
        OperationLogModel._default_manager.create(
            request_id='trace-003',
            user_id=admin_user.id,
            username=admin_user.username,
            source='MCP',
            operation_type='MCP_CALL',
            module='regime',
            action='READ',
            mcp_tool_name='get_current_regime',
            mcp_client_id='token-b',
            request_params={},
            response_status=200,
        )

        api_client.force_authenticate(user=admin_user)
        response = api_client.get('/audit/api/decision-traces/')

        assert response.status_code == 200
        traces = [item for item in response.json()['traces'] if item['request_id'] == 'trace-003']
        assert len(traces) == 2
        assert {item['mcp_client_id'] for item in traces} == {'token-a', 'token-b'}


@pytest.mark.django_db
class TestOperationLogIngest:
    """测试操作日志写入"""

    def test_ingest_without_signature(self, api_client):
        """测试无签名写入被拒绝"""
        response = api_client.post(
            '/audit/api/internal/operation-logs/',
            {
                'request_id': 'req-test-005',
                'source': 'MCP',
                'operation_type': 'MCP_CALL',
                'module': 'signal',
                'action': 'CREATE',
            },
            format='json',
        )

        assert response.status_code == 403
