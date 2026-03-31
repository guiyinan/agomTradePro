"""
Unit tests for ObserverAccessPermission and get_accessible_portfolios.

测试观察员访问权限：
- ObserverAccessPermission.has_permission()
- ObserverAccessPermission.has_object_permission()
- get_accessible_portfolios() 函数
"""

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIRequestFactory

from apps.account.infrastructure.models import (
    AssetCategoryModel,
    CurrencyModel,
    PortfolioModel,
    PortfolioObserverGrantModel,
    PositionModel,
)
from apps.account.interface.permissions import (
    ObserverAccessPermission,
    get_accessible_portfolios,
)


@pytest.mark.django_db
class TestObserverAccessPermission:
    """测试 ObserverAccessPermission 权限类"""

    def test_has_permission_returns_false_for_unauthenticated(self):
        """测试未认证用户返回 False 或 None"""
        factory = APIRequestFactory()
        request = factory.get('/api/account/portfolios/')
        request.user = None

        permission = ObserverAccessPermission()
        # 未认证用户应该返回 False 或 None（表示无权限）
        result = permission.has_permission(request, None)
        assert result is False or result is None

    def test_has_permission_returns_true_for_authenticated(self):
        """测试已认证用户返回 True"""
        factory = APIRequestFactory()
        user = User.objects.create_user(
            username=f"user_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        request = factory.get('/api/account/portfolios/')
        request.user = user

        permission = ObserverAccessPermission()
        assert permission.has_permission(request, None) is True

    @pytest.fixture
    def setup_portfolio_with_grant(self):
        """创建投资组合和授权的 fixture"""
        # 创建用户
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )
        unauthorized = User.objects.create_user(
            username=f"unauth_{uuid.uuid4().hex[:8]}",
            password="test_pass_789"
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

        # 创建授权
        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
        )

        return {
            'owner': owner,
            'observer': observer,
            'unauthorized': unauthorized,
            'portfolio': portfolio,
            'grant': grant,
        }

    def test_has_object_permission_owner_can_access(self, setup_portfolio_with_grant):
        """测试拥有者可以访问投资组合"""
        factory = APIRequestFactory()
        data = setup_portfolio_with_grant

        request = factory.get(f'/api/account/portfolios/{data["portfolio"].id}/')
        request.user = data['owner']

        permission = ObserverAccessPermission()
        assert permission.has_object_permission(request, None, data['portfolio']) is True

    def test_has_object_permission_observer_can_read(self, setup_portfolio_with_grant):
        """测试观察员可以读取投资组合"""
        factory = APIRequestFactory()
        data = setup_portfolio_with_grant

        request = factory.get(f'/api/account/portfolios/{data["portfolio"].id}/')
        request.user = data['observer']

        permission = ObserverAccessPermission()
        assert permission.has_object_permission(request, None, data['portfolio']) is True

    def test_has_object_permission_observer_cannot_write(self, setup_portfolio_with_grant):
        """测试观察员不能写操作"""
        factory = APIRequestFactory()
        data = setup_portfolio_with_grant

        # 测试 POST
        request = factory.post(f'/api/account/portfolios/{data["portfolio"].id}/')
        request.user = data['observer']

        permission = ObserverAccessPermission()
        assert permission.has_object_permission(request, None, data['portfolio']) is False

    def test_has_object_permission_observer_cannot_put(self, setup_portfolio_with_grant):
        """测试观察员不能 PUT"""
        factory = APIRequestFactory()
        data = setup_portfolio_with_grant

        request = factory.put(f'/api/account/portfolios/{data["portfolio"].id}/')
        request.user = data['observer']

        permission = ObserverAccessPermission()
        assert permission.has_object_permission(request, None, data['portfolio']) is False

    def test_has_object_permission_observer_cannot_delete(self, setup_portfolio_with_grant):
        """测试观察员不能 DELETE"""
        factory = APIRequestFactory()
        data = setup_portfolio_with_grant

        request = factory.delete(f'/api/account/portfolios/{data["portfolio"].id}/')
        request.user = data['observer']

        permission = ObserverAccessPermission()
        assert permission.has_object_permission(request, None, data['portfolio']) is False

    def test_has_object_permission_unauthorized_denied(self, setup_portfolio_with_grant):
        """测试未授权用户被拒绝"""
        factory = APIRequestFactory()
        data = setup_portfolio_with_grant

        request = factory.get(f'/api/account/portfolios/{data["portfolio"].id}/')
        request.user = data['unauthorized']

        permission = ObserverAccessPermission()
        assert permission.has_object_permission(request, None, data['portfolio']) is False

    def test_has_object_permission_with_expired_grant(self, setup_portfolio_with_grant):
        """测试过期授权被拒绝"""
        factory = APIRequestFactory()
        data = setup_portfolio_with_grant

        # 设置授权为过期
        data['grant'].expires_at = datetime.now(UTC) - timedelta(days=1)
        data['grant'].save()

        request = factory.get(f'/api/account/portfolios/{data["portfolio"].id}/')
        request.user = data['observer']

        permission = ObserverAccessPermission()
        assert permission.has_object_permission(request, None, data['portfolio']) is False

    def test_has_object_permission_with_revoked_grant(self, setup_portfolio_with_grant):
        """测试撤销授权被拒绝"""
        factory = APIRequestFactory()
        data = setup_portfolio_with_grant

        # 撤销授权
        data['grant'].status = 'revoked'
        data['grant'].save()

        request = factory.get(f'/api/account/portfolios/{data["portfolio"].id}/')
        request.user = data['observer']

        permission = ObserverAccessPermission()
        assert permission.has_object_permission(request, None, data['portfolio']) is False

    def test_has_object_permission_owner_can_write(self, setup_portfolio_with_grant):
        """测试拥有者可以写操作"""
        factory = APIRequestFactory()
        data = setup_portfolio_with_grant

        request = factory.put(f'/api/account/portfolios/{data["portfolio"].id}/')
        request.user = data['owner']

        permission = ObserverAccessPermission()
        assert permission.has_object_permission(request, None, data['portfolio']) is True

    @pytest.fixture
    def setup_position_with_grant(self):
        """创建持仓和授权的 fixture"""
        # 创建用户
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
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

        # 创建授权
        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
        )

        return {
            'owner': owner,
            'observer': observer,
            'portfolio': portfolio,
            'position': position,
            'grant': grant,
        }

    def test_has_object_permission_position_owner_can_access(self, setup_position_with_grant):
        """测试拥有者可以访问持仓"""
        factory = APIRequestFactory()
        data = setup_position_with_grant

        request = factory.get(f'/api/account/positions/{data["position"].id}/')
        request.user = data['owner']

        permission = ObserverAccessPermission()
        assert permission.has_object_permission(request, None, data['position']) is True

    def test_has_object_permission_position_observer_can_read(self, setup_position_with_grant):
        """测试观察员可以读取持仓"""
        factory = APIRequestFactory()
        data = setup_position_with_grant

        request = factory.get(f'/api/account/positions/{data["position"].id}/')
        request.user = data['observer']

        permission = ObserverAccessPermission()
        assert permission.has_object_permission(request, None, data['position']) is True

    def test_has_object_permission_position_observer_cannot_write(self, setup_position_with_grant):
        """测试观察员不能修改持仓"""
        factory = APIRequestFactory()
        data = setup_position_with_grant

        request = factory.put(f'/api/account/positions/{data["position"].id}/')
        request.user = data['observer']

        permission = ObserverAccessPermission()
        assert permission.has_object_permission(request, None, data['position']) is False

    def test_has_object_permission_options_and_head_allowed(self, setup_portfolio_with_grant):
        """测试 OPTIONS 和 HEAD 方法允许"""
        factory = APIRequestFactory()
        data = setup_portfolio_with_grant

        # OPTIONS
        request = factory.options(f'/api/account/portfolios/{data["portfolio"].id}/')
        request.user = data['observer']

        permission = ObserverAccessPermission()
        assert permission.has_object_permission(request, None, data['portfolio']) is True

        # HEAD
        request = factory.head(f'/api/account/portfolios/{data["portfolio"].id}/')
        request.user = data['observer']

        assert permission.has_object_permission(request, None, data['portfolio']) is True


@pytest.mark.django_db
class TestGetAccessiblePortfolios:
    """测试 get_accessible_portfolios 函数"""

    def test_owner_gets_own_portfolios(self):
        """测试拥有者获取自己的投资组合"""
        # 创建用户
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
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
        portfolio1 = PortfolioModel.objects.create(
            user=owner,
            name='组合1',
            base_currency=cny,
            is_active=True,
        )
        portfolio2 = PortfolioModel.objects.create(
            user=owner,
            name='组合2',
            base_currency=cny,
            is_active=False,
        )

        portfolios = get_accessible_portfolios(owner)

        assert portfolios.count() == 2
        assert portfolio1 in portfolios
        assert portfolio2 in portfolios

    def test_observer_gets_granted_portfolios(self):
        """测试观察员获取被授权的投资组合"""
        # 创建用户
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
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
            name='拥有者组合',
            base_currency=cny,
            is_active=True,
        )

        # 创建授权
        PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
        )

        portfolios = get_accessible_portfolios(observer)

        assert portfolios.count() == 1
        assert portfolio in portfolios

    def test_observer_with_multiple_grants(self):
        """测试观察员有多个授权"""
        # 创建用户
        owner1 = User.objects.create_user(
            username=f"owner1_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        owner2 = User.objects.create_user(
            username=f"owner2_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_789"
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
        portfolio1 = PortfolioModel.objects.create(
            user=owner1,
            name='组合1',
            base_currency=cny,
            is_active=True,
        )
        portfolio2 = PortfolioModel.objects.create(
            user=owner2,
            name='组合2',
            base_currency=cny,
            is_active=True,
        )

        # 创建授权
        PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner1,
            observer_user_id=observer,
            status='active',
        )
        PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner2,
            observer_user_id=observer,
            status='active',
        )

        portfolios = get_accessible_portfolios(observer)

        assert portfolios.count() == 2
        assert portfolio1 in portfolios
        assert portfolio2 in portfolios

    def test_observer_excludes_expired_grants(self):
        """测试排除过期授权"""
        # 创建用户
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
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
            name='拥有者组合',
            base_currency=cny,
            is_active=True,
        )

        # 创建过期授权
        PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )

        portfolios = get_accessible_portfolios(observer)

        # 观察员不应该看到过期授权的投资组合
        assert portfolios.count() == 0

    def test_observer_excludes_revoked_grants(self):
        """测试排除撤销授权"""
        # 创建用户
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
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
            name='拥有者组合',
            base_currency=cny,
            is_active=True,
        )

        # 创建撤销授权
        PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='revoked',
        )

        portfolios = get_accessible_portfolios(observer)

        # 观察员不应该看到撤销授权的投资组合
        assert portfolios.count() == 0

    def test_user_with_no_portfolios(self):
        """测试没有投资组合的用户"""
        user = User.objects.create_user(
            username=f"user_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )

        portfolios = get_accessible_portfolios(user)

        assert portfolios.count() == 0

    def test_owner_and_observer_combined(self):
        """测试既是拥有者又是观察员"""
        # 创建用户
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        other_owner = User.objects.create_user(
            username=f"other_owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
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

        # 创建自己的投资组合
        own_portfolio = PortfolioModel.objects.create(
            user=owner,
            name='自己的组合',
            base_currency=cny,
            is_active=True,
        )

        # 创建他人的投资组合
        other_portfolio = PortfolioModel.objects.create(
            user=other_owner,
            name='他人的组合',
            base_currency=cny,
            is_active=True,
        )

        # 授权观察他人的投资组合
        PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=other_owner,
            observer_user_id=owner,
            status='active',
        )

        portfolios = get_accessible_portfolios(owner)

        # 应该能看到两个投资组合
        assert portfolios.count() == 2
        assert own_portfolio in portfolios
        assert other_portfolio in portfolios

    def test_duplicate_portfolios_deduplicated(self):
        """测试重复投资组合去重"""
        # 创建用户
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
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
            name='自己的组合',
            base_currency=cny,
            is_active=True,
        )

        portfolios = get_accessible_portfolios(owner)

        # 即使有多个来源，也应该去重
        # 这里只有一个投资组合，所以 count 应该是 1
        assert portfolios.count() == 1
        assert list(portfolios).count(portfolio) == 1

