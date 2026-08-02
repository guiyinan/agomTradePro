"""
DRF Serializers for Macro Data API.
"""

from typing import Any

from rest_framework import serializers

from apps.data_center.interface.serializers import ProviderConfigSerializer


class MacroIndicatorSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize the frozen macro compatibility payload without loading its ORM model."""

    code = serializers.CharField()
    value = serializers.FloatField()
    unit = serializers.CharField(allow_blank=True, required=False)
    original_unit = serializers.CharField(allow_blank=True, required=False)
    reporting_period = serializers.DateField()
    period_type = serializers.CharField()
    published_at = serializers.DateField(allow_null=True, required=False)
    publication_lag_days = serializers.IntegerField(required=False)
    revision_number = serializers.IntegerField(required=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Register the ``source`` output field without shadowing DRF's Field.source."""

        super().__init__(*args, **kwargs)
        self.fields["source"] = serializers.CharField()


class DataSourceConfigSerializer(ProviderConfigSerializer):
    """Macro-facing serializer for datasource configuration payloads."""
