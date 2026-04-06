"""
DRF Serializers for Macro Data API.
"""

from django.apps import apps as django_apps
from rest_framework import serializers

# Provider config is now owned by data_center; macro acts as a UI entry point only.
DataSourceConfig = django_apps.get_model("data_center", "ProviderConfigModel")
MacroIndicator = django_apps.get_model("macro", "MacroIndicator")


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
