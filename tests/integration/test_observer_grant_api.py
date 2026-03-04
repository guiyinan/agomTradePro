"""
Integration tests for Observer Grant API.

测试观察员授权 API：
- POST /account/api/observer-grants/ - 创建授权
- GET /account/api/observer-grants/ - 列表查询
- DELETE /account/api/observer-grants/{id}/ - 撤销授权
- 权限隔离测试（A 只能管理自己的授权）
- 数量限制测试（最多 10 个）
"""

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.account.infrastructure.models import (
    PortfolioObserverGrantModel,
    PortfolioModel,
    CurrencyModel,
)


@pytest.fixture
def api_client():
    """创建 API 测试客户端"""
    return APIClient()


@pytest.fixture
def setup_users_and_portfolio(db):
    """创建测试用户和投资组合"""
    # 创建用户
    owner = User.objects.create_user(
        username=f"owner_{uuid.uuid4().hex[:8]}",
        password="test_pass_123",
        email="owner@example.com"
    )
    observer = User.objects.create_user(
        username=f"observer_{uuid.uuid4().hex[:8]}",
        password="test_pass_456",
        email="observer@example.com"
    )
    other_user = User.objects.create_user(
        username=f"other_{uuid.uuid4().hex[:8]}",
        password="test_pass_789",
        email="other@example.com"
    )

    # 创建币种
    cny, _ = CurrencyModel.objects.get_or_create(
        code='CNY',
        defaults={
            'name': '人民币',
            'symbol': '¥',
            'is_base': True,
        }
    )

    # 创建投资组合
    portfolio = PortfolioModel.objects.create(
        user=owner,
        name='测试组合',
        base_currency=cny,
        is_active=True,
    )

    return {
        'owner': owner,
        'observer': observer,
        'other_user': other_user,
        'portfolio': portfolio,
    }


@pytest.mark.django_db
class TestObserverGrantCreateAPI:
    """测试创建观察员授权 API"""

    def test_create_grant_with_observer_user_id(self, api_client, setup_users_and_portfolio):
        """测试使用 observer_user_id 创建授权"""
        data = setup_users_and_portfolio

        api_client.force_authenticate(user=data['owner'])

        payload = {
            'observer_user_id': data['observer'].id,
        }

        response = api_client.post('/account/api/observer-grants/', payload)

        assert response.status_code == 201
        assert response.data['success'] is True
        assert 'id' in response.data['data']

        # 验证数据库中的记录
        grant_id = response.data['data']['id']
        grant = PortfolioObserverGrantModel._default_manager.get(id=grant_id)
        assert grant.owner_user_id == data['owner']
        assert grant.observer_user_id == data['observer']

    def test_create_grant_with_username(self, api_client, setup_users_and_portfolio):
        """测试使用 username 创建授权"""
        data = setup_users_and_portfolio

        api_client.force_authenticate(user=data['owner'])

        payload = {
            'username': data['observer'].username,
        }

        response = api_client.post('/account/api/observer-grants/', payload)

        assert response.status_code == 201
        assert response.data['data']['observer_user_id'] == data['observer'].id

    def test_create_grant_with_expiration(self, api_client, setup_users_and_portfolio):
        """测试创建带过期时间的授权"""
        data = setup_users_and_portfolio

        api_client.force_authenticate(user=data['owner'])

        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        payload = {
            'observer_user_id': data['observer'].id,
            'expires_at': expires_at.isoformat(),
        }

        response = api_client.post('/account/api/observer-grants/', payload)

        assert response.status_code == 201
        # 验证过期时间（容差1秒）
        response_expires = datetime.fromisoformat(response.data['data']['expires_at'].replace('Z', '+00:00'))
        assert abs((response_expires - expires_at).total_seconds()) < 1

    def test_create_grant_requires_authentication(self, api_client, setup_users_and_portfolio):
        """测试创建授权需要认证"""
        data = setup_users_and_portfolio

        payload = {
            'observer_user_id': data['observer'].id,
        }

        response = api_client.post('/account/api/observer-grants/', payload)

        assert response.status_code == 401 or response.status_code == 403

    def test_create_grant_prevents_self_grant(self, api_client, setup_users_and_portfolio):
        """测试不能授权给自己"""
        data = setup_users_and_portfolio

        api_client.force_authenticate(user=data['owner'])

        payload = {
            'observer_user_id': data['owner'].id,
        }

        response = api_client.post('/account/api/observer-grants/', payload)

        assert response.status_code == 400
        assert '不能授权给自己' in str(response.data)

    def test_create_grant_prevents_duplicate_active(self, api_client, setup_users_and_portfolio):
        """测试防止重复的 active 授权"""
        data = setup_users_and_portfolio

        api_client.force_authenticate(user=data['owner'])

        # 创建第一个授权
        PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['observer'],
            status='active',
        )

        # 尝试创建第二个授权
        payload = {
            'observer_user_id': data['observer'].id,
        }

        response = api_client.post('/account/api/observer-grants/', payload)

        assert response.status_code == 400
        assert '该用户已被授权' in str(response.data)

    def test_create_grant_invalid_observer_user_id(self, api_client, setup_users_and_portfolio):
        """测试无效的观察员用户 ID"""
        data = setup_users_and_portfolio

        api_client.force_authenticate(user=data['owner'])

        payload = {
            'observer_user_id': 99999,
        }

        response = api_client.post('/account/api/observer-grants/', payload)

        assert response.status_code == 400
        assert '不存在' in str(response.data)

    def test_create_grant_invalid_username(self, api_client, setup_users_and_portfolio):
        """测试无效的用户名"""
        data = setup_users_and_portfolio

        api_client.force_authenticate(user=data['owner'])

        payload = {
            'username': 'nonexistent_user',
        }

        response = api_client.post('/account/api/observer-grants/', payload)

        assert response.status_code == 400
        # 错误信息可能包含 "不存在" 或 "does not exist"
        error_str = str(response.data).lower()
        assert '不存在' in error_str or 'not exist' in error_str

    def test_create_grant_past_expiration(self, api_client, setup_users_and_portfolio):
        """测试过期时间不能是过去时间"""
        data = setup_users_and_portfolio

        api_client.force_authenticate(user=data['owner'])

        past_time = datetime.now(timezone.utc) - timedelta(days=1)
        payload = {
            'observer_user_id': data['observer'].id,
            'expires_at': past_time.isoformat(),
        }

        response = api_client.post('/account/api/observer-grants/', payload)

        assert response.status_code == 400
        assert '过期时间必须大于当前时间' in str(response.data)

    def test_create_grant_missing_observer(self, api_client, setup_users_and_portfolio):
        """测试缺少观察员参数"""
        data = setup_users_and_portfolio

        api_client.force_authenticate(user=data['owner'])

        payload = {}

        response = api_client.post('/account/api/observer-grants/', payload)

        assert response.status_code == 400


@pytest.mark.django_db
class TestObserverGrantListAPI:
    """测试查询观察员授权列表 API"""

    def test_list_grants_as_owner(self, api_client, setup_users_and_portfolio):
        """测试作为拥有者查询授权列表"""
        data = setup_users_and_portfolio

        # 创建授权
        grant1 = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['observer'],
            status='active',
        )
        grant2 = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['other_user'],
            status='revoked',
        )

        api_client.force_authenticate(user=data['owner'])

        response = api_client.get('/account/api/observer-grants/')

        assert response.status_code == 200
        assert response.data['count'] == 2

    def test_list_grants_as_observer(self, api_client, setup_users_and_portfolio):
        """测试作为观察员查询授权列表"""
        data = setup_users_and_portfolio

        # 创建授权
        PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['observer'],
            status='active',
        )

        api_client.force_authenticate(user=data['observer'])

        response = api_client.get('/account/api/observer-grants/?as_observer=1')

        assert response.status_code == 200
        assert response.data['count'] == 1

    def test_list_grants_with_status_filter(self, api_client, setup_users_and_portfolio):
        """测试按状态过滤"""
        data = setup_users_and_portfolio

        # 创建授权
        PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['observer'],
            status='active',
        )
        PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['other_user'],
            status='revoked',
        )

        api_client.force_authenticate(user=data['owner'])

        # 只查询 active 状态
        response = api_client.get('/account/api/observer-grants/?status=active')

        assert response.status_code == 200
        assert response.data['count'] == 1
        assert response.data['results'][0]['status'] == 'active'

    def test_list_grants_permission_isolation(self, api_client, setup_users_and_portfolio):
        """测试权限隔离：用户只能看到自己的授权"""
        data = setup_users_and_portfolio

        # 创建授权
        PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['observer'],
            status='active',
        )

        # 另一个用户查询
        api_client.force_authenticate(user=data['other_user'])

        response = api_client.get('/account/api/observer-grants/')

        assert response.status_code == 200
        assert response.data['count'] == 0

    def test_list_grants_requires_authentication(self, api_client):
        """测试查询列表需要认证"""
        response = api_client.get('/account/api/observer-grants/')

        assert response.status_code == 401 or response.status_code == 403


@pytest.mark.django_db
class TestObserverGrantDetailAPI:
    """测试观察员授权详情 API"""

    def test_get_grant_detail(self, api_client, setup_users_and_portfolio):
        """测试获取授权详情"""
        data = setup_users_and_portfolio

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['observer'],
            status='active',
        )

        api_client.force_authenticate(user=data['owner'])

        response = api_client.get(f'/account/api/observer-grants/{grant.id}/')

        assert response.status_code == 200
        assert response.data['id'] == str(grant.id)
        assert response.data['owner_username'] == data['owner'].username
        assert response.data['observer_username'] == data['observer'].username

    def test_get_grant_detail_as_observer(self, api_client, setup_users_and_portfolio):
        """测试观察员可以查看授权详情"""
        data = setup_users_and_portfolio

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['observer'],
            status='active',
        )

        api_client.force_authenticate(user=data['observer'])

        response = api_client.get(f'/account/api/observer-grants/{grant.id}/?as_observer=1')

        assert response.status_code == 200

    def test_get_grant_detail_unauthorized(self, api_client, setup_users_and_portfolio):
        """测试未授权用户无法查看授权详情"""
        data = setup_users_and_portfolio

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['observer'],
            status='active',
        )

        api_client.force_authenticate(user=data['other_user'])

        response = api_client.get(f'/account/api/observer-grants/{grant.id}/')

        assert response.status_code == 404  # DRF 返回 404 因为不在查询集中


@pytest.mark.django_db
class TestObserverGrantDeleteAPI:
    """测试撤销观察员授权 API"""

    def test_delete_grant_as_owner(self, api_client, setup_users_and_portfolio):
        """测试拥有者可以撤销授权"""
        data = setup_users_and_portfolio

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['observer'],
            status='active',
        )

        api_client.force_authenticate(user=data['owner'])

        response = api_client.delete(f'/account/api/observer-grants/{grant.id}/')

        assert response.status_code == 200
        assert response.data['success'] is True
        assert response.data['message'] == '授权已撤销'

        # 验证数据库状态
        grant.refresh_from_db()
        assert grant.status == 'revoked'
        assert grant.revoked_by == data['owner']

    def test_delete_grant_prevents_unauthorized(self, api_client, setup_users_and_portfolio):
        """测试未授权用户无法撤销"""
        data = setup_users_and_portfolio

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['observer'],
            status='active',
        )

        api_client.force_authenticate(user=data['other_user'])

        response = api_client.delete(f'/account/api/observer-grants/{grant.id}/')

        assert response.status_code == 403

    def test_delete_grant_observer_cannot_revoke(self, api_client, setup_users_and_portfolio):
        """测试观察员不能撤销授权"""
        data = setup_users_and_portfolio

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['observer'],
            status='active',
        )

        api_client.force_authenticate(user=data['observer'])

        response = api_client.delete(f'/account/api/observer-grants/{grant.id}/')

        assert response.status_code == 403

    def test_delete_already_revoked_grant(self, api_client, setup_users_and_portfolio):
        """测试撤销已撤销的授权"""
        data = setup_users_and_portfolio

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['observer'],
            status='revoked',
            revoked_at=datetime.now(timezone.utc),
            revoked_by=data['owner'],
        )

        api_client.force_authenticate(user=data['owner'])

        response = api_client.delete(f'/account/api/observer-grants/{grant.id}/')

        assert response.status_code == 400
        assert '无法撤销' in str(response.data)

    def test_delete_expired_grant_fails(self, api_client, setup_users_and_portfolio):
        """测试撤销过期授权失败"""
        data = setup_users_and_portfolio

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['observer'],
            status='expired',
        )

        api_client.force_authenticate(user=data['owner'])

        response = api_client.delete(f'/account/api/observer-grants/{grant.id}/')

        assert response.status_code == 400


@pytest.mark.django_db
class TestObserverGrantCountLimit:
    """测试观察员数量限制"""

    def test_max_ten_active_grants(self, api_client):
        """测试最多 10 个活跃授权"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )

        # 创建 10 个观察员
        observers = []
        for i in range(10):
            observer = User.objects.create_user(
                username=f"observer_{i}_{uuid.uuid4().hex[:8]}",
                password="test_pass_456"
            )
            observers.append(observer)
            PortfolioObserverGrantModel._default_manager.create(
                owner_user_id=owner,
                observer_user_id=observer,
                status='active',
            )

        # 创建第 11 个观察员
        new_observer = User.objects.create_user(
            username=f"new_observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_789"
        )

        api_client.force_authenticate(user=owner)

        # 使用 username 而不是 ID
        payload = {
            'username': new_observer.username,
        }

        response = api_client.post('/account/api/observer-grants/', payload)

        assert response.status_code == 400
        assert '达到观察员数量上限' in str(response.data)

    def test_revoked_grant_does_not_count(self, api_client):
        """测试撤销的授权不计入数量限制"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )

        # 创建 10 个观察员
        observers = []
        grants = []
        for i in range(10):
            observer = User.objects.create_user(
                username=f"observer_{i}_{uuid.uuid4().hex[:8]}",
                password="test_pass_456"
            )
            observers.append(observer)
            grant = PortfolioObserverGrantModel._default_manager.create(
                owner_user_id=owner,
                observer_user_id=observer,
                status='active',
            )
            grants.append(grant)

        # 撤销第一个授权
        grants[0].status = 'revoked'
        grants[0].save()

        # 现在可以创建新的授权
        new_observer = User.objects.create_user(
            username=f"new_observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_789"
        )

        api_client.force_authenticate(user=owner)

        # 使用 username 而不是 ID，因为序列化器的 PrimaryKeyRelatedField 需要 User 对象
        payload = {
            'username': new_observer.username,
        }

        response = api_client.post('/account/api/observer-grants/', payload)

        # 打印错误信息以便调试
        if response.status_code != 201:
            print(f"Error: {response.data}")

        assert response.status_code == 201


@pytest.mark.django_db
class TestObserverGrantUpdateAPI:
    """测试更新观察员授权 API"""

    def test_update_grant_expiration(self, api_client, setup_users_and_portfolio):
        """测试更新授权过期时间"""
        data = setup_users_and_portfolio

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['observer'],
            status='active',
            expires_at=None,
        )

        api_client.force_authenticate(user=data['owner'])

        new_expires = datetime.now(timezone.utc) + timedelta(days=60)
        payload = {
            'expires_at': new_expires.isoformat(),
        }

        response = api_client.put(f'/account/api/observer-grants/{grant.id}/', payload)

        assert response.status_code == 200

        grant.refresh_from_db()
        # 验证过期时间（容差1秒）
        assert abs((grant.expires_at - new_expires).total_seconds()) < 1

    def test_update_grant_past_expiration_fails(self, api_client, setup_users_and_portfolio):
        """测试更新为过去时间失败"""
        data = setup_users_and_portfolio

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['observer'],
            status='active',
            expires_at=None,
        )

        api_client.force_authenticate(user=data['owner'])

        past_time = datetime.now(timezone.utc) - timedelta(days=1)
        payload = {
            'expires_at': past_time.isoformat(),
        }

        response = api_client.put(f'/account/api/observer-grants/{grant.id}/', payload)

        assert response.status_code == 400


@pytest.mark.django_db
class TestObserverGrantSerializerFields:
    """测试序列化器字段"""

    def test_grant_serializer_includes_display_fields(self, api_client, setup_users_and_portfolio):
        """测试序列化器包含显示字段"""
        data = setup_users_and_portfolio

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['owner'],
            observer_user_id=data['observer'],
            status='active',
        )

        api_client.force_authenticate(user=data['owner'])

        response = api_client.get(f'/account/api/observer-grants/{grant.id}/')

        assert response.status_code == 200
        assert 'owner_username' in response.data
        assert 'observer_username' in response.data
        assert 'scope_display' in response.data
        assert 'status_display' in response.data
        assert 'is_valid' in response.data
        assert response.data['owner_username'] == data['owner'].username
        assert response.data['observer_username'] == data['observer'].username
        assert response.data['is_valid'] is True
