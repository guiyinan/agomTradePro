"""
Data Center — Interface Layer Serializers

DRF serializers for provider config input validation and output formatting.
No business logic here — only field-level validation.
"""

from __future__ import annotations

from typing import Any, cast

from rest_framework import serializers

_SENSITIVE_PROVIDER_KEYS = frozenset({"api_key", "api_secret", "token", "secret", "password"})


def _sanitize_provider_config_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_provider_config_value(item)
            for key, item in value.items()
            if str(key).lower() not in _SENSITIVE_PROVIDER_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_provider_config_value(item) for item in value]
    return cast(object, value)


class ProviderConfigSerializer(serializers.Serializer[Any]):
    """Input / output serializer for a provider configuration."""

    SOURCE_TYPE_CHOICES = [
        "tushare",
        "akshare",
        "eastmoney",
        "qmt",
        "fred",
        "wind",
        "choice",
    ]

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=100)
    source_type = serializers.ChoiceField(choices=SOURCE_TYPE_CHOICES)
    is_active = serializers.BooleanField(default=True)
    priority = serializers.IntegerField(default=100)
    api_key = serializers.CharField(
        max_length=500,
        allow_blank=True,
        default="",
        write_only=True,
        style={"input_type": "password"},
    )
    api_secret = serializers.CharField(
        max_length=500,
        allow_blank=True,
        default="",
        write_only=True,
        style={"input_type": "password"},
    )
    http_url = serializers.URLField(allow_blank=True, default="")
    api_endpoint = serializers.URLField(allow_blank=True, default="")
    extra_config = serializers.DictField(child=serializers.JSONField(), default=dict)
    description = serializers.CharField(allow_blank=True, default="")


class ProviderConfigListSerializer(serializers.Serializer[Any]):
    """Read serializer that masks sensitive credential fields."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField()
    source_type = serializers.CharField()
    is_active = serializers.BooleanField()
    priority = serializers.IntegerField()
    # Mask actual key value, just indicate whether one is configured
    has_api_key = serializers.SerializerMethodField()
    has_api_secret = serializers.SerializerMethodField()
    http_url = serializers.CharField()
    api_endpoint = serializers.CharField()
    extra_config = serializers.SerializerMethodField()
    description = serializers.CharField()

    def get_has_api_key(self, obj: dict[str, Any]) -> bool:
        return bool(obj.get("has_api_key", obj.get("api_key")))

    def get_has_api_secret(self, obj: dict[str, Any]) -> bool:
        return bool(obj.get("has_api_secret", obj.get("api_secret")))

    def get_extra_config(self, obj: dict[str, Any]) -> dict[str, Any]:
        sanitized = _sanitize_provider_config_value(obj.get("extra_config") or {})
        return cast(dict[str, Any], sanitized)


class DataProviderSettingsSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for global provider behaviour settings."""

    DEFAULT_SOURCE_CHOICES = ["akshare", "tushare", "failover"]

    default_source = serializers.ChoiceField(choices=DEFAULT_SOURCE_CHOICES)
    enable_failover = serializers.BooleanField()
    failover_tolerance = serializers.FloatField(min_value=0.0, max_value=1.0)
    description = serializers.CharField(allow_blank=True, default="")


class ProductionCoverageUniverseConfigSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for production coverage universe settings."""

    EXCHANGE_CHOICES = ["SSE", "SZSE", "BSE"]

    universe_id = serializers.CharField(max_length=50, required=False, default="active_a_share")
    asset_type = serializers.CharField(max_length=20, required=False, default="stock")
    exchanges = serializers.ListField(
        child=serializers.ChoiceField(choices=EXCHANGE_CHOICES),
        required=False,
        allow_empty=False,
        default=list,
    )
    include_inactive = serializers.BooleanField(required=False, default=False)
    min_active_asset_count = serializers.IntegerField(required=False, min_value=0, default=4000)
    min_star_market_count = serializers.IntegerField(required=False, min_value=0, default=200)
    min_chinext_count = serializers.IntegerField(required=False, min_value=0, default=0)
    min_bse_count = serializers.IntegerField(required=False, min_value=0, default=50)
    description = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_exchanges(self, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in value:
            exchange = str(raw).strip().upper()
            if exchange and exchange not in normalized:
                normalized.append(exchange)
        if not normalized:
            raise serializers.ValidationError("At least one exchange is required.")
        return normalized


class ConnectionTestResultSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for connection test results."""

    success = serializers.BooleanField()
    status = serializers.CharField()
    summary = serializers.CharField()
    logs = serializers.ListField(child=serializers.CharField())
    tested_at = serializers.DateTimeField()


class ProviderHealthSnapshotSerializer(serializers.Serializer[Any]):
    """Serializer for live provider health snapshots."""

    provider_name = serializers.CharField()
    capability = serializers.CharField()
    status = serializers.CharField()
    consecutive_failures = serializers.IntegerField()
    last_success_at = serializers.DateTimeField(allow_null=True)
    avg_latency_ms = serializers.FloatField(allow_null=True)


class IndicatorCatalogSerializer(serializers.Serializer[Any]):
    """Serializer for macro indicator catalog CRUD."""

    PERIOD_TYPE_CHOICES = ["D", "W", "M", "Q", "H", "Y"]

    code = serializers.CharField(max_length=50)
    name_cn = serializers.CharField(max_length=100)
    name_en = serializers.CharField(max_length=100, allow_blank=True, default="")
    description = serializers.CharField(allow_blank=True, default="")
    category = serializers.CharField(max_length=30, allow_blank=True, default="")
    default_period_type = serializers.ChoiceField(choices=PERIOD_TYPE_CHOICES, default="M")
    is_active = serializers.BooleanField(default=True)
    extra = serializers.DictField(child=serializers.JSONField(), default=dict)
    default_rule = serializers.DictField(read_only=True)


class PublisherCatalogSerializer(serializers.Serializer[Any]):
    """Serializer for provenance publisher catalog CRUD."""

    PUBLISHER_CLASS_CHOICES = [
        "government",
        "association",
        "market_infrastructure",
        "regulator",
        "system",
        "other",
    ]

    code = serializers.CharField(max_length=40)
    canonical_name = serializers.CharField(max_length=120)
    canonical_name_en = serializers.CharField(max_length=160, allow_blank=True, default="")
    publisher_class = serializers.ChoiceField(choices=PUBLISHER_CLASS_CHOICES)
    aliases = serializers.ListField(
        child=serializers.CharField(max_length=120),
        required=False,
        default=list,
    )
    country_code = serializers.CharField(max_length=10, required=False, default="CN")
    website = serializers.URLField(allow_blank=True, required=False, default="")
    is_active = serializers.BooleanField(default=True)
    description = serializers.CharField(allow_blank=True, default="")


class IndicatorUnitRuleSerializer(serializers.Serializer[Any]):
    """Serializer for indicator unit-rule CRUD."""

    id = serializers.IntegerField(read_only=True)
    indicator_code = serializers.CharField(max_length=50, required=False)
    source_type = serializers.CharField(max_length=20, allow_blank=True, default="")
    dimension_key = serializers.CharField(max_length=30)
    original_unit = serializers.CharField(max_length=20, allow_blank=True, default="")
    storage_unit = serializers.CharField(max_length=20)
    display_unit = serializers.CharField(max_length=20)
    multiplier_to_storage = serializers.FloatField(min_value=0.00000001)
    is_active = serializers.BooleanField(default=True)
    priority = serializers.IntegerField(default=0)
    description = serializers.CharField(max_length=200, allow_blank=True, default="")


class SyncMacroRequestSerializer(serializers.Serializer[dict[str, Any]]):
    provider_id = serializers.IntegerField()
    indicator_code = serializers.CharField(max_length=50)
    start = serializers.DateField()
    end = serializers.DateField()


class SyncPriceRequestSerializer(serializers.Serializer[dict[str, Any]]):
    provider_id = serializers.IntegerField()
    asset_code = serializers.CharField(max_length=20)
    start = serializers.DateField()
    end = serializers.DateField()


class SyncQuoteRequestSerializer(serializers.Serializer[dict[str, Any]]):
    provider_id = serializers.IntegerField()
    asset_codes = serializers.ListField(child=serializers.CharField(max_length=20))


class DecisionReliabilityRepairRequestSerializer(serializers.Serializer[dict[str, Any]]):
    target_date = serializers.DateField(required=False, allow_null=True, default=None)
    portfolio_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    asset_codes = serializers.ListField(
        child=serializers.CharField(max_length=20),
        required=False,
        default=list,
    )
    macro_indicator_codes = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        default=list,
    )
    strict = serializers.BooleanField(required=False, default=True)
    quote_max_age_hours = serializers.FloatField(required=False, min_value=0.1, default=4.0)


class SyncFundNavRequestSerializer(serializers.Serializer[dict[str, Any]]):
    provider_id = serializers.IntegerField()
    fund_code = serializers.CharField(max_length=20)
    start = serializers.DateField()
    end = serializers.DateField()


class SyncFinancialRequestSerializer(serializers.Serializer[dict[str, Any]]):
    provider_id = serializers.IntegerField()
    asset_code = serializers.CharField(max_length=20)
    periods = serializers.IntegerField(min_value=1, default=8)


class SyncValuationRequestSerializer(serializers.Serializer[dict[str, Any]]):
    provider_id = serializers.IntegerField()
    asset_code = serializers.CharField(max_length=20)
    start = serializers.DateField()
    end = serializers.DateField()


class SyncSectorMembershipRequestSerializer(serializers.Serializer[dict[str, Any]]):
    provider_id = serializers.IntegerField()
    sector_code = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    sector_name = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=""
    )
    effective_date = serializers.DateField(required=False, allow_null=True, default=None)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.get("sector_code") and not attrs.get("sector_name"):
            raise serializers.ValidationError("Either sector_code or sector_name is required.")
        return attrs


class SyncNewsRequestSerializer(serializers.Serializer[dict[str, Any]]):
    provider_id = serializers.IntegerField()
    asset_code = serializers.CharField(max_length=20)
    limit = serializers.IntegerField(min_value=1, max_value=200, default=20)


class SyncCapitalFlowRequestSerializer(serializers.Serializer[dict[str, Any]]):
    provider_id = serializers.IntegerField()
    asset_code = serializers.CharField(max_length=20)
    period = serializers.CharField(max_length=10, default="5d")


class CapitalFlowQuerySerializer(serializers.Serializer[dict[str, Any]]):
    """Validate the canonical persisted capital-flow query contract."""

    asset_code = serializers.CharField(
        max_length=20,
        allow_blank=False,
        trim_whitespace=True,
    )
    start = serializers.DateField(required=False, allow_null=True)
    end = serializers.DateField(required=False, allow_null=True)
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=500,
        default=100,
    )

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Reject legacy or unknown query parameters."""

        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError(
                {"non_field_errors": [f"Unknown query parameters: {', '.join(unknown_fields)}"]}
            )
        return cast(dict[str, Any], super().to_internal_value(data))

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Require an ordered optional date range."""

        start = attrs.get("start")
        end = attrs.get("end")
        if start is not None and end is not None and start > end:
            raise serializers.ValidationError("start must be on or before end")
        return attrs


class MarketThermometerConfigSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for market thermometer config payloads."""

    short_window = serializers.IntegerField(required=False, min_value=1)
    medium_window = serializers.IntegerField(required=False, min_value=1)
    long_window = serializers.IntegerField(required=False, min_value=1)
    monthly_long_window = serializers.IntegerField(required=False, min_value=1)
    daily_stale_days = serializers.IntegerField(required=False, min_value=1)
    monthly_stale_days = serializers.IntegerField(required=False, min_value=1)
    min_valid_components = serializers.IntegerField(required=False, min_value=1)
    component_weights = serializers.DictField(
        child=serializers.FloatField(min_value=0.0),
        required=False,
    )
    thresholds = serializers.DictField(
        child=serializers.FloatField(min_value=0.0, max_value=100.0),
        required=False,
    )


class MarketThermometerUserOverrideSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for per-user market thermometer threshold overrides."""

    warm_threshold = serializers.FloatField(required=False, min_value=0.0, max_value=100.0)
    hot_threshold = serializers.FloatField(required=False, min_value=0.0, max_value=100.0)
    overheat_threshold = serializers.FloatField(required=False, min_value=0.0, max_value=100.0)
    extreme_threshold = serializers.FloatField(required=False, min_value=0.0, max_value=100.0)


class MarketThermometerImportSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for investor-account CSV import."""

    csv_text = serializers.CharField(required=False, allow_blank=True)
    dry_run = serializers.BooleanField(required=False, default=False)
    value_unit = serializers.ChoiceField(choices=("户", "万户"), required=False, default="户")
    fail_on_warning = serializers.BooleanField(required=False, default=False)
