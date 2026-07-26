"""DRF serializers for config center."""

from __future__ import annotations

import re
from typing import Any, cast

from rest_framework import serializers

ALPHA_UNIVERSE_SOURCE_TYPES = {
    "manual",
    "csv",
    "data_center_filter",
    "tushare_index",
}


class QlibRuntimeConfigSerializer(serializers.Serializer[dict[str, Any]]):
    configured = serializers.BooleanField(read_only=True)
    enabled = serializers.BooleanField(required=False)
    provider_uri = serializers.CharField(required=False, allow_blank=True)
    region = serializers.CharField(required=False, max_length=10)
    model_root = serializers.CharField(required=False, allow_blank=True)
    default_universe = serializers.CharField(required=False, max_length=50)
    default_feature_set_id = serializers.CharField(required=False, max_length=50)
    default_label_id = serializers.CharField(required=False, max_length=50)
    train_queue_name = serializers.CharField(required=False, max_length=64)
    infer_queue_name = serializers.CharField(required=False, max_length=64)
    allow_auto_activate = serializers.BooleanField(required=False)
    alpha_fixed_provider = serializers.CharField(required=False, allow_blank=True, max_length=20)
    alpha_pool_mode = serializers.CharField(required=False, max_length=32)
    active_model = serializers.DictField(read_only=True)
    training_task_running = serializers.BooleanField(read_only=True)
    latest_run_status = serializers.CharField(read_only=True, allow_null=True)
    validation_errors = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )


class QlibTrainingProfileSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.IntegerField(required=False)
    profile_key = serializers.CharField(max_length=64)
    name = serializers.CharField(max_length=120)
    model_name = serializers.CharField(max_length=100)
    model_type = serializers.CharField(max_length=50)
    universe = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    start_date = serializers.DateField(required=False, allow_null=True, default=None)
    end_date = serializers.DateField(required=False, allow_null=True, default=None)
    feature_set_id = serializers.CharField(
        max_length=50, required=False, allow_blank=True, default=""
    )
    label_id = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    learning_rate = serializers.FloatField(required=False, allow_null=True, default=None)
    epochs = serializers.IntegerField(required=False, allow_null=True, default=None, min_value=1)
    model_params = serializers.DictField(required=False, default=dict)
    extra_train_config = serializers.DictField(required=False, default=dict)
    activate_after_train = serializers.BooleanField(required=False, default=False)
    is_active = serializers.BooleanField(required=False, default=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class AlphaUniverseConfigSerializer(serializers.Serializer[dict[str, Any]]):
    universe_id = serializers.RegexField(
        regex=r"^[a-z0-9][a-z0-9_\-]{1,63}$",
        max_length=64,
        help_text="自定义 Alpha/Qlib 股票池 ID，例如 all_a_share 或 star_market",
    )
    name = serializers.CharField(max_length=120)
    source_type = serializers.ChoiceField(choices=sorted(ALPHA_UNIVERSE_SOURCE_TYPES))
    stock_codes = serializers.JSONField(required=False, default=cast(Any, list))
    filters = serializers.DictField(required=False, default=dict)
    is_active = serializers.BooleanField(required=False, default=True)
    description = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs["universe_id"] = str(attrs["universe_id"]).strip().lower()
        source_type = attrs.get("source_type")
        stock_codes = _parse_stock_codes(attrs.get("stock_codes") or [])
        attrs["stock_codes"] = stock_codes
        filters = attrs.get("filters") or {}
        if source_type in {"manual", "csv"} and not stock_codes:
            raise serializers.ValidationError({"stock_codes": "手工或 CSV 股票池至少需要一个代码"})
        if source_type == "data_center_filter" and not isinstance(filters, dict):
            raise serializers.ValidationError({"filters": "filters 必须是 JSON object"})
        if source_type == "tushare_index":
            index_code = str(filters.get("index_code") or "").strip().upper()
            if re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", index_code) is None:
                raise serializers.ValidationError(
                    {"filters": "Tushare 指数股票池需要合法的 index_code"}
                )
            attrs["filters"] = {**filters, "index_code": index_code}
        return attrs


def _parse_stock_codes(value: Any) -> list[str]:
    if isinstance(value, str):
        normalized = value.replace(",", "\n").replace("，", "\n").replace(";", "\n")
        codes: list[str] = []
        for line in normalized.splitlines():
            codes.extend(part.strip() for part in line.split() if part.strip())
        return codes
    if isinstance(value, list | tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    raise serializers.ValidationError({"stock_codes": "stock_codes 必须是数组或分隔字符串"})


class QlibTrainingRunTriggerSerializer(serializers.Serializer[dict[str, Any]]):
    profile_key = serializers.CharField(required=False, allow_blank=True, default="")
    model_name = serializers.CharField(required=False, allow_blank=True, max_length=100)
    model_type = serializers.CharField(required=False, allow_blank=True, max_length=50)
    universe = serializers.CharField(required=False, allow_blank=True, max_length=50)
    start_date = serializers.DateField(required=False, allow_null=True, default=None)
    end_date = serializers.DateField(required=False, allow_null=True, default=None)
    feature_set_id = serializers.CharField(required=False, allow_blank=True, max_length=50)
    label_id = serializers.CharField(required=False, allow_blank=True, max_length=50)
    learning_rate = serializers.FloatField(required=False, allow_null=True, default=None)
    epochs = serializers.IntegerField(required=False, allow_null=True, default=None, min_value=1)
    model_params = serializers.DictField(required=False, default=dict)
    extra_train_config = serializers.DictField(required=False, default=dict)
    activate = serializers.BooleanField(required=False)
