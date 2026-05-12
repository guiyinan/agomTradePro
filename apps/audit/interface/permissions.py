"""
Permissions for Audit API.
"""

import hashlib
import hmac
import json
import time

from django.conf import settings
from rest_framework import permissions


class IsAuditAdmin(permissions.BasePermission):
    """
    审计管理员权限

    仅允许 admin 或 owner 角色访问审计管理功能。
    """
    message = "需要审计管理员权限"

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # 检查是否为超级用户
        if request.user.is_superuser:
            return True

        # 检查 RBAC 角色
        user_role = getattr(request.user, 'rbac_role', '').lower()
        return user_role in ('admin', 'owner')


class OperationLogReadPermission(permissions.BasePermission):
    """
    操作日志读取权限

    - 管理员可读取全量日志
    - 普通用户仅可读取本人日志
    """
    message = "无权查看此日志"

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        # 管理员可查看所有日志
        if IsAuditAdmin().has_permission(request, view):
            return True

        # 普通用户仅可查看本人日志
        user_id = getattr(obj, 'user_id', None)
        return user_id == request.user.id


class HasInternalAuditSignature(permissions.BasePermission):
    """
    内部审计写入权限

    用于验证 MCP/SDK 调用的内部写入请求。
    验证 X-Audit-Signature 头和 X-Audit-Timestamp 时间戳。
    """
    message = "无效的审计签名"

    # 签名有效期（秒）
    SIGNATURE_TTL = 300  # 5 分钟

    def has_permission(self, request, view):
        signature = request.headers.get('X-Audit-Signature', '')
        timestamp = request.headers.get('X-Audit-Timestamp', '')

        if not signature or not timestamp:
            return False

        try:
            # 检查时间戳是否在有效期内
            ts = int(timestamp)
            current_time = int(time.time())
            if abs(current_time - ts) > self.SIGNATURE_TTL:
                return False

            # 获取密钥
            secret_key = getattr(settings, 'AUDIT_INTERNAL_SECRET_KEY', '')
            if not secret_key:
                # 如果没有配置密钥，在开发环境允许通过
                return settings.DEBUG

            # 计算签名
            # 签名内容: timestamp + request body (JSON 排序后)
            # 必须与 SDK 端的签名算法一致: json.dumps(data, sort_keys=True)
            body_raw = request.body.decode('utf-8') if request.body else '{}'
            try:
                # 解析并重新排序 JSON，确保与服务端签名一致
                data = json.loads(body_raw)
                body = json.dumps(data, sort_keys=True, ensure_ascii=False)
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = body_raw

            sign_content = f"{timestamp}:{body}"

            expected_signature = hmac.new(
                secret_key.encode('utf-8'),
                sign_content.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            # 使用恒定时间比较防止时序攻击
            return hmac.compare_digest(signature, expected_signature)

        except (ValueError, TypeError):
            return False


class IsSelfOrAuditAdmin(permissions.BasePermission):
    """
    本人或审计管理员权限

    - 管理员可访问所有资源
    - 普通用户仅可访问自己的资源
    """
    message = "无权访问此资源"

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        # 管理员可访问所有
        if IsAuditAdmin().has_permission(request, view):
            return True

        # 检查是否为本人
        obj_user_id = None
        if hasattr(obj, 'user_id'):
            obj_user_id = obj.user_id
        elif isinstance(obj, dict):
            obj_user_id = obj.get('user_id')

        return obj_user_id == request.user.id
