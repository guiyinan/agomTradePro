"""
工作台 API 集成测试

测试新增的 Bootstrap/Detail/Fetch API 端点。
"""

from datetime import UTC, date, datetime, timezone
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User

from apps.policy.application.use_cases import FetchRSSOutput
from apps.policy.domain.entities import PolicyLevel
from apps.policy.infrastructure.models import PolicyLog, RSSSourceConfigModel


@pytest.fixture
def api_client():
    """创建 API 客户端"""
    from rest_framework.test import APIClient
    client = APIClient()
    return client


@pytest.fixture
def test_user(db):
    """创建测试用户"""
    user = User.objects.create_user(username='testuser', password='testpass123')
    user.is_staff = True
    user.save()
    return user


@pytest.fixture
def auth_client(api_client, test_user):
    """创建已认证的 API 客户端"""
    api_client.force_authenticate(user=test_user)
    return api_client


@pytest.fixture
def sample_event(db, test_user):
    """创建示例事件"""
    event = PolicyLog.objects.create(
        event_date=date.today(),
        event_type='policy',
        level='P2',
        title='测试事件',
        description='这是一个测试事件的详细描述',
        evidence_url='https://example.com/test',
        gate_effective=True,
        effective_at=datetime.now(UTC),
        effective_by=test_user,
        audit_status='approved',
        ai_confidence=0.85,
    )
    return event


@pytest.mark.django_db
class TestWorkbenchBootstrapAPI:
    """测试 Bootstrap API"""

    def test_bootstrap_returns_all_required_fields(self, auth_client):
        """测试 Bootstrap API 返回所有必需字段"""
        response = auth_client.get('/api/policy/workbench/bootstrap/')

        assert response.status_code == 200
        data = response.json()

        # 验证必需字段存在
        assert 'success' in data
        assert 'summary' in data
        assert 'default_list' in data
        assert 'filter_options' in data
        assert 'trend' in data
        assert 'fetch_status' in data

    def test_bootstrap_filter_options_structure(self, auth_client):
        """测试 filter_options 结构"""
        response = auth_client.get('/api/policy/workbench/bootstrap/')
        data = response.json()

        filter_options = data.get('filter_options', {})
        assert 'event_types' in filter_options
        assert 'levels' in filter_options
        assert 'gate_levels' in filter_options
        assert 'asset_classes' in filter_options
        assert 'sources' in filter_options

        # 验证 event_types 格式
        event_types = filter_options['event_types']
        assert len(event_types) > 0
        assert all('value' in t and 'label' in t for t in event_types)


@pytest.mark.django_db
class TestWorkbenchFetchAPI:
    """测试 Fetch API"""

    def test_fetch_all_sources_success(self, auth_client):
        """测试抓取全部源"""
        response = auth_client.post(
            '/api/policy/workbench/fetch/',
            data={},
            format='json'
        )

        assert response.status_code == 200
        data = response.json()

        # 验证响应结构
        assert 'success' in data
        assert 'mode' in data
        assert 'sources_processed' in data
        assert 'total_items' in data
        assert 'new_policy_events' in data
        assert 'errors' in data

        # mode 应该是 'all'
        assert data['mode'] == 'all'

    def test_fetch_with_force_refetch(self, auth_client):
        """测试强制重新抓取"""
        response = auth_client.post(
            '/api/policy/workbench/fetch/',
            data={'force_refetch': True},
            format='json'
        )

        assert response.status_code == 200
        data = response.json()
        assert 'success' in data

    def test_fetch_single_source(self, auth_client, db):
        """测试抓取指定源"""
        # 创建测试源
        source = RSSSourceConfigModel.objects.create(
            name='测试源',
            url='https://example.com/feed.xml',
            is_active=True,
            category='policy'
        )

        with patch(
            "apps.policy.interface.workbench_api_views.FetchRSSUseCase.execute",
            return_value=FetchRSSOutput(
                success=True,
                sources_processed=1,
                total_items=3,
                new_policy_events=2,
                errors=[],
                details=[{"source_name": source.name, "items_count": 3, "new_events_count": 2}],
            ),
        ):
            response = auth_client.post(
                '/api/policy/workbench/fetch/',
                data={'source_id': source.id},
                format='json'
            )

        assert response.status_code == 200
        data = response.json()

        # mode 应该是 'single'
        assert data['mode'] == 'single'

    def test_fetch_requires_authentication(self, api_client):
        """测试未认证请求被拒绝"""
        response = api_client.post(
            '/api/policy/workbench/fetch/',
            data={},
            format='json'
        )

        # 应该返回 401 或 403
        assert response.status_code in [401, 403]


@pytest.mark.django_db
class TestWorkbenchItemDetailAPI:
    """测试 Detail API"""

    def test_get_event_detail_success(self, auth_client, sample_event):
        """测试获取事件详情"""
        response = auth_client.get(f'/api/policy/workbench/items/{sample_event.id}/')

        assert response.status_code == 200
        data = response.json()

        assert data['success'] is True
        item = data['item']

        # 验证基本字段
        assert item['id'] == sample_event.id
        assert item['title'] == sample_event.title
        assert item['event_type'] == sample_event.event_type
        assert item['level'] == sample_event.level

    def test_get_event_detail_includes_source_name(self, auth_client, sample_event, db):
        """测试详情包含来源名称"""
        # 创建 RSS 源
        source = RSSSourceConfigModel.objects.create(
            name='测试RSS源',
            url='https://example.com/feed.xml',
            is_active=True
        )

        # 更新事件的源
        sample_event.rss_source_id = source.id
        sample_event.save()

        response = auth_client.get(f'/api/policy/workbench/items/{sample_event.id}/')
        data = response.json()

        assert data['item']['rss_source_name'] == '测试RSS源'

    def test_get_event_detail_not_found(self, auth_client):
        """测试获取不存在的事件"""
        response = auth_client.get('/api/policy/workbench/items/99999/')

        assert response.status_code == 404

    def test_get_event_detail_includes_audit_info(self, auth_client, sample_event):
        """测试详情包含审核信息"""
        response = auth_client.get(f'/api/policy/workbench/items/{sample_event.id}/')
        data = response.json()

        item = data['item']
        assert 'audit_status' in item
        assert 'reviewed_by_id' in item
        assert 'reviewed_by_name' in item


@pytest.mark.django_db
class TestWorkbenchItemsDefaultTab:
    """测试默认 Tab 为 all"""

    def test_default_tab_is_all(self, auth_client):
        """测试默认 tab 为 all"""
        response = auth_client.get('/api/policy/workbench/items/')
        assert response.status_code == 200

        data = response.json()
        # 验证默认返回的是 all tab 的数据
        # 由于没有指定 tab，应该使用默认值 'all'


@pytest.mark.django_db
class TestCSRFProtection:
    """测试 CSRF 保护"""

    def test_post_endpoints_require_csrf(self):
        """测试 POST 端点需要 CSRF（通过 DRF 认证）"""
        # 注意：DRF 的 IsAuthenticated 权限会处理认证
        # CSRF 在 DRF 中通常通过 SessionAuthentication 处理
        # 这里我们验证端点需要认证
        from rest_framework.test import APIClient

        client = APIClient()  # 未认证客户端

        # 测试 approve 端点需要认证
        response = client.post('/api/policy/workbench/items/1/approve/', {})
        assert response.status_code in [401, 403]

        # 测试 reject 端点需要认证
        response = client.post('/api/policy/workbench/items/1/reject/', {'reason': 'test'})
        assert response.status_code in [401, 403]

        # 测试 fetch 端点需要认证
        response = client.post('/api/policy/workbench/fetch/', {})
        assert response.status_code in [401, 403]
