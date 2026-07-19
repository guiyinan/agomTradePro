"""
身份、账户资料与访问授权 ORM 模型

包含用户账户配置（扩展 Django User）、MCP/SDK 访问 Token、
投资组合观察员授权。
"""

import base64
import hashlib
import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings  # type: ignore[import-untyped]
from django.contrib.auth.models import User  # type: ignore[import-untyped]
from django.core.exceptions import ValidationError  # type: ignore[import-untyped]
from django.db import models  # type: ignore[import-untyped]

from apps.account.application.rbac import ROLE_CHOICES

__all__ = [
    "AccountProfileModel",
    "PortfolioObserverGrantModel",
    "UserAccessTokenModel",
]


def _build_app_fernet() -> Fernet:
    secret = getattr(settings, "AGOMTRADEPRO_ENCRYPTION_KEY", "") or getattr(
        settings, "SECRET_KEY", ""
    )
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


# 账户与组合模型


class AccountProfileModel(models.Model):  # type: ignore[misc]
    """
    用户账户配置表

    扩展 Django User 模型，存储投资偏好和初始资金。

    ⭐ 重构说明（2026-01-04）：
    - 删除了 real_account 和 simulated_account 外键
    - 用户投资组合统一由 SimulatedAccountModel 管理
    - 通过 user.investment_accounts 查询所有投资组合
    """

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="account_profile", verbose_name="用户"
    )

    display_name = models.CharField(max_length=100, verbose_name="显示名称")

    initial_capital = models.DecimalField(
        max_digits=20, decimal_places=2, default=Decimal("1000000.00"), verbose_name="初始资金"
    )

    RISK_TOLERANCE_CHOICES = [
        ("conservative", "保守型"),
        ("moderate", "稳健型"),
        ("aggressive", "激进型"),
    ]
    risk_tolerance = models.CharField(
        max_length=20, choices=RISK_TOLERANCE_CHOICES, default="moderate", verbose_name="风险偏好"
    )

    rbac_role = models.CharField(
        max_length=32,
        choices=ROLE_CHOICES,
        default="owner",
        verbose_name="RBAC角色",
        help_text="系统统一角色（与 MCP 对齐）",
    )

    mcp_enabled = models.BooleanField(
        default=True,
        verbose_name="允许 MCP/SDK 访问",
        help_text="关闭后，该用户所有 MCP/SDK Token 将立即失效",
    )

    # 波动率目标配置
    target_volatility = models.FloatField(
        default=0.15, verbose_name="目标波动率", help_text="年化波动率目标，如0.15表示15%"
    )

    volatility_tolerance = models.FloatField(
        default=0.2,
        verbose_name="波动率容忍度",
        help_text="超过目标波动率多少比例触发降仓，如0.2表示20%",
    )

    max_volatility_reduction = models.FloatField(
        default=0.5,
        verbose_name="最大降仓幅度",
        help_text="波动率超标时最大降仓比例，如0.5表示最多降50%",
    )

    # 用户协议和审批相关字段
    user_agreement_accepted = models.BooleanField(default=False, verbose_name="用户协议已接受")
    risk_warning_acknowledged = models.BooleanField(default=False, verbose_name="风险提示已确认")
    agreement_accepted_at = models.DateTimeField(null=True, blank=True, verbose_name="协议接受时间")
    agreement_ip_address = models.GenericIPAddressField(
        null=True, blank=True, verbose_name="协议接受IP"
    )

    # 用户审批状态（⭐新增）
    APPROVAL_STATUS_CHOICES = [
        ("pending", "待审批"),
        ("approved", "已批准"),
        ("rejected", "已拒绝"),
        ("auto_approved", "自动批准"),
    ]
    approval_status = models.CharField(
        max_length=20, choices=APPROVAL_STATUS_CHOICES, default="pending", verbose_name="审批状态"
    )
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="批准时间")
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_users",
        verbose_name="审批人",
    )
    rejection_reason = models.TextField(blank=True, verbose_name="拒绝原因")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "account_profile"
        verbose_name = "账户配置"
        verbose_name_plural = "账户配置"

    def __str__(self) -> str:
        return f"{self.user.username} - {self.display_name}"


class UserAccessTokenModel(models.Model):  # type: ignore[misc]
    """支持多 Token 的 MCP/SDK 访问凭证。"""

    ACCESS_LEVEL_READ_ONLY = "read_only"
    ACCESS_LEVEL_READ_WRITE = "read_write"
    ACCESS_LEVEL_CHOICES = [
        (ACCESS_LEVEL_READ_ONLY, "只读"),
        (ACCESS_LEVEL_READ_WRITE, "读写"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="access_tokens",
        verbose_name="所属用户",
    )
    name = models.CharField(
        max_length=100,
        default="default",
        verbose_name="Token名称",
        help_text="例如：Claude Desktop / Local SDK / VPS Script",
    )
    key = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name="Token Key",
    )
    key_encrypted = models.TextField(
        blank=True,
        verbose_name="Token密文",
        help_text="用于按系统配置决定是否允许明文查看",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_access_tokens",
        verbose_name="创建人",
    )
    access_level = models.CharField(
        max_length=20,
        choices=ACCESS_LEVEL_CHOICES,
        default=ACCESS_LEVEL_READ_WRITE,
        verbose_name="访问级别",
        help_text="只读 Token 仅允许 GET/HEAD/OPTIONS；读写 Token 仍需通过账号角色鉴权。",
    )
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="最后使用时间",
    )
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="撤销时间",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否有效",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "user_access_token"
        verbose_name = "用户访问Token"
        verbose_name_plural = "用户访问Token"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                condition=models.Q(is_active=True),
                name="uniq_active_access_token_name_per_user",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["key"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.username}:{self.name}"

    @property
    def preview(self) -> str:
        if not self.key:
            return "-"
        return f"{self.key[:8]}...{self.key[-6:]}"

    @classmethod
    def generate_key(cls) -> str:
        return secrets.token_hex(20)

    @classmethod
    def create_token(
        cls,
        *,
        user: User,
        name: str,
        created_by: User | None = None,
        access_level: str = ACCESS_LEVEL_READ_WRITE,
    ) -> tuple["UserAccessTokenModel", str]:
        raw_name = (name or "").strip() or f"token-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        raw_key = cls.generate_key()
        token = cls._default_manager.create(
            user=user,
            name=raw_name,
            key=raw_key,
            key_encrypted=_build_app_fernet().encrypt(raw_key.encode("utf-8")).decode("utf-8"),
            created_by=created_by,
            access_level=access_level,
        )
        return token, raw_key

    @property
    def allows_write(self) -> bool:
        return bool(self.access_level == self.ACCESS_LEVEL_READ_WRITE)

    def reveal_key(self) -> str:
        if not self.key_encrypted:
            return ""
        try:
            return str(
                _build_app_fernet().decrypt(self.key_encrypted.encode("utf-8")).decode("utf-8")
            )
        except (InvalidToken, ValueError, TypeError):
            return ""

    def revoke(self) -> None:
        self.is_active = False
        self.revoked_at = datetime.now(UTC)
        self.save(update_fields=["is_active", "revoked_at", "updated_at"])


# ============================================================
# Portfolio Observer Grant Model
# ============================================================


class PortfolioObserverGrantModel(models.Model):  # type: ignore[misc]
    """
    投资组合观察员授权表

    记录用户 A 授权用户 B 查看其投资组合的记录。
    支持授权范围、状态管理和过期时间。
    """

    # 主键
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, verbose_name="授权ID")

    # 授权关系
    owner_user_id = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="granted_observers", verbose_name="账户拥有者"
    )
    observer_user_id = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="observed_portfolios", verbose_name="观察员"
    )

    # 授权范围（首版固定为 portfolio_read）
    SCOPE_CHOICES = [
        ("portfolio_read", "查看投资组合"),
    ]
    scope = models.CharField(
        max_length=50, choices=SCOPE_CHOICES, default="portfolio_read", verbose_name="授权范围"
    )

    # 状态枚举
    STATUS_CHOICES = [
        ("active", "激活"),
        ("revoked", "已撤销"),
        ("expired", "已过期"),
    ]
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="active", verbose_name="状态"
    )

    # 过期时间（可选）
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="过期时间")

    # 审计字段
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_observer_grants",
        verbose_name="创建者",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    revoked_at = models.DateTimeField(null=True, blank=True, verbose_name="撤销时间")
    revoked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_observer_grants",
        verbose_name="撤销者",
    )

    class Meta:
        db_table = "portfolio_observer_grant"
        verbose_name = "投资组合观察员授权"
        verbose_name_plural = "投资组合观察员授权"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner_user_id", "observer_user_id"], name="idx_owner_observer"),
            models.Index(fields=["observer_user_id", "status"], name="idx_observer_status"),
            models.Index(fields=["status", "expires_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["owner_user_id", "observer_user_id"],
                condition=models.Q(status="active"),
                name="unique_active_grant",
            )
        ]

    def __str__(self) -> str:
        return f"{self.owner_user_id.username} -> {self.observer_user_id.username} ({self.get_status_display()})"

    def clean(self) -> None:
        """验证约束条件"""
        # 不能授权给自己
        if self.owner_user_id == self.observer_user_id:
            raise ValidationError({"observer_user_id": "不能授权给自己"})

        # 检查是否已存在 active 授权
        if self.status == "active" and not getattr(
            self, "_skip_duplicate_active_validation", False
        ):
            existing = PortfolioObserverGrantModel.objects.filter(
                owner_user_id=self.owner_user_id,
                observer_user_id=self.observer_user_id,
                status="active",
            ).exclude(id=self.id)
            if existing.exists():
                raise ValidationError(
                    {
                        "owner_user_id": "该用户已被授权为观察员",
                        "observer_user_id": "该用户已被授权为观察员",
                    }
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self._skip_duplicate_active_validation = True
        try:
            self.full_clean(validate_constraints=False)
        finally:
            self._skip_duplicate_active_validation = False
        super().save(*args, **kwargs)

    def is_valid(self) -> bool:
        """检查授权是否有效"""
        if self.status != "active":
            return False
        if self.expires_at and self.expires_at < datetime.now(UTC):
            return False
        return True

    def is_expired(self) -> bool:
        """检查授权是否已过期"""
        if self.expires_at is None:
            return False
        return bool(self.expires_at < datetime.now(UTC))

    def revoke(self, revoked_by_user: Any) -> None:
        """撤销授权"""
        self.status = "revoked"
        self.revoked_at = datetime.now(UTC)
        self.revoked_by = revoked_by_user
        self.save()
