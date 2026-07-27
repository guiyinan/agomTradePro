"""
Share Admin Configuration

Django Admin 配置。
"""

from django.contrib import admin
from django.http import HttpRequest

from apps.share.application.interface_services import has_share_disclaimer_config
from apps.share.models import (
    ShareAccessLogModel,
    ShareDisclaimerConfigModel,
    ShareLinkModel,
    ShareSnapshotModel,
)
from shared.infrastructure.django_admin import TypedModelAdmin


@admin.register(ShareLinkModel)
class ShareLinkAdmin(TypedModelAdmin[ShareLinkModel]):
    """分享链接 Admin"""

    list_display = [
        "id",
        "short_code",
        "title",
        "owner",
        "share_level",
        "status",
        "access_count",
        "expires_at",
        "created_at",
    ]
    list_filter = ["share_level", "status", "created_at", "expires_at"]
    search_fields = ["short_code", "title", "owner__username"]
    readonly_fields = [
        "short_code",
        "password_hash",
        "access_count",
        "last_snapshot_at",
        "last_accessed_at",
        "created_at",
        "updated_at",
    ]
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "基本信息",
            {
                "fields": (
                    "owner",
                    "account_id",
                    "short_code",
                    "title",
                    "subtitle",
                    "share_level",
                    "status",
                )
            },
        ),
        (
            "访问控制",
            {
                "fields": (
                    "password_hash",
                    "expires_at",
                    "max_access_count",
                    "access_count",
                )
            },
        ),
        (
            "可见性配置",
            {
                "fields": (
                    "show_amounts",
                    "show_positions",
                    "show_transactions",
                    "show_decision_summary",
                    "show_decision_evidence",
                    "show_invalidation_logic",
                )
            },
        ),
        ("SEO 配置", {"fields": ("allow_indexing",)}),
        (
            "时间信息",
            {
                "fields": (
                    "last_snapshot_at",
                    "last_accessed_at",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Require share creation to pass through password hashing and scope use cases."""

        del request
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: ShareLinkModel | None = None,
    ) -> bool:
        """Preserve links and their cascading snapshot/access audit evidence."""

        del request, obj
        return False


@admin.register(ShareSnapshotModel)
class ShareSnapshotAdmin(TypedModelAdmin[ShareSnapshotModel]):
    """分享快照 Admin"""

    list_display = [
        "id",
        "share_link",
        "snapshot_version",
        "generated_at",
        "source_range_start",
        "source_range_end",
    ]
    list_filter = ["generated_at"]
    search_fields = ["share_link__short_code", "share_link__title"]
    readonly_fields = [field.name for field in ShareSnapshotModel._meta.fields]
    date_hierarchy = "generated_at"

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Prevent operators from fabricating generated snapshots."""

        del request
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: ShareSnapshotModel | None = None,
    ) -> bool:
        """Keep generated snapshot evidence immutable."""

        del request, obj
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: ShareSnapshotModel | None = None,
    ) -> bool:
        """Prevent deleting generated snapshot evidence through Admin."""

        del request, obj
        return False


@admin.register(ShareAccessLogModel)
class ShareAccessLogAdmin(TypedModelAdmin[ShareAccessLogModel]):
    """访问日志 Admin"""

    list_display = [
        "id",
        "share_link",
        "accessed_at",
        "ip_hash",
        "result_status",
        "is_verified",
    ]
    list_filter = ["result_status", "is_verified", "accessed_at"]
    search_fields = ["share_link__short_code", "ip_hash"]
    readonly_fields = [field.name for field in ShareAccessLogModel._meta.fields]
    date_hierarchy = "accessed_at"

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Prevent operators from fabricating public-access audit records."""

        del request
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: ShareAccessLogModel | None = None,
    ) -> bool:
        """Keep public-access audit evidence immutable."""

        del request, obj
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: ShareAccessLogModel | None = None,
    ) -> bool:
        """Prevent deleting public-access audit evidence through Admin."""

        del request, obj
        return False


@admin.register(ShareDisclaimerConfigModel)
class ShareDisclaimerConfigAdmin(TypedModelAdmin[ShareDisclaimerConfigModel]):
    list_display = ["singleton_key", "is_enabled", "modal_enabled", "updated_at"]
    readonly_fields = ["singleton_key", "created_at", "updated_at"]
    fieldsets = (
        ("显示开关", {"fields": ("singleton_key", "is_enabled", "modal_enabled")}),
        ("标题与按钮", {"fields": ("modal_title", "modal_confirm_text")}),
        ("提示内容", {"fields": ("lines",)}),
        ("时间信息", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Require Django add permission before checking singleton availability."""

        return super().has_add_permission(request) and not has_share_disclaimer_config()

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: ShareDisclaimerConfigModel | None = None,
    ) -> bool:
        """Prevent deleting the active public disclaimer configuration."""

        del request, obj
        return False
