"""
Share Admin Configuration

Django Admin 配置。
"""
from django.contrib import admin
from apps.share.infrastructure.models import (
    ShareLinkModel,
    ShareSnapshotModel,
    ShareAccessLogModel,
)


@admin.register(ShareLinkModel)
class ShareLinkAdmin(admin.ModelAdmin):
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
        "access_count",
        "last_snapshot_at",
        "last_accessed_at",
        "created_at",
        "updated_at",
    ]
    date_hierarchy = "created_at"

    fieldsets = (
        ("基本信息", {
            "fields": (
                "owner",
                "account_id",
                "short_code",
                "title",
                "subtitle",
                "share_level",
                "status",
            )
        }),
        ("访问控制", {
            "fields": (
                "password_hash",
                "expires_at",
                "max_access_count",
                "access_count",
            )
        }),
        ("可见性配置", {
            "fields": (
                "show_amounts",
                "show_positions",
                "show_transactions",
                "show_decision_summary",
                "show_decision_evidence",
                "show_invalidation_logic",
            )
        }),
        ("SEO 配置", {
            "fields": ("allow_indexing",)
        }),
        ("时间信息", {
            "fields": (
                "last_snapshot_at",
                "last_accessed_at",
                "created_at",
                "updated_at",
            )
        }),
    )


@admin.register(ShareSnapshotModel)
class ShareSnapshotAdmin(admin.ModelAdmin):
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
    readonly_fields = ["generated_at"]
    date_hierarchy = "generated_at"


@admin.register(ShareAccessLogModel)
class ShareAccessLogAdmin(admin.ModelAdmin):
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
    readonly_fields = ["accessed_at"]
    date_hierarchy = "accessed_at"
