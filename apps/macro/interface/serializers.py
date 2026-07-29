"""
DRF Serializers for Macro Data API.
"""

from typing import Any

from django.apps import apps as django_apps
from rest_framework import serializers

from apps.data_center.interface.serializers import ProviderConfigSerializer

MacroIndicator = django_apps.get_model("macro", "MacroIndicator")


class MacroIndicatorSerializer(serializers.ModelSerializer[Any]):
    """Serializer for MacroIndicator"""

    class Meta:
        model = MacroIndicator
        fields = "__all__"


class DataSourceConfigSerializer(ProviderConfigSerializer):
    """Macro-facing serializer for datasource configuration payloads."""
