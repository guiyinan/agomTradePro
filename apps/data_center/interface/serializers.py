"""
Data Center — Interface Layer Serializers

DRF serializers for provider config input validation and output formatting.
No business logic here — only field-level validation.
"""

from __future__ import annotations

from rest_framework import serializers


class ProviderConfigSerializer(serializers.Serializer):
    """Input / output serializer for a provider configuration."""

    SOURCE_TYPE_CHOICES = [
        "tushare", "akshare", "eastmoney", "qmt", "fred", "wind", "choice",
    ]

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=100)
    source_type = serializers.ChoiceField(choices=SOURCE_TYPE_CHOICES)
    is_active = serializers.BooleanField(default=True)
    priority = serializers.IntegerField(default=100)
    api_key = serializers.CharField(
        max_length=500, allow_blank=True, default="",
        # Write-only so tokens are never echoed in list responses
        style={"input_type": "password"},
    )
    api_secret = serializers.CharField(
        max_length=500, allow_blank=True, default="",
        style={"input_type": "password"},
    )
    http_url = serializers.URLField(allow_blank=True, default="")
    api_endpoint = serializers.URLField(allow_blank=True, default="")
    extra_config = serializers.DictField(child=serializers.JSONField(), default=dict)
    description = serializers.CharField(allow_blank=True, default="")


class ProviderConfigListSerializer(serializers.Serializer):
    """Read serializer that masks sensitive credential fields."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField()
    source_type = serializers.CharField()
    is_active = serializers.BooleanField()
    priority = serializers.IntegerField()
    # Mask actual key value, just indicate whether one is configured
    has_api_key = serializers.SerializerMethodField()
    http_url = serializers.CharField()
    api_endpoint = serializers.CharField()
    extra_config = serializers.DictField()
    description = serializers.CharField()

    def get_has_api_key(self, obj: dict) -> bool:  # type: ignore[override]
        return bool(obj.get("api_key"))


class DataProviderSettingsSerializer(serializers.Serializer):
    """Serializer for global provider behaviour settings."""

    DEFAULT_SOURCE_CHOICES = ["akshare", "tushare", "failover"]

    default_source = serializers.ChoiceField(choices=DEFAULT_SOURCE_CHOICES)
    enable_failover = serializers.BooleanField()
    failover_tolerance = serializers.FloatField(min_value=0.0, max_value=1.0)
    description = serializers.CharField(allow_blank=True, default="")


class ConnectionTestResultSerializer(serializers.Serializer):
    """Serializer for connection test results."""

    success = serializers.BooleanField()
    status = serializers.CharField()
    summary = serializers.CharField()
    logs = serializers.ListField(child=serializers.CharField())
    tested_at = serializers.DateTimeField()


class ProviderHealthSnapshotSerializer(serializers.Serializer):
    """Serializer for live provider health snapshots."""

    provider_name = serializers.CharField()
    capability = serializers.CharField()
    status = serializers.CharField()
    consecutive_failures = serializers.IntegerField()
    last_success_at = serializers.DateTimeField(allow_null=True)
    avg_latency_ms = serializers.FloatField(allow_null=True)


class SyncMacroRequestSerializer(serializers.Serializer):
    provider_id = serializers.IntegerField()
    indicator_code = serializers.CharField(max_length=50)
    start = serializers.DateField()
    end = serializers.DateField()


class SyncPriceRequestSerializer(serializers.Serializer):
    provider_id = serializers.IntegerField()
    asset_code = serializers.CharField(max_length=20)
    start = serializers.DateField()
    end = serializers.DateField()


class SyncQuoteRequestSerializer(serializers.Serializer):
    provider_id = serializers.IntegerField()
    asset_codes = serializers.ListField(child=serializers.CharField(max_length=20))


class SyncFundNavRequestSerializer(serializers.Serializer):
    provider_id = serializers.IntegerField()
    fund_code = serializers.CharField(max_length=20)
    start = serializers.DateField()
    end = serializers.DateField()


class SyncFinancialRequestSerializer(serializers.Serializer):
    provider_id = serializers.IntegerField()
    asset_code = serializers.CharField(max_length=20)
    periods = serializers.IntegerField(min_value=1, default=8)


class SyncValuationRequestSerializer(serializers.Serializer):
    provider_id = serializers.IntegerField()
    asset_code = serializers.CharField(max_length=20)
    start = serializers.DateField()
    end = serializers.DateField()


class SyncSectorMembershipRequestSerializer(serializers.Serializer):
    provider_id = serializers.IntegerField()
    sector_code = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    sector_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    effective_date = serializers.DateField(required=False, allow_null=True, default=None)

    def validate(self, attrs):
        if not attrs.get("sector_code") and not attrs.get("sector_name"):
            raise serializers.ValidationError("Either sector_code or sector_name is required.")
        return attrs


class SyncNewsRequestSerializer(serializers.Serializer):
    provider_id = serializers.IntegerField()
    asset_code = serializers.CharField(max_length=20)
    limit = serializers.IntegerField(min_value=1, max_value=200, default=20)


class SyncCapitalFlowRequestSerializer(serializers.Serializer):
    provider_id = serializers.IntegerField()
    asset_code = serializers.CharField(max_length=20)
    period = serializers.CharField(max_length=10, default="5d")
