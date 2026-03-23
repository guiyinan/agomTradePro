"""
Unit tests for Operation Audit Log permissions.
"""

import uuid

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIRequestFactory

from apps.audit.interface.permissions import (
    HasInternalAuditSignature,
    IsAuditAdmin,
    IsSelfOrAuditAdmin,
    OperationLogReadPermission,
)


@pytest.mark.django_db
class TestIsAuditAdmin:
    """测试审计管理员权限"""

    def test_superuser_has_permission(self):
        """测试超级用户有权限"""
        factory = APIRequestFactory()
        request = factory.get('/')
        request.user = User.objects.create_user(
            username=f"admin_{uuid.uuid4().hex[:8]}",
            is_superuser=True,
        )

        permission = IsAuditAdmin()
        assert permission.has_permission(request, None) is True

    def test_admin_role_has_permission(self):
        """测试 admin 角色有权限"""
        factory = APIRequestFactory()
        request = factory.get('/')
        user = User.objects.create_user(username=f"admin_user_{uuid.uuid4().hex[:8]}")
        user.rbac_role = 'admin'
        request.user = user

        permission = IsAuditAdmin()
        assert permission.has_permission(request, None) is True

    def test_owner_role_has_permission(self):
        """测试 owner 角色有权限"""
        factory = APIRequestFactory()
        request = factory.get('/')
        user = User.objects.create_user(username=f"owner_user_{uuid.uuid4().hex[:8]}")
        user.rbac_role = 'owner'
        request.user = user

        permission = IsAuditAdmin()
        assert permission.has_permission(request, None) is True

    def test_regular_user_no_permission(self):
        """测试普通用户无权限"""
        factory = APIRequestFactory()
        request = factory.get('/')
        user = User.objects.create_user(username=f"regular_user_{uuid.uuid4().hex[:8]}")
        user.rbac_role = 'analyst'
        request.user = user

        permission = IsAuditAdmin()
        assert permission.has_permission(request, None) is False

    def test_unauthenticated_no_permission(self):
        """测试未认证用户无权限"""
        factory = APIRequestFactory()
        request = factory.get('/')
        request.user = None

        permission = IsAuditAdmin()
        assert permission.has_permission(request, None) is False


@pytest.mark.django_db
class TestOperationLogReadPermission:
    """测试操作日志读取权限"""

    def test_admin_can_read_all(self):
        """测试管理员可读取所有日志"""
        factory = APIRequestFactory()
        request = factory.get('/')
        user = User.objects.create_user(username=f"admin_user_{uuid.uuid4().hex[:8]}")
        user.rbac_role = 'admin'
        request.user = user

        permission = OperationLogReadPermission()
        # 对于管理员，has_object_permission 应该返回 True
        assert permission.has_permission(request, None) is True


@pytest.mark.django_db
class TestIsSelfOrAuditAdmin:
    """测试本人或管理员权限"""

    def test_admin_can_access_all(self):
        """测试管理员可访问所有资源"""
        factory = APIRequestFactory()
        request = factory.get('/')
        admin_user = User.objects.create_user(username=f"admin_user_{uuid.uuid4().hex[:8]}")
        admin_user.rbac_role = 'admin'
        request.user = admin_user

        permission = IsSelfOrAuditAdmin()

        # 模拟对象
        class MockLog:
            user_id = 999  # 其他用户

        assert permission.has_object_permission(request, None, MockLog()) is True

    def test_user_can_access_own(self):
        """测试用户可访问自己的资源"""
        factory = APIRequestFactory()
        request = factory.get('/')
        user = User.objects.create_user(username=f"regular_user_{uuid.uuid4().hex[:8]}", id=123)
        request.user = user

        permission = IsSelfOrAuditAdmin()

        class MockLog:
            user_id = 123  # 同一用户

        assert permission.has_object_permission(request, None, MockLog()) is True

    def test_user_cannot_access_others(self):
        """测试用户不能访问他人资源"""
        factory = APIRequestFactory()
        request = factory.get('/')
        user = User.objects.create_user(username=f"regular_user_{uuid.uuid4().hex[:8]}", id=123)
        user.rbac_role = 'analyst'
        request.user = user

        permission = IsSelfOrAuditAdmin()

        class MockLog:
            user_id = 999  # 其他用户

        assert permission.has_object_permission(request, None, MockLog()) is False


class TestHasInternalAuditSignature:
    """测试内部审计签名权限"""

    def test_missing_signature_denied(self):
        """测试缺少签名被拒绝"""
        factory = APIRequestFactory()
        request = factory.post('/')
        request.headers = {}

        permission = HasInternalAuditSignature()
        assert permission.has_permission(request, None) is False

    def test_missing_timestamp_denied(self):
        """测试缺少时间戳被拒绝"""
        factory = APIRequestFactory()
        request = factory.post('/')
        request.headers = {'X-Audit-Signature': 'abc123'}

        permission = HasInternalAuditSignature()
        assert permission.has_permission(request, None) is False
