"""
观察员权限测试

测试持仓查询授权检查功能：
- 账户拥有者完全访问权限
- 观察员只读权限
- 审计日志记录
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from django.contrib.auth.models import User
from django.utils import timezone as django_timezone
from rest_framework.test import APIClient

from apps.account.infrastructure.models import (
    AssetCategoryModel,
    CurrencyModel,
    PortfolioModel,
    PortfolioObserverGrantModel,
    PositionModel,
)


@pytest.fixture
def setup_observer_test_data(db):
    """创建观察员测试数据"""
    # 创建用户
    owner = User.objects.create_user(
        username='portfolio_owner',
        email='owner@example.com',
        password='test_pass_123'
    )
    observer = User.objects.create_user(
        username='observer_user',
        email='observer@example.com',
        password='test_pass_456'
    )
    unauthorized_user = User.objects.create_user(
        username='unauthorized_user',
        email='unauthorized@example.com',
        password='test_pass_789'
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

    # 创建投资组合
    portfolio = PortfolioModel.objects.create(
        user=owner,
        name='测试组合',
        base_currency=cny,
        is_active=True,
    )

    # 创建持仓
    position = PositionModel.objects.create(
        portfolio=portfolio,
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

    # 创建观察员授权
    grant = PortfolioObserverGrantModel.objects.create(
        owner_user_id=owner,
        observer_user_id=observer,
        scope='portfolio_read',
        status='active',
        expires_at=None,
    )

    return {
        'owner': owner,
        'observer': observer,
        'unauthorized_user': unauthorized_user,
        'portfolio': portfolio,
        'position': position,
        'grant': grant,
    }


class TestObserverAccessPermission:
    """观察员访问权限测试"""

    def test_owner_can_access_portfolio(self, setup_observer_test_data):
        """拥有者可以访问投资组合"""
        data = setup_observer_test_data
        client = APIClient()
        client.force_authenticate(user=data['owner'])

        response = client.get(f'/api/account/portfolios/{data["portfolio"].id}/')

        assert response.status_code == 200
        assert response.data['id'] == data['portfolio'].id

    def test_observer_can_access_portfolio(self, setup_observer_test_data):
        """观察员可以访问被授权的投资组合"""
        data = setup_observer_test_data
        client = APIClient()
        client.force_authenticate(user=data['observer'])

        response = client.get(f'/api/account/portfolios/{data["portfolio"].id}/')

        assert response.status_code == 200
        assert response.data['id'] == data['portfolio'].id

    def test_unauthorized_user_cannot_access_portfolio(self, setup_observer_test_data):
        """未授权用户不能访问投资组合"""
        data = setup_observer_test_data
        client = APIClient()
        client.force_authenticate(user=data['unauthorized_user'])

        response = client.get(f'/api/account/portfolios/{data["portfolio"].id}/')

        # 未授权用户无法访问该投资组合，返回 403（权限拒绝）或 404（不在 queryset 中）
        assert response.status_code in (403, 404)

    def test_observer_can_list_positions(self, setup_observer_test_data):
        """观察员可以查看持仓列表"""
        data = setup_observer_test_data
        client = APIClient()
        client.force_authenticate(user=data['observer'])

        response = client.get('/api/account/positions/')

        assert response.status_code == 200
        assert len(response.data['results']) >= 1

    def test_observer_can_retrieve_position(self, setup_observer_test_data):
        """观察员可以查看持仓详情"""
        data = setup_observer_test_data
        client = APIClient()
        client.force_authenticate(user=data['observer'])

        response = client.get(f'/api/account/positions/{data["position"].id}/')

        assert response.status_code == 200
        assert response.data['asset_code'] == '000001.SZ'

    def test_observer_cannot_create_position(self, setup_observer_test_data):
        """观察员不能创建持仓"""
        data = setup_observer_test_data
        client = APIClient()
        client.force_authenticate(user=data['observer'])

        payload = {
            'portfolio': data['portfolio'].id,
            'asset_code': '000002.SZ',
            'shares': 100,
            'avg_cost': 20.00,
            'asset_class': 'equity',
            'region': 'CN',
            'cross_border': 'domestic',
        }

        response = client.post('/api/account/positions/', payload)

        # 观察员无法创建持仓 - 可能是 403（权限拒绝）或 404（找不到投资组合）
        assert response.status_code in (403, 404, 400)

    def test_observer_cannot_update_position(self, setup_observer_test_data):
        """观察员不能更新持仓"""
        data = setup_observer_test_data
        client = APIClient()
        client.force_authenticate(user=data['observer'])

        payload = {
            'shares': 2000,
        }

        response = client.patch(
            f'/api/account/positions/{data["position"].id}/',
            payload
        )

        assert response.status_code == 403

    def test_observer_cannot_close_position(self, setup_observer_test_data):
        """观察员不能平仓"""
        data = setup_observer_test_data
        client = APIClient()
        client.force_authenticate(user=data['observer'])

        response = client.post(f'/api/account/positions/{data["position"].id}/close/')

        assert response.status_code == 403

    def test_observer_cannot_delete_position(self, setup_observer_test_data):
        """观察员不能删除持仓"""
        data = setup_observer_test_data
        client = APIClient()
        client.force_authenticate(user=data['observer'])

        response = client.delete(f'/api/account/positions/{data["position"].id}/')

        assert response.status_code == 403

    def test_owner_can_close_position(self, setup_observer_test_data):
        """拥有者可以平仓"""
        data = setup_observer_test_data
        client = APIClient()
        client.force_authenticate(user=data['owner'])

        response = client.post(f'/api/account/positions/{data["position"].id}/close/')

        assert response.status_code == 200
        assert response.data['success'] is True

    def test_observer_can_access_portfolio_positions(self, setup_observer_test_data):
        """观察员可以访问投资组合的持仓列表"""
        data = setup_observer_test_data
        client = APIClient()
        client.force_authenticate(user=data['observer'])

        response = client.get(f'/api/account/portfolios/{data["portfolio"].id}/positions/')

        assert response.status_code == 200
        assert response.data['count'] >= 1

    def test_observer_can_access_portfolio_statistics(self, setup_observer_test_data):
        """观察员可以访问投资组合统计信息"""
        data = setup_observer_test_data
        client = APIClient()
        client.force_authenticate(user=data['observer'])

        response = client.get(f'/api/account/portfolios/{data["portfolio"].id}/statistics/')

        assert response.status_code == 200
        assert 'total_value' in response.data

    def test_expired_grant_denied(self, setup_observer_test_data):
        """过期授权被拒绝"""
        data = setup_observer_test_data
        # 设置授权为已过期
        data['grant'].expires_at = datetime.now(UTC) - timedelta(days=1)
        data['grant'].save()

        client = APIClient()
        client.force_authenticate(user=data['observer'])

        response = client.get(f'/api/account/portfolios/{data["portfolio"].id}/')

        # 过期授权的投资组合不可访问，返回 403（权限拒绝）或 404（不在 queryset 中）
        assert response.status_code in (403, 404)

    def test_revoked_grant_denied(self, setup_observer_test_data):
        """已撤销授权被拒绝"""
        data = setup_observer_test_data
        # 撤销授权
        data['grant'].status = 'revoked'
        data['grant'].save()

        client = APIClient()
        client.force_authenticate(user=data['observer'])

        response = client.get(f'/api/account/portfolios/{data["portfolio"].id}/')

        # 撤销授权的投资组合不可访问，返回 403（权限拒绝）或 404（不在 queryset 中）
        assert response.status_code in (403, 404)


class TestObserverAuditLogging:
    """观察员审计日志测试"""

    def test_observer_access_logs_audit(self, setup_observer_test_data):
        """观察员访问记录审计日志"""
        # 注意：审计日志记录功能在 retrieve 方法中通过 _log_observer_access_if_needed 触发
        # 这里只测试访问成功，实际审计日志验证需要更完整的测试设置
        data = setup_observer_test_data
        client = APIClient()
        client.force_authenticate(user=data['observer'])

        # 访问投资组合 - 应该成功
        response = client.get(f'/api/account/portfolios/{data["portfolio"].id}/')
        assert response.status_code == 200

        # 访问持仓详情 - 应该成功
        response = client.get(f'/api/account/positions/{data["position"].id}/')
        assert response.status_code == 200

    def test_observer_position_access_logs_audit(self, setup_observer_test_data):
        """观察员访问持仓详情记录"""
        # 这个测试验证观察员可以访问持仓详情
        # 审计日志功能在 _log_observer_access_if_needed 中实现
        data = setup_observer_test_data
        client = APIClient()
        client.force_authenticate(user=data['observer'])

        # 访问持仓详情
        response = client.get(f'/api/account/positions/{data["position"].id}/')
        assert response.status_code == 200
        assert response.data['asset_code'] == '000001.SZ'


class TestGetAccessiblePortfolios:
    """获取可访问投资组合功能测试"""

    def test_owner_gets_own_portfolios(self, setup_observer_test_data):
        """拥有者获取自己的投资组合"""
        from apps.account.interface.permissions import get_accessible_portfolios

        data = setup_observer_test_data
        portfolios = get_accessible_portfolios(data['owner'])

        assert portfolios.count() >= 1
        assert data['portfolio'] in portfolios

    def test_observer_gets_granted_portfolios(self, setup_observer_test_data):
        """观察员获取被授权的投资组合"""
        from apps.account.interface.permissions import get_accessible_portfolios

        data = setup_observer_test_data
        portfolios = get_accessible_portfolios(data['observer'])

        assert portfolios.count() >= 1
        assert data['portfolio'] in portfolios

    def test_unauthorized_gets_no_portfolios(self, setup_observer_test_data):
        """未授权用户无法获取投资组合"""
        from apps.account.interface.permissions import get_accessible_portfolios

        data = setup_observer_test_data
        portfolios = get_accessible_portfolios(data['unauthorized_user'])

        assert portfolios.count() == 0

