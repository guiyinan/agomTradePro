"""
DRF Serializers for Macro Data API.
"""

from rest_framework import serializers

from apps.macro.infrastructure.models import DataSourceConfig, MacroIndicator


class MacroIndicatorSerializer(serializers.ModelSerializer):
    """Serializer for MacroIndicator"""

    class Meta:
        model = MacroIndicator
        fields = '__all__'


class DataSourceConfigSerializer(serializers.ModelSerializer):
    """Serializer for datasource configuration."""

    class Meta:
        model = DataSourceConfig
        fields = [
            "id",
            "name",
            "source_type",
            "is_active",
            "priority",
            "api_endpoint",
            "http_url",
            "api_key",
            "api_secret",
            "extra_config",
            "description",
            "created_at",
            "updated_at",
        ]
