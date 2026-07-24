"""DRF serializers for the signal API."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from math import isfinite
from typing import Any, TypeVar, cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.regime.domain.asset_eligibility import get_eligibility_matrix
from apps.regime.domain.services_v2 import RegimeType
from apps.signal.domain.entities import SignalStatus
from shared.sanitization import sanitize_plain_text

SchemaDecorated = TypeVar("SchemaDecorated", bound=Callable[..., Any])
schema_string_field = cast(
    Callable[[SchemaDecorated], SchemaDecorated],
    extend_schema_field(OpenApiTypes.STR),
)

_ASSET_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._:-]{0,19}$")
_DIRECTION_CHOICES = ("LONG", "SHORT", "NEUTRAL")
_REGIME_CHOICES = tuple(item.value for item in RegimeType)
_STATUS_CHOICES = tuple(item.value for item in SignalStatus)
_MAX_LOGIC_LENGTH = 5000
_MAX_INVALIDATION_LENGTH = 2000


class StrictFieldsSerializer(serializers.Serializer[dict[str, Any]]):
    """Reject fields outside a signal request's published contract."""

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Validate request keys before normal DRF field conversion."""

        if isinstance(data, Mapping):
            unknown_fields = sorted(str(field_name) for field_name in set(data) - set(self.fields))
            if unknown_fields:
                raise serializers.ValidationError(
                    {"non_field_errors": [f"Unknown fields: {', '.join(unknown_fields)}"]}
                )
        return cast(dict[str, Any], super().to_internal_value(data))


def _validate_asset_code(value: str) -> str:
    """Normalize and validate one bounded asset identifier."""

    normalized = value.strip().upper()
    if not _ASSET_CODE_PATTERN.fullmatch(normalized):
        raise serializers.ValidationError("资产代码格式无效")
    return normalized


def _validate_asset_class(value: str) -> str:
    """Require an asset class published by the eligibility registry."""

    normalized = value.strip()
    if normalized not in get_eligibility_matrix():
        raise serializers.ValidationError("未知资产类别")
    return normalized


def _sanitize_logic_text(
    value: str,
    *,
    field_label: str,
    minimum_length: int,
    maximum_length: int,
) -> str:
    """Sanitize bounded logic text while preserving comparison operators."""

    normalized = sanitize_plain_text(value).replace("&lt;", "<").replace("&gt;", ">")
    if not minimum_length <= len(normalized) <= maximum_length:
        raise serializers.ValidationError(
            f"{field_label}长度必须为 {minimum_length} 到 {maximum_length} 个字符"
        )
    return normalized


class InvestmentSignalSerializer(serializers.Serializer[dict[str, Any]]):
    """Read serializer for investment signal payloads."""

    id = serializers.IntegerField(read_only=True)
    asset_code = serializers.CharField(read_only=True)
    asset_class = serializers.CharField(read_only=True)
    direction = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    logic_desc = serializers.CharField(read_only=True)
    invalidation_description = serializers.CharField(read_only=True, allow_blank=True)
    invalidation_rule = serializers.JSONField(read_only=True)
    human_readable_invalidation = serializers.SerializerMethodField()
    target_regime = serializers.CharField(read_only=True)
    rejection_reason = serializers.CharField(read_only=True, allow_blank=True)
    created_at = serializers.DateTimeField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)
    invalidated_at = serializers.DateTimeField(read_only=True, allow_null=True)
    backtest_performance_score = serializers.FloatField(read_only=True, allow_null=True)
    avg_backtest_return = serializers.FloatField(read_only=True, allow_null=True)

    @schema_string_field
    def get_human_readable_invalidation(self, obj: Any) -> str:
        """Return the human-readable invalidation description."""

        if isinstance(obj, Mapping):
            value = obj.get("human_readable_invalidation") or obj.get("invalidation_description")
            return value if isinstance(value, str) else ""
        formatter = getattr(obj, "get_human_readable_rules", None)
        if callable(formatter):
            value = formatter()
            return value if isinstance(value, str) else ""
        value = getattr(obj, "invalidation_description", "")
        return value if isinstance(value, str) else ""


class InvestmentSignalCreateSerializer(StrictFieldsSerializer):
    """Write serializer for creating investment signals."""

    asset_code = serializers.CharField(min_length=1, max_length=20)
    asset_class = serializers.CharField(min_length=1, max_length=50)
    direction = serializers.ChoiceField(choices=_DIRECTION_CHOICES)
    logic_desc = serializers.CharField(
        min_length=5,
        max_length=_MAX_LOGIC_LENGTH,
    )
    invalidation_logic = serializers.CharField(
        write_only=True,
        required=True,
        min_length=5,
        max_length=_MAX_INVALIDATION_LENGTH,
        help_text="自然语言描述的证伪逻辑，如 'PMI 跌破 50' 或 'CPI > 3 且 M2 < 10'",
    )
    target_regime = serializers.ChoiceField(choices=_REGIME_CHOICES)

    def validate_asset_code(self, value: str) -> str:
        """Normalize and validate the asset identifier."""

        return _validate_asset_code(value)

    def validate_asset_class(self, value: str) -> str:
        """Validate the asset class against the runtime eligibility registry."""

        return _validate_asset_class(value)

    def validate_invalidation_logic(self, value: str) -> str:
        """Validate and sanitize invalidation logic."""

        value = _sanitize_logic_text(
            value,
            field_label="证伪逻辑",
            minimum_length=5,
            maximum_length=_MAX_INVALIDATION_LENGTH,
        )

        quantifiable_keywords = [
            "跌破",
            "突破",
            "小于",
            "大于",
            "低于",
            "高于",
            "<",
            ">",
            "<=",
            ">=",
            "涨幅",
            "跌幅",
            "%",
        ]
        has_keyword = any(kw in value for kw in quantifiable_keywords)
        if not has_keyword:
            raise serializers.ValidationError(
                "证伪逻辑需要包含可量化条件，如：跌破、突破、<、>、涨幅、跌幅等"
            )

        return value

    def validate_logic_desc(self, value: str) -> str:
        """Validate and sanitize logic description."""

        return _sanitize_logic_text(
            value,
            field_label="信号逻辑",
            minimum_length=5,
            maximum_length=_MAX_LOGIC_LENGTH,
        )

    def create(self, validated_data: dict[str, Any]) -> dict[str, Any]:
        """Create a signal via application query services."""

        from apps.signal.application.query_services import create_investment_signal_payload

        try:
            return create_investment_signal_payload(**validated_data)
        except ValueError as exc:
            raise serializers.ValidationError({"invalidation_logic": str(exc)}) from exc


class InvestmentSignalUpdateSerializer(StrictFieldsSerializer):
    """Write serializer for updating investment signals."""

    asset_code = serializers.CharField(required=False, min_length=1, max_length=20)
    asset_class = serializers.CharField(required=False, min_length=1, max_length=50)
    direction = serializers.ChoiceField(
        choices=_DIRECTION_CHOICES,
        required=False,
    )
    logic_desc = serializers.CharField(
        required=False,
        min_length=5,
        max_length=_MAX_LOGIC_LENGTH,
    )
    invalidation_logic = serializers.CharField(
        required=False,
        min_length=5,
        max_length=_MAX_INVALIDATION_LENGTH,
    )
    target_regime = serializers.ChoiceField(
        choices=_REGIME_CHOICES,
        required=False,
    )

    def validate_asset_code(self, value: str) -> str:
        """Normalize and validate the asset identifier."""

        return _validate_asset_code(value)

    def validate_asset_class(self, value: str) -> str:
        """Validate the asset class against the runtime eligibility registry."""

        return _validate_asset_class(value)

    def validate_invalidation_logic(self, value: str) -> str:
        """Reuse create-time invalidation validation."""

        return InvestmentSignalCreateSerializer().validate_invalidation_logic(value)

    def validate_logic_desc(self, value: str) -> str:
        """Reuse create-time logic sanitization."""

        return _sanitize_logic_text(
            value,
            field_label="信号逻辑",
            minimum_length=5,
            maximum_length=_MAX_LOGIC_LENGTH,
        )


class InvestmentSignalValidateRequestSerializer(StrictFieldsSerializer):
    """Serializer for signal validation request"""

    signal_id = serializers.IntegerField(required=False, min_value=1)
    asset_code = serializers.CharField(
        required=True,
        min_length=1,
        max_length=20,
    )
    logic_desc = serializers.CharField(
        required=False,
        min_length=5,
        max_length=_MAX_LOGIC_LENGTH,
    )
    invalidation_logic = serializers.CharField(
        required=False,
        min_length=5,
        max_length=_MAX_INVALIDATION_LENGTH,
    )
    invalidation_threshold = serializers.FloatField(required=False)

    def validate_asset_code(self, value: str) -> str:
        """Normalize and validate the asset identifier."""

        return _validate_asset_code(value)

    def validate_invalidation_threshold(self, value: float) -> float:
        """Reject non-finite thresholds."""

        if not isfinite(value):
            raise serializers.ValidationError("证伪阈值必须是有限数值")
        return value


class InvestmentSignalValidateResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Serializer for signal validation response"""

    success = serializers.BooleanField()
    is_eligible = serializers.BooleanField()
    eligibility = serializers.CharField(allow_null=True)
    rejection_reason = serializers.CharField(allow_null=True)
    warnings = serializers.ListField(child=serializers.CharField(), allow_empty=True)


class SignalListQuerySerializer(StrictFieldsSerializer):
    """Serializer for signal list query parameters"""

    status = serializers.ChoiceField(
        choices=_STATUS_CHOICES,
        required=False,
        allow_null=True,
    )
    asset_class = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=50,
    )
    direction = serializers.ChoiceField(
        choices=_DIRECTION_CHOICES,
        required=False,
        allow_null=True,
    )
    search = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=200,
    )
    include_test = serializers.BooleanField(required=False, default=False)
    limit = serializers.IntegerField(default=50, min_value=1, max_value=500)

    def validate_asset_class(self, value: str | None) -> str | None:
        """Validate an optional asset-class filter."""

        return _validate_asset_class(value) if value is not None else None


class UnifiedSignalSerializer(serializers.Serializer[dict[str, Any]]):
    """Read serializer for unified signal payloads."""

    id = serializers.IntegerField(read_only=True)
    signal_date = serializers.CharField(read_only=True)
    signal_source = serializers.CharField(read_only=True)
    signal_source_display = serializers.CharField(read_only=True, required=False)
    signal_type = serializers.CharField(read_only=True)
    signal_type_display = serializers.CharField(read_only=True, required=False)
    asset_code = serializers.CharField(read_only=True)
    asset_name = serializers.CharField(read_only=True, allow_blank=True)
    target_weight = serializers.FloatField(read_only=True, allow_null=True)
    current_weight = serializers.FloatField(read_only=True, allow_null=True)
    priority = serializers.IntegerField(read_only=True)
    priority_display = serializers.CharField(read_only=True, required=False)
    is_executed = serializers.BooleanField(read_only=True)
    executed_at = serializers.DateTimeField(read_only=True, allow_null=True)
    reason = serializers.CharField(read_only=True)
    action_required = serializers.CharField(read_only=True, allow_blank=True)
    extra_data = serializers.JSONField(read_only=True)
    related_signal_id = serializers.CharField(read_only=True, allow_blank=True)
    created_at = serializers.DateTimeField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)
