"""
Unit tests for PortfolioObserverGrantModel.

测试授权模型的功能：
- 字段验证
- clean() 方法（不能授权给自己、唯一 active 授权）
- is_valid() 方法
- revoke() 方法
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.account.infrastructure.models import PortfolioObserverGrantModel


@pytest.mark.django_db
class TestObserverGrantModelFields:
    """测试观察员授权模型字段"""

    def test_create_grant_with_required_fields(self):
        """测试创建授权时必需字段"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            scope='portfolio_read',
            status='active',
        )

        assert grant.id is not None
        assert grant.owner_user_id == owner
        assert grant.observer_user_id == observer
        assert grant.scope == 'portfolio_read'
        assert grant.status == 'active'
        assert grant.created_at is not None
        assert grant.expires_at is None

    def test_create_grant_with_expiration(self):
        """测试创建带过期时间的授权"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )
        expires_at = datetime.now(UTC) + timedelta(days=30)

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            scope='portfolio_read',
            status='active',
            expires_at=expires_at,
        )

        assert grant.expires_at is not None
        # 比较时间（容差1秒）
        assert abs((grant.expires_at - expires_at).total_seconds()) < 1

    def test_grant_id_is_uuid(self):
        """测试授权ID是UUID格式"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
        )

        # 验证ID是UUID格式
        try:
            uuid.UUID(str(grant.id))
        except ValueError:
            pytest.fail("Grant ID is not a valid UUID")

    def test_grant_str_representation(self):
        """测试授权的字符串表示"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
        )

        str_repr = str(grant)
        assert owner.username in str_repr
        assert observer.username in str_repr
        assert "激活" in str_repr or "active" in str_repr.lower()


@pytest.mark.django_db
class TestObserverGrantModelClean:
    """测试观察员授权模型的 clean() 方法"""

    def test_clean_allows_valid_grant(self):
        """测试 clean() 允许有效的授权"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        grant = PortfolioObserverGrantModel(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
        )

        # 不应该抛出异常
        grant.clean()

    def test_clean_prevents_self_grant(self):
        """测试 clean() 防止授权给自己"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )

        grant = PortfolioObserverGrantModel(
            owner_user_id=owner,
            observer_user_id=owner,
            status='active',
        )

        with pytest.raises(ValidationError) as exc_info:
            grant.clean()

        errors = exc_info.value.message_dict
        assert "observer_user_id" in errors
        assert "不能授权给自己" in str(errors["observer_user_id"])

    def test_clean_prevents_duplicate_active_grant(self):
        """测试 clean() 防止重复的 active 授权"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        # 创建第一个授权
        PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
        )

        # 尝试创建第二个 active 授权
        grant2 = PortfolioObserverGrantModel(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
        )

        with pytest.raises(ValidationError) as exc_info:
            grant2.clean()

        errors = exc_info.value.message_dict
        assert "该用户已被授权为观察员" in str(errors)

    def test_clean_allows_revoked_then_active_grant(self):
        """测试 clean() 允许撤销后重新授权"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        # 创建并撤销第一个授权
        grant1 = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
        )
        grant1.status = 'revoked'
        grant1.save()

        # 创建新的 active 授权应该成功
        grant2 = PortfolioObserverGrantModel(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
        )

        # 不应该抛出异常
        grant2.clean()

    def test_clean_allows_non_active_duplicate(self):
        """测试 clean() 允许非 active 状态的重复授权"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        # 创建第一个授权（ revoked 状态）
        PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='revoked',
        )

        # 创建第二个 active 授权应该成功
        grant2 = PortfolioObserverGrantModel(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
        )

        # 不应该抛出异常
        grant2.clean()


@pytest.mark.django_db
class TestObserverGrantModelIsValid:
    """测试观察员授权模型的 is_valid() 方法"""

    def test_is_valid_returns_true_for_active_grant(self):
        """测试 active 状态的授权返回 True"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
        )

        assert grant.is_valid() is True

    def test_is_valid_returns_true_for_active_with_future_expiration(self):
        """测试未过期的 active 授权返回 True"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )

        assert grant.is_valid() is True

    def test_is_valid_returns_false_for_expired_grant(self):
        """测试过期的授权返回 False"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )

        assert grant.is_valid() is False

    def test_is_valid_returns_false_for_revoked_grant(self):
        """测试撤销的授权返回 False"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='revoked',
        )

        assert grant.is_valid() is False

    def test_is_valid_returns_true_for_expired_status_grant(self):
        """测试 expired 状态的授权返回 False"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='expired',
        )

        assert grant.is_valid() is False

    def test_is_valid_returns_true_for_null_expiration(self):
        """测试无过期时间的授权返回 True（如果状态是 active）"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
            expires_at=None,
        )

        assert grant.is_valid() is True

    def test_is_valid_handles_expiration_at_boundary(self):
        """测试过期时间边界情况"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        # 刚好过期的授权
        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
            expires_at=datetime.now(UTC) - timedelta(milliseconds=100),
        )

        assert grant.is_valid() is False


@pytest.mark.django_db
class TestObserverGrantModelRevoke:
    """测试观察员授权模型的 revoke() 方法"""

    def test_revoke_changes_status_to_revoked(self):
        """测试 revoke() 将状态改为 revoked"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
        )

        grant.revoke(owner)

        # 刷新实例
        grant.refresh_from_db()
        assert grant.status == 'revoked'

    def test_revoke_sets_revoked_at_timestamp(self):
        """测试 revoke() 设置撤销时间"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        before_revoke = datetime.now(UTC)

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
        )

        grant.revoke(owner)

        # 刷新实例
        grant.refresh_from_db()
        assert grant.revoked_at is not None
        assert grant.revoked_at >= before_revoke

    def test_revoke_sets_revoked_by_user(self):
        """测试 revoke() 设置撤销者"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )
        admin = User.objects.create_user(
            username=f"admin_{uuid.uuid4().hex[:8]}",
            password="test_pass_789"
        )

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
        )

        grant.revoke(admin)

        # 刷新实例
        grant.refresh_from_db()
        assert grant.revoked_by == admin

    def test_revoke_on_already_revoked_grant(self):
        """测试撤销已撤销的授权"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='revoked',
            revoked_at=datetime.now(UTC),
            revoked_by=owner,
        )

        # 再次撤销应该成功（幂等操作）
        grant.revoke(owner)

        # 刷新实例
        grant.refresh_from_db()
        assert grant.status == 'revoked'

    def test_revoke_makes_grant_invalid(self):
        """测试撤销后的授权无效"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        grant = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
        )

        assert grant.is_valid() is True

        grant.revoke(owner)

        # 刷新实例
        grant.refresh_from_db()
        assert grant.is_valid() is False


@pytest.mark.django_db
class TestObserverGrantModelConstraints:
    """测试观察员授权模型的数据库约束"""

    def test_unique_active_grant_constraint(self):
        """测试数据库层面的唯一 active 授权约束"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer = User.objects.create_user(
            username=f"observer_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )

        # 创建第一个 active 授权
        PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer,
            status='active',
        )

        # 尝试创建第二个 active 授权应该违反数据库约束
        with pytest.raises(IntegrityError):
            PortfolioObserverGrantModel._default_manager.create(
                owner_user_id=owner,
                observer_user_id=observer,
                status='active',
            )

    def test_constraint_allows_different_observers(self):
        """测试约束允许同一个 owner 授权不同的观察员"""
        owner = User.objects.create_user(
            username=f"owner_{uuid.uuid4().hex[:8]}",
            password="test_pass_123"
        )
        observer1 = User.objects.create_user(
            username=f"observer1_{uuid.uuid4().hex[:8]}",
            password="test_pass_456"
        )
        observer2 = User.objects.create_user(
            username=f"observer2_{uuid.uuid4().hex[:8]}",
            password="test_pass_789"
        )

        # 同一个 owner 可以授权不同的观察员
        grant1 = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer1,
            status='active',
        )
        grant2 = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner,
            observer_user_id=observer2,
            status='active',
        )

        assert grant1.id != grant2.id

    def test_constraint_allows_different_owners(self):
        """测试约束允许不同 owner 授权同一个观察员"""
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

        # 不同 owner 可以授权同一个观察员
        grant1 = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner1,
            observer_user_id=observer,
            status='active',
        )
        grant2 = PortfolioObserverGrantModel._default_manager.create(
            owner_user_id=owner2,
            observer_user_id=observer,
            status='active',
        )

        assert grant1.id != grant2.id
