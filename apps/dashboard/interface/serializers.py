"""
Dashboard Interface Serializers

仪表盘 DRF 序列化器定义。
"""

from collections.abc import Mapping
from typing import Any, cast

from django.apps import apps as django_apps
from django.db.models import Model
from rest_framework import serializers

DashboardAlertModel = django_apps.get_model("dashboard", "DashboardAlertModel")
DashboardCardModel = django_apps.get_model("dashboard", "DashboardCardModel")
DashboardConfigModel = django_apps.get_model("dashboard", "DashboardConfigModel")
DashboardUserConfigModel = django_apps.get_model("dashboard", "DashboardUserConfigModel")

# ========== Domain Entity Serializers ==========


class StrictFieldsSerializer(serializers.Serializer[dict[str, Any]]):
    """Reject fields outside published Dashboard mutation contracts."""

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Validate the request key set before normal field conversion."""

        if not isinstance(data, Mapping):
            raise serializers.ValidationError("Expected an object payload.")
        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError(
                {"non_field_errors": [f"Unknown fields: {', '.join(unknown_fields)}"]}
            )
        return cast(dict[str, Any], super().to_internal_value(data))


def _validate_unique_ids(values: list[str]) -> list[str]:
    """Reject repeated dashboard identifiers while preserving request order."""

    if len(set(values)) != len(values):
        raise serializers.ValidationError("Duplicate identifiers are not allowed.")
    return values


class MetricCardSerializer(serializers.Serializer[dict[str, Any]]):
    """指标卡片序列化器"""

    title = serializers.CharField()
    value = serializers.FloatField(allow_null=True)
    unit = serializers.CharField(allow_null=True, required=False)
    prefix = serializers.CharField(allow_null=True, required=False)
    suffix = serializers.CharField(allow_null=True, required=False)
    trend = serializers.CharField(allow_null=True, required=False)
    trend_value = serializers.FloatField(allow_null=True, required=False)
    trend_period = serializers.CharField(allow_null=True, required=False)
    comparison_value = serializers.FloatField(allow_null=True, required=False)
    comparison_label = serializers.CharField(allow_null=True, required=False)
    format_pattern = serializers.CharField(allow_null=True, required=False)
    icon = serializers.CharField(allow_null=True, required=False)
    color = serializers.CharField(allow_null=True, required=False)
    threshold_warning = serializers.FloatField(allow_null=True, required=False)
    threshold_critical = serializers.FloatField(allow_null=True, required=False)
    data_source = serializers.CharField(allow_null=True, required=False)
    last_updated = serializers.DateTimeField(allow_null=True, required=False)
    formatted_value = serializers.CharField(read_only=True)


class ChartConfigSerializer(serializers.Serializer[dict[str, Any]]):
    """图表配置序列化器"""

    chart_type = serializers.CharField()
    data_type = serializers.CharField(required=False)
    title = serializers.CharField(allow_null=True, required=False)
    x_axis_label = serializers.CharField(allow_null=True, required=False)
    y_axis_label = serializers.CharField(allow_null=True, required=False)
    series = serializers.ListField(child=serializers.DictField(), required=False)
    colors = serializers.DictField(required=False)
    show_legend = serializers.BooleanField(required=False)
    show_grid = serializers.BooleanField(required=False)
    interactive = serializers.BooleanField(required=False)
    height = serializers.IntegerField(required=False)
    width = serializers.CharField(required=False)
    options = serializers.DictField(required=False)


class DashboardWidgetSerializer(serializers.Serializer[dict[str, Any]]):
    """仪表盘组件序列化器"""

    widget_id = serializers.CharField()
    widget_type = serializers.CharField()
    title = serializers.CharField(allow_null=True, required=False)
    config = serializers.DictField(allow_null=True, required=False)
    data_source = serializers.CharField(allow_null=True, required=False)
    refresh_interval = serializers.IntegerField(required=False)
    cache_ttl = serializers.IntegerField(required=False)
    is_visible = serializers.BooleanField(required=False)
    is_collapsed = serializers.BooleanField(required=False)
    is_loading = serializers.BooleanField(required=False)
    error_message = serializers.CharField(allow_null=True, required=False)
    metadata = serializers.DictField(required=False)
    cache_key = serializers.CharField(read_only=True)


class DashboardCardSerializer(serializers.Serializer[dict[str, Any]]):
    """仪表盘卡片序列化器"""

    card_id = serializers.CharField()
    card_type = serializers.CharField()
    title = serializers.CharField(allow_null=True, required=False)
    widgets = DashboardWidgetSerializer(many=True, required=False)
    layout = serializers.CharField(allow_null=True, required=False)
    position = serializers.DictField(allow_null=True, required=False)
    size = serializers.DictField(allow_null=True, required=False)
    is_visible = serializers.BooleanField(required=False)
    is_collapsible = serializers.BooleanField(required=False)
    is_collapsed = serializers.BooleanField(required=False)
    is_draggable = serializers.BooleanField(required=False)
    is_resizable = serializers.BooleanField(required=False)
    dependencies = serializers.ListField(child=serializers.CharField(), required=False)
    metadata = serializers.DictField(required=False)


class DashboardLayoutSerializer(serializers.Serializer[dict[str, Any]]):
    """仪表盘布局序列化器"""

    layout_id = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_null=True, required=False)
    cards = DashboardCardSerializer(many=True, required=False)
    columns = serializers.IntegerField(required=False)
    row_height = serializers.IntegerField(required=False)
    gutter = serializers.IntegerField(required=False)
    is_default = serializers.BooleanField(required=False)
    metadata = serializers.DictField(required=False)


class AlertConfigSerializer(serializers.Serializer[dict[str, Any]]):
    """告警配置序列化器"""

    alert_id = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_null=True, required=False)
    metric = serializers.CharField(allow_null=True, required=False)
    condition = serializers.CharField(allow_null=True, required=False)
    severity = serializers.CharField()
    threshold = serializers.FloatField(allow_null=True, required=False)
    notification_channels = serializers.ListField(child=serializers.CharField(), required=False)
    is_enabled = serializers.BooleanField(required=False)
    cooldown = serializers.IntegerField(required=False)
    metadata = serializers.DictField(required=False)


class DashboardPreferencesSerializer(serializers.Serializer[dict[str, Any]]):
    """用户偏好序列化器"""

    user_id = serializers.IntegerField()
    layout_id = serializers.CharField()
    hidden_cards = serializers.ListField(child=serializers.CharField(), required=False)
    collapsed_cards = serializers.ListField(child=serializers.CharField(), required=False)
    card_order = serializers.ListField(child=serializers.CharField(), required=False)
    custom_card_config = serializers.DictField(required=False)
    theme = serializers.CharField(required=False)
    refresh_enabled = serializers.BooleanField(required=False)
    refresh_interval = serializers.IntegerField(required=False)
    last_updated = serializers.DateTimeField(allow_null=True, required=False)


# ========== Service Result Serializers ==========


class MetricCalculationResultSerializer(serializers.Serializer[dict[str, Any]]):
    """指标计算结果序列化器"""

    metric_name = serializers.CharField()
    value = serializers.FloatField(allow_null=True)
    formatted_value = serializers.CharField()
    trend = serializers.CharField(allow_null=True, required=False)
    trend_value = serializers.FloatField(allow_null=True, required=False)
    severity = serializers.CharField(allow_null=True, required=False)
    timestamp = serializers.DateTimeField()
    metadata = serializers.DictField(required=False)


class LayoutResolutionResultSerializer(serializers.Serializer[dict[str, Any]]):
    """布局解析结果序列化器"""

    visible_cards = DashboardCardSerializer(many=True)
    visible_widgets = DashboardWidgetSerializer(many=True)
    hidden_count = serializers.IntegerField()
    total_cards = serializers.IntegerField()
    layout_metadata = serializers.DictField(required=False)


# ========== Model Serializers ==========


class DashboardConfigModelSerializer(serializers.ModelSerializer[Model]):
    """仪表盘配置模型序列化器"""

    class Meta:
        model = DashboardConfigModel
        fields = [
            "config_id",
            "name",
            "description",
            "layout_config",
            "card_configs",
            "is_default",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class DashboardUserConfigModelSerializer(serializers.ModelSerializer[Model]):
    """用户仪表盘配置模型序列化器"""

    username = serializers.CharField(source="user.username", read_only=True)
    dashboard_config_name = serializers.CharField(
        source="dashboard_config.name", read_only=True, allow_null=True
    )

    class Meta:
        model = DashboardUserConfigModel
        fields = [
            "id",
            "user",
            "username",
            "dashboard_config",
            "dashboard_config_name",
            "hidden_cards",
            "collapsed_cards",
            "card_order",
            "custom_card_config",
            "theme",
            "refresh_enabled",
            "refresh_interval",
            "last_updated",
        ]
        read_only_fields = ["last_updated"]


class DashboardCardModelSerializer(serializers.ModelSerializer[Model]):
    """仪表盘卡片模型序列化器"""

    class Meta:
        model = DashboardCardModel
        fields = [
            "id",
            "card_id",
            "card_type",
            "title",
            "description",
            "widget_config",
            "data_source",
            "visibility_conditions",
            "position",
            "size",
            "is_visible",
            "is_collapsible",
            "is_draggable",
            "is_resizable",
            "dependencies",
            "display_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class DashboardAlertModelSerializer(serializers.ModelSerializer[Model]):
    """仪表盘告警模型序列化器"""

    severity_display = serializers.CharField(source="get_severity_display", read_only=True)

    class Meta:
        model = DashboardAlertModel
        fields = [
            "id",
            "alert_id",
            "name",
            "description",
            "metric",
            "condition",
            "severity",
            "severity_display",
            "threshold",
            "notification_channels",
            "is_enabled",
            "cooldown",
            "last_triggered_at",
            "trigger_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["last_triggered_at", "trigger_count", "created_at", "updated_at"]


# ========== Request/Response Serializers ==========


class UpdatePreferencesRequestSerializer(StrictFieldsSerializer):
    """更新偏好请求序列化器"""

    hidden_cards = serializers.ListField(child=serializers.CharField(), required=False)
    collapsed_cards = serializers.ListField(child=serializers.CharField(), required=False)
    card_order = serializers.ListField(child=serializers.CharField(), required=False)
    theme = serializers.CharField(required=False)
    refresh_enabled = serializers.BooleanField(required=False)
    refresh_interval = serializers.IntegerField(required=False, min_value=1)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Reject no-op preference mutations."""

        if not attrs:
            raise serializers.ValidationError("At least one preference is required.")
        return attrs

    def validate_hidden_cards(self, value: list[str]) -> list[str]:
        """Reject duplicate hidden-card identifiers."""

        return _validate_unique_ids(value)

    def validate_collapsed_cards(self, value: list[str]) -> list[str]:
        """Reject duplicate collapsed-card identifiers."""

        return _validate_unique_ids(value)

    def validate_card_order(self, value: list[str]) -> list[str]:
        """Reject duplicate card-order identifiers."""

        return _validate_unique_ids(value)


class ToggleCardVisibilityRequestSerializer(StrictFieldsSerializer):
    """切换卡片可见性请求序列化器"""

    card_id = serializers.CharField()
    is_visible = serializers.BooleanField()


class ToggleCardCollapseRequestSerializer(StrictFieldsSerializer):
    """切换卡片折叠状态请求序列化器"""

    card_id = serializers.CharField()
    is_collapsed = serializers.BooleanField()


class RefreshDashboardRequestSerializer(StrictFieldsSerializer):
    """刷新仪表盘请求序列化器"""

    force_refresh = serializers.BooleanField(required=False)
    include_widgets = serializers.ListField(child=serializers.CharField(), required=False)

    def validate_include_widgets(self, value: list[str]) -> list[str]:
        """Reject duplicate widget refresh identifiers."""

        return _validate_unique_ids(value)


class DashboardResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """仪表盘响应序列化器"""

    layout = DashboardLayoutSerializer()
    preferences = DashboardPreferencesSerializer(required=False)
    alerts = AlertConfigSerializer(many=True, required=False)
    metrics = MetricCalculationResultSerializer(many=True, required=False)
    timestamp = serializers.DateTimeField()
