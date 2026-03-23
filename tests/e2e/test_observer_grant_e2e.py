"""
E2E tests for Observer Grant flow.

端到端测试观察员授权流程：
- A 创建授权成功，B 可只读查看 A 持仓
- B 尝试交易/修改被 403 拒绝
- A 撤销后，B 立即失去访问权限
- 授权过期后自动失效
"""

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from django.contrib.auth.models import User
from django.test import Client
from rest_framework.test import APIClient

from apps.account.infrastructure.models import (
    AssetCategoryModel,
    CurrencyModel,
    PortfolioModel,
    PortfolioObserverGrantModel,
    PositionModel,
)


@pytest.fixture
def setup_e2e_data(db):
    """创建 E2E 测试数据"""
    # 创建用户 A（拥有者）
    user_a = User.objects.create_user(
        username=f"user_a_{uuid.uuid4().hex[:8]}",
        password='test_pass_123',
        email='user_a@example.com'
    )

    # 创建用户 B（观察员）
    user_b = User.objects.create_user(
        username=f"user_b_{uuid.uuid4().hex[:8]}",
        password='test_pass_456',
        email='user_b@example.com'
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

    # 创建资产分类
    equity_category, _ = AssetCategoryModel.objects.get_or_create(
        code='equity',
        defaults={
            'name': '股票',
            'level': 1,
            'path': '股票',
        }
    )

    # 创建 A 的投资组合
    portfolio_a = PortfolioModel.objects.create(
        user=user_a,
        name='用户A的组合',
        base_currency=cny,
        is_active=True,
    )

    # 创建持仓
    position_a = PositionModel.objects.create(
        portfolio=portfolio_a,
        asset_code='000001.SZ',
        category=equity_category,
        currency=cny,
        asset_class='equity',
        region='CN',
        cross_border='domestic',
        shares=1000,
        avg_cost=10.50,
        current_price=12.00,
        market_value=12000,
        unrealized_pnl=1500,
        unrealized_pnl_pct=14.29,
        source='manual',
        is_closed=False,
    )

    return {
        'user_a': user_a,
        'user_b': user_b,
        'portfolio_a': portfolio_a,
        'position_a': position_a,
        'cny': cny,
        'equity_category': equity_category,
    }


@pytest.mark.django_db
class TestObserverGrantE2E:
    """端到端测试观察员授权流程"""

    def test_scenario_a_creates_grant_b_can_read(self, setup_e2e_data):
        """
        场景：A 创建授权，B 可以只读查看 A 的持仓
        """
        data = setup_e2e_data
        api_client = APIClient()

        # 步骤 1：A 登录并创建授权
        api_client.force_authenticate(user=data['user_a'])

        grant_payload = {
            'observer_user_id': data['user_b'].id,
        }

        grant_response = api_client.post('/account/api/observer-grants/', grant_payload)

        assert grant_response.status_code == 201
        grant_id = grant_response.data['data']['id']
        assert grant_response.data['data']['status'] == 'active'

        # 步骤 2：B 登录并查看 A 的投资组合
        api_client.force_authenticate(user=data['user_b'])

        portfolio_response = api_client.get(f'/account/api/portfolios/{data["portfolio_a"].id}/')

        assert portfolio_response.status_code == 200
        assert portfolio_response.data['name'] == '用户A的组合'

        # 步骤 3：B 查看持仓列表
        positions_response = api_client.get(f'/account/api/portfolios/{data["portfolio_a"].id}/positions/')

        assert positions_response.status_code == 200
        assert positions_response.data['count'] == 1

        # 步骤 4：B 查看持仓详情
        position_response = api_client.get(f'/account/api/positions/{data["position_a"].id}/')

        assert position_response.status_code == 200
        assert position_response.data['asset_code'] == '000001.SZ'

        # 步骤 5：B 查看统计信息
        stats_response = api_client.get(f'/account/api/portfolios/{data["portfolio_a"].id}/statistics/')

        assert stats_response.status_code == 200
        assert 'total_value' in stats_response.data

    def test_scenario_b_tries_write_operations_denied(self, setup_e2e_data):
        """
        场景：B 尝试写操作被 403 拒绝
        """
        data = setup_e2e_data
        api_client = APIClient()

        # 前置条件：创建授权
        PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['user_a'],
            observer_user_id=data['user_b'],
            status='active',
        )

        # B 登录
        api_client.force_authenticate(user=data['user_b'])

        # 尝试创建持仓
        create_payload = {
            'portfolio': data['portfolio_a'].id,
            'asset_code': '000002.SZ',
            'shares': 100,
            'avg_cost': 20.00,
        }

        create_response = api_client.post('/account/api/positions/', create_payload)
        assert create_response.status_code == 403

        # 尝试更新持仓
        update_payload = {
            'shares': 2000,
        }

        update_response = api_client.patch(
            f'/account/api/positions/{data["position_a"].id}/',
            update_payload
        )
        assert update_response.status_code == 403

        # 尝试平仓
        close_response = api_client.post(f'/account/api/positions/{data["position_a"].id}/close/')
        assert close_response.status_code == 403

        # 尝试删除持仓
        delete_response = api_client.delete(f'/account/api/positions/{data["position_a"].id}/')
        assert delete_response.status_code == 403

        # 尝试修改投资组合
        portfolio_update_payload = {
            'name': '修改后的名称',
        }

        portfolio_update_response = api_client.put(
            f'/account/api/portfolios/{data["portfolio_a"].id}/',
            portfolio_update_payload
        )
        assert portfolio_update_response.status_code == 403

    def test_scenario_a_revokes_b_loses_access(self, setup_e2e_data):
        """
        场景：A 撤销授权，B 立即失去访问权限
        """
        data = setup_e2e_data
        api_client = APIClient()

        # 前置条件：创建授权
        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['user_a'],
            observer_user_id=data['user_b'],
            status='active',
        )

        # 验证 B 可以访问
        api_client.force_authenticate(user=data['user_b'])
        before_response = api_client.get(f'/account/api/portfolios/{data["portfolio_a"].id}/')
        assert before_response.status_code == 200

        # A 撤销授权
        api_client.force_authenticate(user=data['user_a'])
        revoke_response = api_client.delete(f'/account/api/observer-grants/{grant.id}/')
        assert revoke_response.status_code == 200
        assert revoke_response.data['data']['status'] == 'revoked'

        # B 尝试访问
        api_client.force_authenticate(user=data['user_b'])
        after_response = api_client.get(f'/account/api/portfolios/{data["portfolio_a"].id}/')
        assert after_response.status_code == 403

    def test_scenario_grant_expires_b_loses_access(self, setup_e2e_data):
        """
        场景：授权过期后，B 失去访问权限
        """
        data = setup_e2e_data
        api_client = APIClient()

        # 创建短期授权（已过期）
        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['user_a'],
            observer_user_id=data['user_b'],
            status='active',
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )

        # B 尝试访问
        api_client.force_authenticate(user=data['user_b'])
        response = api_client.get(f'/account/api/portfolios/{data["portfolio_a"].id}/')
        assert response.status_code == 403

    def test_scenario_grant_near_expiration_still_works(self, setup_e2e_data):
        """
        场景：授权即将过期但未过期，B 仍可访问
        """
        data = setup_e2e_data
        api_client = APIClient()

        # 创建即将过期的授权（1分钟后过期）
        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['user_a'],
            observer_user_id=data['user_b'],
            status='active',
            expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )

        # B 可以访问
        api_client.force_authenticate(user=data['user_b'])
        response = api_client.get(f'/account/api/portfolios/{data["portfolio_a"].id}/')
        assert response.status_code == 200

    def test_scenario_a_creates_grant_with_expiration(self, setup_e2e_data):
        """
        场景：A 创建带过期时间的授权
        """
        data = setup_e2e_data
        api_client = APIClient()

        # A 创建 30 天有效的授权
        api_client.force_authenticate(user=data['user_a'])

        expires_at = datetime.now(UTC) + timedelta(days=30)

        grant_payload = {
            'observer_user_id': data['user_b'].id,
            'expires_at': expires_at.isoformat(),
        }

        grant_response = api_client.post('/account/api/observer-grants/', grant_payload)

        assert grant_response.status_code == 201
        assert grant_response.data['data']['expires_at'] is not None

        # B 可以访问
        api_client.force_authenticate(user=data['user_b'])
        portfolio_response = api_client.get(f'/account/api/portfolios/{data["portfolio_a"].id}/')
        assert portfolio_response.status_code == 200

    def test_scenario_b_queries_grants_as_observer(self, setup_e2e_data):
        """
        场景：B 查询自己的观察员授权列表
        """
        data = setup_e2e_data
        api_client = APIClient()

        # A 创建授权
        PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['user_a'],
            observer_user_id=data['user_b'],
            status='active',
        )

        # B 查询作为观察员的授权
        api_client.force_authenticate(user=data['user_b'])
        grants_response = api_client.get('/account/api/observer-grants/?as_observer=1')

        assert grants_response.status_code == 200
        assert grants_response.data['count'] == 1
        assert grants_response.data['results'][0]['owner_username'] == data['user_a'].username

    def test_scenario_a_queries_own_grants(self, setup_e2e_data):
        """
        场景：A 查询自己创建的授权列表
        """
        data = setup_e2e_data
        api_client = APIClient()

        # A 创建授权
        PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=data['user_a'],
            observer_user_id=data['user_b'],
            status='active',
        )

        # A 查询自己创建的授权
        api_client.force_authenticate(user=data['user_a'])
        grants_response = api_client.get('/account/api/observer-grants/')

        assert grants_response.status_code == 200
        assert grants_response.data['count'] == 1
        assert grants_response.data['results'][0]['observer_username'] == data['user_b'].username

    def test_scenario_full_lifecycle(self, setup_e2e_data):
        """
        场景：完整的授权生命周期
        1. A 创建授权
        2. B 可以访问
        3. A 更新过期时间
        4. B 仍可访问
        5. A 撤销授权
        6. B 失去访问权限
        """
        data = setup_e2e_data
        api_client = APIClient()

        # 1. A 创建授权
        api_client.force_authenticate(user=data['user_a'])
        create_response = api_client.post('/account/api/observer-grants/', {
            'username': data['user_b'].username,
        })
        assert create_response.status_code == 201
        grant_id = create_response.data['data']['id']

        # 2. B 可以访问
        api_client.force_authenticate(user=data['user_b'])
        access_response = api_client.get(f'/account/api/portfolios/{data["portfolio_a"].id}/')
        assert access_response.status_code == 200

        # 3. A 更新过期时间
        api_client.force_authenticate(user=data['user_a'])
        new_expires = datetime.now(UTC) + timedelta(days=60)
        update_response = api_client.put(
            f'/account/api/observer-grants/{grant_id}/',
            {'expires_at': new_expires.isoformat()}
        )
        assert update_response.status_code == 200

        # 4. B 仍可访问
        api_client.force_authenticate(user=data['user_b'])
        access_response2 = api_client.get(f'/account/api/portfolios/{data["portfolio_a"].id}/')
        assert access_response2.status_code == 200

        # 5. A 撤销授权
        api_client.force_authenticate(user=data['user_a'])
        revoke_response = api_client.delete(f'/account/api/observer-grants/{grant_id}/')
        assert revoke_response.status_code == 200

        # 6. B 失去访问权限
        api_client.force_authenticate(user=data['user_b'])
        access_response3 = api_client.get(f'/account/api/portfolios/{data["portfolio_a"].id}/')
        assert access_response3.status_code == 403


@pytest.mark.django_db
class TestObserverGrantWebE2E:
    """端到端测试观察员授权 Web 页面"""

    @pytest.fixture(autouse=True)
    def _override_cache_and_throttle(self, settings):
        settings.CACHES = {
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "observer-grant-e2e",
            }
        }
        settings.REST_FRAMEWORK = {
            **getattr(settings, "REST_FRAMEWORK", {}),
            "DEFAULT_THROTTLE_CLASSES": [],
            "DEFAULT_THROTTLE_RATES": {},
        }

    def test_collaboration_page_renders(self, setup_e2e_data):
        """测试协作页面渲染"""
        data = setup_e2e_data
        client = Client()
        client.force_login(data['user_a'])

        response = client.get('/account/collaboration/')

        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert '观察员' in content or '协作' in content

    def test_observer_portal_renders(self, setup_e2e_data):
        """测试观察员门户页面渲染"""
        data = setup_e2e_data
        client = Client()
        client.force_login(data['user_b'])

        response = client.get('/account/observer/')

        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert '观察员' in content or '观察' in content


@pytest.mark.django_db
class TestObserverGrantEdgeCases:
    """测试边界情况"""

    def test_scenario_self_grant_prevented(self, setup_e2e_data):
        """场景：A 不能授权给自己"""
        data = setup_e2e_data
        api_client = APIClient()

        api_client.force_authenticate(user=data['user_a'])

        response = api_client.post('/account/api/observer-grants/', {
            'observer_user_id': data['user_a'].id,
        })

        assert response.status_code == 400
        assert '不能授权给自己' in str(response.data)

    def test_scenario_duplicate_grant_prevented(self, setup_e2e_data):
        """场景：防止重复授权"""
        data = setup_e2e_data
        api_client = APIClient()

        api_client.force_authenticate(user=data['user_a'])

        # 创建第一个授权
        first_response = api_client.post('/account/api/observer-grants/', {
            'observer_user_id': data['user_b'].id,
        })
        assert first_response.status_code == 201

        # 尝试创建第二个授权
        second_response = api_client.post('/account/api/observer-grants/', {
            'observer_user_id': data['user_b'].id,
        })
        assert second_response.status_code == 400
        assert '该用户已被授权' in str(second_response.data)

    def test_scenario_revoked_then_reauthorized(self, setup_e2e_data):
        """场景：撤销后重新授权"""
        data = setup_e2e_data
        api_client = APIClient()

        # 创建并撤销授权
        api_client.force_authenticate(user=data['user_a'])
        create_response = api_client.post('/account/api/observer-grants/', {
            'observer_user_id': data['user_b'].id,
        })
        grant_id = create_response.data['data']['id']

        revoke_response = api_client.delete(f'/account/api/observer-grants/{grant_id}/')
        assert revoke_response.status_code == 200

        # 重新授权应该成功
        reauth_response = api_client.post('/account/api/observer-grants/', {
            'observer_user_id': data['user_b'].id,
        })
        assert reauth_response.status_code == 201

    def test_scenario_max_ten_grants(self, setup_e2e_data):
        """场景：最多 10 个授权限制"""
        api_client = APIClient()

        # 创建拥有者
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password='test_pass_123'
        )

        # 创建 10 个观察员
        observers = []
        for i in range(10):
            observer = User.objects.create_user(
                username=f"observer_{i}_{uuid.uuid4().hex[:8]}",
                password='test_pass_456'
            )
            observers.append(observer)

        api_client.force_authenticate(user=owner)

        # 创建 10 个授权
        for observer in observers:
            response = api_client.post('/account/api/observer-grants/', {
                'observer_user_id': observer.id,
            })
            assert response.status_code == 201

        # 第 11 个应该失败
        new_observer = User.objects.create_user(
            username=f"new_observer_{uuid.uuid4().hex[:8]}",
            password='test_pass_789'
        )

        response = api_client.post('/account/api/observer-grants/', {
            'observer_user_id': new_observer.id,
        })
        assert response.status_code == 400
        assert '达到观察员数量上限' in str(response.data)
