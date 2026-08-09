"""Administrative user, access-token, system-settings, and backup operations."""

import json
import logging
from collections.abc import Mapping
from typing import Any

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.account.infrastructure.backup_delivery_projection import get_backup_delivery_settings
from apps.account.infrastructure.backup_service import (
    generate_backup_archive,
    hash_download_nonce,
    validate_download_token,
)
from apps.account.infrastructure.models import (
    AccountProfileModel,
    UserAccessTokenModel,
)
from apps.account.infrastructure.system_settings_projection import SystemSettingsProjection
from apps.config_center.application.public import (
    consume_backup_download_token,
    get_runtime_market_visual_tokens,
    get_system_governance_settings,
    update_system_governance_settings,
)

logger = logging.getLogger(__name__)


class AccountInterfaceAdministrationRepositoryMixin:
    """Persist administrative access and system-management workflows."""

    _ACCOUNT_RUNTIME_FIELDS = (
        "require_user_approval",
        "auto_approve_first_admin",
        "default_mcp_enabled",
        "allow_token_plaintext_view",
        "user_agreement_content",
        "risk_warning_content",
        "notes",
    )

    @classmethod
    def _account_settings_projection(
        cls,
        base_settings: SystemSettingsProjection | None = None,
    ) -> tuple[SystemSettingsProjection, dict[str, Any]]:
        """Return the compatibility model overlaid with the typed account profile."""

        compatibility_shape = base_settings or SystemSettingsProjection()
        system_settings = get_backup_delivery_settings(base_settings=compatibility_shape)
        governance = get_system_governance_settings()
        for field_name in cls._ACCOUNT_RUNTIME_FIELDS:
            if field_name in governance:
                setattr(system_settings, field_name, governance[field_name])
        return system_settings, governance

    def create_access_token(
        self,
        *,
        target_user_id: int,
        created_by_user_id: int,
        token_name: str,
        access_level: str,
    ) -> tuple[UserAccessTokenModel, str]:
        """Create a token for the target user."""

        target_user = User._default_manager.select_related("account_profile").get(id=target_user_id)
        created_by = User._default_manager.get(id=created_by_user_id)
        token, raw_key = UserAccessTokenModel.create_token(
            user=target_user,
            name=token_name,
            created_by=created_by,
            access_level=access_level,
        )
        return token, raw_key

    def revoke_access_token_for_user(self, *, target_user_id: int, token_id: int) -> str:
        """Revoke one active token owned by the target user."""

        token = UserAccessTokenModel._default_manager.get(
            id=token_id,
            user_id=target_user_id,
            is_active=True,
        )
        token_name = token.name
        token.revoke()
        return token_name

    def revoke_all_access_tokens_for_user(self, *, target_user_id: int) -> dict[str, Any]:
        """Revoke all active tokens for the target user."""

        target_user = User._default_manager.get(id=target_user_id)
        active_tokens = list(
            UserAccessTokenModel._default_manager.filter(user=target_user, is_active=True)
        )
        for token in active_tokens:
            token.revoke()
        return {
            "username": target_user.username,
            "deleted_count": len(active_tokens),
        }

    def revoke_access_token_by_id(self, token_id: int) -> dict[str, Any]:
        """Revoke a token by id."""

        token = UserAccessTokenModel._default_manager.select_related("user").get(
            id=token_id,
            is_active=True,
        )
        username = token.user.username
        token_name = token.name
        token.revoke()
        return {"username": username, "token_name": token_name}

    def build_user_management_context(
        self,
        *,
        status_filter: str,
        search_query: str,
    ) -> dict[str, Any]:
        """Build the admin user management context."""

        profiles = AccountProfileModel._default_manager.select_related("user", "approved_by").all()
        if status_filter:
            profiles = profiles.filter(approval_status=status_filter)
        if search_query:
            profiles = profiles.filter(
                Q(user__username__icontains=search_query)
                | Q(user__email__icontains=search_query)
                | Q(display_name__icontains=search_query)
            )
        profiles = profiles.order_by("-created_at")

        system_settings, _governance = self._account_settings_projection()
        return {
            "profiles": profiles,
            "system_settings": system_settings,
            "status_filter": status_filter,
            "search_query": search_query,
            "total_count": profiles.count(),
            "pending_count": profiles.filter(approval_status="pending").count(),
            "approved_count": profiles.filter(
                approval_status__in=["approved", "auto_approved"]
            ).count(),
            "rejected_count": profiles.filter(approval_status="rejected").count(),
        }

    def build_token_management_context(
        self,
        *,
        search_query: str,
        only_without_token: bool,
    ) -> dict[str, Any]:
        """Build the admin token management context."""

        users = (
            User._default_manager.select_related("account_profile").all().order_by("-date_joined")
        )
        if search_query:
            users = users.filter(
                Q(username__icontains=search_query) | Q(email__icontains=search_query)
            )

        tokens = (
            UserAccessTokenModel._default_manager.select_related("created_by")
            .filter(is_active=True)
            .order_by("-created_at")
        )
        token_map: dict[int, list[UserAccessTokenModel]] = {}
        for token in tokens:
            token_map.setdefault(token.user_id, []).append(token)

        rows = []
        for user in users:
            user_tokens = token_map.get(user.id, [])
            if only_without_token and user_tokens:
                continue
            rows.append(
                {
                    "user": user,
                    "profile": getattr(user, "account_profile", None),
                    "tokens": user_tokens,
                    "has_token": bool(user_tokens),
                    "token_count": len(user_tokens),
                    "read_only_token_count": sum(
                        1
                        for token in user_tokens
                        if token.access_level == UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY
                    ),
                }
            )

        system_settings, _governance = self._account_settings_projection()
        return {
            "rows": rows,
            "search_query": search_query,
            "only_without_token": only_without_token,
            "total_users": len(rows),
            "with_token_count": sum(1 for row in rows if row["has_token"]),
            "without_token_count": sum(1 for row in rows if not row["has_token"]),
            "total_token_count": sum(row["token_count"] for row in rows),
            "system_settings": system_settings,
        }

    def toggle_user_mcp(self, target_user_id: int) -> dict[str, Any]:
        """Toggle MCP access for a user."""

        target_user = User._default_manager.select_related("account_profile").get(id=target_user_id)
        profile = target_user.account_profile
        profile.mcp_enabled = not profile.mcp_enabled
        profile.save(update_fields=["mcp_enabled", "updated_at"])

        if not profile.mcp_enabled:
            for token in UserAccessTokenModel._default_manager.filter(
                user=target_user,
                is_active=True,
            ):
                token.revoke()

        return {
            "username": target_user.username,
            "mcp_enabled": profile.mcp_enabled,
            "default_mcp_enabled": bool(
                get_system_governance_settings().get("default_mcp_enabled", False)
            ),
        }

    def approve_user(self, *, actor_user_id: int, target_user_id: int) -> dict[str, Any]:
        """Approve a pending user."""

        with transaction.atomic():
            actor = User._default_manager.get(id=actor_user_id)
            target_user = User._default_manager.get(id=target_user_id)
            profile = target_user.account_profile

            if profile.approval_status == "approved":
                return {
                    "level": "warning",
                    "message": f"用户 {target_user.username} 已经被批准过了",
                    "username": target_user.username,
                }
            if profile.approval_status == "rejected":
                return {
                    "level": "error",
                    "message": f"用户 {target_user.username} 已被拒绝，请先取消拒绝状态",
                    "username": target_user.username,
                }
            if profile.approval_status != "pending":
                return {
                    "level": "error",
                    "message": f"用户 {target_user.username} 当前状态不允许批准",
                    "username": target_user.username,
                }

            target_user.is_active = True
            target_user.save(update_fields=["is_active"])

            profile.approval_status = "approved"
            profile.approved_at = timezone.now()
            profile.approved_by = actor
            profile.mcp_enabled = bool(
                get_system_governance_settings().get("default_mcp_enabled", False)
            )
            profile.rejection_reason = ""
            profile.save(
                update_fields=[
                    "approval_status",
                    "approved_at",
                    "approved_by",
                    "mcp_enabled",
                    "rejection_reason",
                    "updated_at",
                ]
            )

            return {
                "level": "success",
                "message": f"已批准用户 {target_user.username}",
                "username": target_user.username,
            }

    def reject_user(
        self,
        *,
        actor_user_id: int,
        target_user_id: int,
        rejection_reason: str,
    ) -> dict[str, Any]:
        """Reject a pending user and revoke active tokens."""

        with transaction.atomic():
            actor = User._default_manager.get(id=actor_user_id)
            target_user = User._default_manager.get(id=target_user_id)
            profile = target_user.account_profile

            if target_user.id == actor.id:
                return {
                    "level": "error",
                    "message": "不能拒绝自己",
                    "username": target_user.username,
                }

            if profile.approval_status != "pending":
                return {
                    "level": "error",
                    "message": f"用户 {target_user.username} 当前状态不允许拒绝",
                    "username": target_user.username,
                }

            profile.approval_status = "rejected"
            profile.rejection_reason = rejection_reason
            profile.approved_at = None
            profile.approved_by = None
            profile.save(
                update_fields=[
                    "approval_status",
                    "rejection_reason",
                    "approved_at",
                    "approved_by",
                    "updated_at",
                ]
            )

            target_user.is_active = False
            target_user.save(update_fields=["is_active"])
            for token in UserAccessTokenModel._default_manager.filter(
                user=target_user,
                is_active=True,
            ):
                token.revoke()

            return {
                "level": "success",
                "message": f"已拒绝用户 {target_user.username}",
                "username": target_user.username,
            }

    def set_user_role(self, *, target_user_id: int, rbac_role: str) -> dict[str, Any]:
        """Update a user's RBAC role."""

        target_user = User._default_manager.get(id=target_user_id)
        profile = target_user.account_profile
        profile.rbac_role = rbac_role
        profile.save(update_fields=["rbac_role", "updated_at"])
        return {
            "level": "success",
            "message": f"已将用户 {target_user.username} 角色更新为 {rbac_role}",
            "username": target_user.username,
        }

    def reset_user_status(self, *, actor_user_id: int, target_user_id: int) -> dict[str, Any]:
        """Reset a user's approval status back to pending."""

        with transaction.atomic():
            actor = User._default_manager.get(id=actor_user_id)
            target_user = User._default_manager.get(id=target_user_id)
            profile = target_user.account_profile

            if target_user.id == actor.id:
                return {
                    "level": "error",
                    "message": "不能重置自己",
                    "username": target_user.username,
                }

            profile.approval_status = "pending"
            profile.approved_at = None
            profile.approved_by = None
            profile.rejection_reason = ""
            profile.save(
                update_fields=[
                    "approval_status",
                    "approved_at",
                    "approved_by",
                    "rejection_reason",
                    "updated_at",
                ]
            )

            target_user.is_active = False
            target_user.save(update_fields=["is_active"])
            for token in UserAccessTokenModel._default_manager.filter(
                user=target_user,
                is_active=True,
            ):
                token.revoke()

            return {
                "level": "success",
                "message": f"已重置用户 {target_user.username} 的状态",
                "username": target_user.username,
            }

    def build_system_settings_context(self) -> dict[str, Any]:
        """Build the system settings page context."""

        system_settings, governance = self._account_settings_projection()
        for field_name in (
            "market_color_convention",
            "alpha_pool_mode",
            "benchmark_code_map",
            "asset_proxy_code_map",
        ):
            if field_name in governance:
                setattr(system_settings, field_name, governance[field_name])
        return {
            "system_settings": system_settings,
            "market_color_choices": SystemSettingsProjection.MARKET_COLOR_CONVENTION_CHOICES,
            "alpha_pool_mode_choices": SystemSettingsProjection.ALPHA_POOL_MODE_CHOICES,
            "market_visuals": get_runtime_market_visual_tokens(),
            "benchmark_code_map_json": json.dumps(
                governance.get("benchmark_code_map") or {},
                ensure_ascii=False,
                indent=2,
            ),
            "asset_proxy_code_map_json": json.dumps(
                governance.get("asset_proxy_code_map") or {},
                ensure_ascii=False,
                indent=2,
            ),
        }

    def update_system_settings_from_mapping(
        self,
        data: Mapping[str, Any],
        *,
        actor: Any = None,
    ) -> None:
        """Update system settings from an HTTP form mapping."""

        current_governance = get_system_governance_settings()
        market_color_choices = {
            key for key, _ in SystemSettingsProjection.MARKET_COLOR_CONVENTION_CHOICES
        }
        alpha_pool_mode_choices = {
            key for key, _ in SystemSettingsProjection.ALPHA_POOL_MODE_CHOICES
        }

        benchmark_code_map = json.loads(data.get("benchmark_code_map", "{}") or "{}")
        asset_proxy_code_map = json.loads(data.get("asset_proxy_code_map", "{}") or "{}")
        market_color_convention = data.get(
            "market_color_convention",
            current_governance.get("market_color_convention", "cn_a_share"),
        )
        alpha_pool_mode = data.get(
            "alpha_pool_mode",
            current_governance.get(
                "alpha_pool_mode", SystemSettingsProjection.ALPHA_POOL_MODE_STRICT_VALUATION
            ),
        )

        if not isinstance(benchmark_code_map, dict):
            raise ValueError("基准代码映射必须是 JSON 对象")
        if not isinstance(asset_proxy_code_map, dict):
            raise ValueError("资产代理代码映射必须是 JSON 对象")
        if market_color_convention not in market_color_choices:
            raise ValueError("市场颜色约定不合法")
        if alpha_pool_mode not in alpha_pool_mode_choices:
            raise ValueError("Alpha 股票池模式不合法")

        with transaction.atomic():
            update_system_governance_settings(
                {
                    "require_user_approval": data.get("require_user_approval") == "on",
                    "auto_approve_first_admin": data.get("auto_approve_first_admin") == "on",
                    "default_mcp_enabled": data.get("default_mcp_enabled") == "on",
                    "allow_token_plaintext_view": data.get("allow_token_plaintext_view") == "on",
                    "user_agreement_content": data.get("user_agreement_content", ""),
                    "risk_warning_content": data.get("risk_warning_content", ""),
                    "notes": data.get("notes", ""),
                    "market_color_convention": market_color_convention,
                    "alpha_pool_mode": alpha_pool_mode,
                    "benchmark_code_map": benchmark_code_map,
                    "asset_proxy_code_map": asset_proxy_code_map,
                },
                actor=actor,
            )

    def build_backup_download_payload(self, token: str) -> dict[str, Any]:
        """Atomically consume one current backup token and generate its archive."""

        with transaction.atomic():
            config = get_backup_delivery_settings(base_settings=SystemSettingsProjection())
            max_age_seconds = max(config.backup_link_ttl_days, 1) * 86400

            try:
                payload = validate_download_token(token, max_age_seconds=max_age_seconds)
            except Exception as exc:
                raise LookupError("备份链接无效或已过期") from exc

            if payload["settings_id"] != config.pk or payload["email"] != config.backup_email:
                raise LookupError("备份链接无效")
            if not config.backup_enabled:
                raise ValueError("数据库备份邮件功能未启用")

            supplied_digest = hash_download_nonce(payload["nonce"])
            consumed_at = timezone.now()
            if not consume_backup_download_token(digest=supplied_digest, consumed_at=consumed_at):
                raise LookupError("备份链接无效或已使用")

        archive = generate_backup_archive(config)
        return {
            "filename": archive.filename,
            "content": archive.content,
            "content_type": archive.content_type,
        }
