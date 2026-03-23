"""
Share API Serializers

DRF 序列化器定义。
"""
from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.share.infrastructure.models import (
    ShareAccessLogModel,
    ShareLinkModel,
    ShareSnapshotModel,
)

User = get_user_model()


class ShareLinkSerializer(serializers.ModelSerializer):
    """
    分享链接序列化器
    """
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    has_password = serializers.SerializerMethodField()
    share_url = serializers.SerializerMethodField()
    visibility = serializers.SerializerMethodField()

    class Meta:
        model = ShareLinkModel
        fields = [
            "id",
            "owner_id",
            "owner_username",
            "account_id",
            "short_code",
            "title",
            "subtitle",
            "theme",
            "share_level",
            "status",
            "has_password",
            "expires_at",
            "max_access_count",
            "access_count",
            "last_snapshot_at",
            "last_accessed_at",
            "allow_indexing",
            "visibility",
            "share_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "owner_id",
            "owner_username",
            "short_code",
            "access_count",
            "last_snapshot_at",
            "last_accessed_at",
            "created_at",
            "updated_at",
        ]

    def get_has_password(self, obj) -> bool:
        """是否设置了密码"""
        return bool(obj.password_hash)

    def get_share_url(self, obj) -> str:
        """生成分享 URL"""
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(f"/share/{obj.short_code}/")
        return f"/share/{obj.short_code}/"

    def get_visibility(self, obj) -> dict:
        """获取可见性配置"""
        return {
            "amounts": obj.show_amounts,
            "positions": obj.show_positions,
            "transactions": obj.show_transactions,
            "decision_summary": obj.show_decision_summary,
            "decision_evidence": obj.show_decision_evidence,
            "invalidation_logic": obj.show_invalidation_logic,
        }


class CreateShareLinkSerializer(serializers.Serializer):
    """
    创建分享链接请求序列化器
    """
    account_id = serializers.IntegerField(min_value=1)
    title = serializers.CharField(max_length=100)
    subtitle = serializers.CharField(max_length=200, required=False, allow_null=True)
    theme = serializers.ChoiceField(
        choices=["bloomberg", "monopoly"],
        default="bloomberg",
    )
    share_level = serializers.ChoiceField(
        choices=["snapshot", "observer", "research"],
        default="snapshot",
    )
    password = serializers.CharField(max_length=128, required=False, allow_null=True, allow_blank=True)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    max_access_count = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    allow_indexing = serializers.BooleanField(default=False)
    show_amounts = serializers.BooleanField(default=False)
    show_positions = serializers.BooleanField(default=True)
    show_transactions = serializers.BooleanField(default=True)
    show_decision_summary = serializers.BooleanField(default=True)
    show_decision_evidence = serializers.BooleanField(default=False)
    show_invalidation_logic = serializers.BooleanField(default=False)

    def validate_account_id(self, value):
        """验证账户存在且属于当前用户"""
        from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
        try:
            account = SimulatedAccountModel.objects.get(id=value)
            # 验证账户属于当前用户
            request = self.context.get("request")
            if request and request.user.is_authenticated and account.user_id != request.user.id:
                raise serializers.ValidationError("无权分享此账户")
        except SimulatedAccountModel.DoesNotExist:
            raise serializers.ValidationError("模拟账户不存在")
        return value


class UpdateShareLinkSerializer(serializers.Serializer):
    """
    更新分享链接请求序列化器
    """
    title = serializers.CharField(max_length=100, required=False)
    subtitle = serializers.CharField(max_length=200, required=False, allow_null=True)
    theme = serializers.ChoiceField(
        choices=["bloomberg", "monopoly"],
        required=False,
    )
    share_level = serializers.ChoiceField(
        choices=["snapshot", "observer", "research"],
        required=False,
    )
    password = serializers.CharField(max_length=128, required=False, allow_null=True, allow_blank=True)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    max_access_count = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    allow_indexing = serializers.BooleanField(required=False)
    show_amounts = serializers.BooleanField(required=False)
    show_positions = serializers.BooleanField(required=False)
    show_transactions = serializers.BooleanField(required=False)
    show_decision_summary = serializers.BooleanField(required=False)
    show_decision_evidence = serializers.BooleanField(required=False)
    show_invalidation_logic = serializers.BooleanField(required=False)


class ShareSnapshotSerializer(serializers.ModelSerializer):
    """
    分享快照序列化器
    """
    class Meta:
        model = ShareSnapshotModel
        fields = [
            "id",
            "snapshot_version",
            "summary_payload",
            "performance_payload",
            "positions_payload",
            "transactions_payload",
            "decision_payload",
            "generated_at",
            "source_range_start",
            "source_range_end",
        ]
        read_only_fields = [
            "id",
            "snapshot_version",
            "generated_at",
        ]


class ShareAccessLogSerializer(serializers.ModelSerializer):
    """
    访问日志序列化器
    """
    share_link_title = serializers.CharField(source="share_link.title", read_only=True)

    class Meta:
        model = ShareAccessLogModel
        fields = [
            "id",
            "share_link_id",
            "share_link_title",
            "accessed_at",
            "ip_hash",
            "user_agent",
            "referer",
            "is_verified",
            "result_status",
        ]
        read_only_fields = [
            "id",
            "accessed_at",
        ]


class ShareAccessRequestSerializer(serializers.Serializer):
    """
    访问分享链接请求序列化器
    """
    password = serializers.CharField(max_length=128, required=False, allow_null=True, allow_blank=True)


class PublicShareLinkSerializer(serializers.ModelSerializer):
    """
    公开分享链接序列化器（用于公开访问 API）

    只包含允许公开的信息。
    """
    visibility = serializers.SerializerMethodField()

    class Meta:
        model = ShareLinkModel
        fields = [
            "title",
            "subtitle",
            "theme",
            "share_level",
            "visibility",
            "last_snapshot_at",
        ]

    def get_visibility(self, obj) -> dict:
        """获取可见性配置"""
        return {
            "amounts": obj.show_amounts,
            "positions": obj.show_positions,
            "transactions": obj.show_transactions,
            "decision_summary": obj.show_decision_summary,
            "decision_evidence": obj.show_decision_evidence,
            "invalidation_logic": obj.show_invalidation_logic,
        }


class PublicShareSnapshotSerializer(serializers.Serializer):
    """
    公开快照序列化器

    根据可见性配置过滤数据。
    """
    summary = serializers.DictField(read_only=True)
    performance = serializers.DictField(read_only=True, required=False)
    positions = serializers.DictField(read_only=True, required=False)
    transactions = serializers.DictField(read_only=True, required=False)
    decisions = serializers.DictField(read_only=True, required=False)
    generated_at = serializers.DateTimeField(read_only=True)
    source_range_start = serializers.DateField(read_only=True, required=False)
    source_range_end = serializers.DateField(read_only=True, required=False)
