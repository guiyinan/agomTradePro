"""
Share Admin Configuration

Django Admin 配置。
"""
from django.apps import apps as django_apps
from django.contrib import admin

from apps.share.application.interface_services import has_share_disclaimer_config

ShareAccessLogModel = django_apps.get_model("share", "ShareAccessLogModel")
ShareDisclaimerConfigModel = django_apps.get_model("share", "ShareDisclaimerConfigModel")
ShareLinkModel = django_apps.get_model("share", "ShareLinkModel")
ShareSnapshotModel = django_apps.get_model("share", "ShareSnapshotModel")


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


@admin.register(ShareDisclaimerConfigModel)
class ShareDisclaimerConfigAdmin(admin.ModelAdmin):
    list_display = ["singleton_key", "is_enabled", "modal_enabled", "updated_at"]
    readonly_fields = ["singleton_key", "created_at", "updated_at"]
    fieldsets = (
        ("显示开关", {"fields": ("singleton_key", "is_enabled", "modal_enabled")}),
        ("标题与按钮", {"fields": ("modal_title", "modal_confirm_text")}),
        ("提示内容", {"fields": ("lines",)}),
        ("时间信息", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        return not has_share_disclaimer_config()

    def has_delete_permission(self, request, obj=None):
        return False
