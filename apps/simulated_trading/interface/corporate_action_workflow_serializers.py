"""Strict JSON contracts for the owner-facing simulated corporate-action workflow."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, cast

from rest_framework import serializers

MAX_CONTINUATION_TOKEN_LENGTH = 65536

CORPORATE_ACTION_WORKFLOW_ACTION_CHOICES: tuple[str, ...] = (
    "cash_entitlement",
    "cash_payment",
    "share_entitlement",
    "share_delivery",
    "share_sellable_release",
    "rights_not_exercised",
    "tax_assess",
    "tax_recognize",
    "tax_collect",
)


class _StrictObjectSerializer(serializers.Serializer[dict[str, Any]]):
    """Reject unknown JSON members and type coercions before DRF field conversion."""

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Accept only a JSON object whose keys belong to this declared contract."""
        if not isinstance(data, Mapping):
            raise serializers.ValidationError({"non_field_errors": ["请求必须为 JSON 对象。"]})
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({"non_field_errors": ["请求包含未支持字段。"]})
        self._validate_exact_types(cast(Mapping[str, object], data))
        return cast(dict[str, Any], super().to_internal_value(data))

    def _validate_exact_types(self, data: Mapping[str, object]) -> None:
        """Allow subclasses to enforce literal JSON types before conversion."""


def _normalized_account_id(value: object) -> int:
    """Read a canonical positive account identifier carried by a continuation."""
    if type(value) is int:
        account_id = value
    elif type(value) is str and value.isascii() and value.isdecimal():
        account_id = int(value)
        if str(account_id) != value:
            raise serializers.ValidationError({"account_id": "账户编号格式无效。"})
    else:
        raise serializers.ValidationError({"account_id": "账户编号格式无效。"})
    if account_id <= 0:
        raise serializers.ValidationError({"account_id": "账户编号格式无效。"})
    return account_id


class OwnerCorporateActionWorkflowReadRequestSerializer(_StrictObjectSerializer):
    """Declare an empty body for an exact owner workflow read."""


class OwnerCorporateActionWorkflowPrepareRequestSerializer(_StrictObjectSerializer):
    """Accept only a source event, one operation, and an optional settlement date."""

    account_id = serializers.IntegerField(required=False, min_value=1)
    event_id = serializers.CharField(
        required=True, allow_blank=False, trim_whitespace=False, max_length=192
    )
    action = serializers.ChoiceField(choices=CORPORATE_ACTION_WORKFLOW_ACTION_CHOICES)
    correction_mode = serializers.ChoiceField(
        choices=("ordinary", "correct_existing"), required=False, default="ordinary"
    )
    settlement_date = serializers.DateField(required=False, allow_null=False)

    def _validate_exact_types(self, data: Mapping[str, object]) -> None:
        """Require exact strings and canonical IDs; dates use ISO calendar strings."""
        if "account_id" in data:
            _normalized_account_id(data["account_id"])
        for key in ("event_id", "action"):
            if type(data.get(key)) is not str:
                raise serializers.ValidationError({key: "必须为字符串。"})
        if "correction_mode" in data and type(data["correction_mode"]) is not str:
            raise serializers.ValidationError({"correction_mode": "必须明确选择办理方式。"})
        if "settlement_date" in data:
            value = data["settlement_date"]
            if type(value) is not str:
                raise serializers.ValidationError({"settlement_date": "必须为 ISO 日期。"})
            try:
                parsed = date.fromisoformat(value)
            except ValueError as exc:
                raise serializers.ValidationError({"settlement_date": "必须为 ISO 日期。"}) from exc
            if parsed.isoformat() != value:
                raise serializers.ValidationError({"settlement_date": "必须为 ISO 日期。"})

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Normalize only a canonical path account ID and ISO date after strict checks."""
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        normalized: dict[str, object] = dict(cast(Mapping[str, object], data))
        if "account_id" in normalized:
            normalized["account_id"] = _normalized_account_id(normalized["account_id"])
        return super().to_internal_value(normalized)


class OwnerCorporateActionWorkflowConfirmRequestSerializer(_StrictObjectSerializer):
    """Confirm only an exact protected workflow continuation."""

    account_id = serializers.IntegerField(required=False, min_value=1)
    continuation_token = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=False,
        max_length=MAX_CONTINUATION_TOKEN_LENGTH,
    )
    confirmed = serializers.BooleanField(required=True)

    def _validate_exact_types(self, data: Mapping[str, object]) -> None:
        """Reject boolean-like numbers and strings before a write is reached."""
        if "account_id" in data:
            _normalized_account_id(data["account_id"])
        if type(data.get("continuation_token")) is not str:
            raise serializers.ValidationError({"continuation_token": "必须为字符串。"})
        if type(data.get("confirmed")) is not bool:
            raise serializers.ValidationError({"confirmed": "必须为明确选择的布尔值。"})

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Normalize a public account ID without accepting coercive input."""
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        normalized: dict[str, object] = dict(cast(Mapping[str, object], data))
        if "account_id" in normalized:
            normalized["account_id"] = _normalized_account_id(normalized["account_id"])
        return super().to_internal_value(normalized)


class OwnerCorporateActionWorkflowRefreshRequestSerializer(_StrictObjectSerializer):
    """Require an explicit owner confirmation for evidence refresh."""

    account_id = serializers.IntegerField(required=False, min_value=1)
    confirmed = serializers.BooleanField(required=True)

    def _validate_exact_types(self, data: Mapping[str, object]) -> None:
        """Reject nonliteral confirmation and malformed optional account identifiers."""
        if "account_id" in data:
            _normalized_account_id(data["account_id"])
        if type(data.get("confirmed")) is not bool:
            raise serializers.ValidationError({"confirmed": "必须为明确选择的布尔值。"})

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Normalize a public account ID without accepting coercive input."""
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        normalized: dict[str, object] = dict(cast(Mapping[str, object], data))
        if "account_id" in normalized:
            normalized["account_id"] = _normalized_account_id(normalized["account_id"])
        return super().to_internal_value(normalized)


class _StrictNullableTextField(serializers.Field[str | None, object, str | None, Any]):
    """Preserve money strings exactly and reject numeric formatting or coercion."""

    def __init__(self, **kwargs: Any) -> None:
        """Allow explicit null values for unknown monetary amounts."""
        kwargs["allow_null"] = True
        super().__init__(**kwargs)

    def to_internal_value(self, data: object) -> str | None:
        """Validate an exact string or null input value."""
        if data is None or type(data) is str:
            return data
        raise serializers.ValidationError("必须为字符串或 null。")

    def to_representation(self, value: object) -> str | None:
        """Serialize only exact string or null outputs, without numeric coercion."""
        if value is None or type(value) is str:
            return value
        raise serializers.ValidationError("响应金额必须为字符串或 null。")


class OwnerCorporateActionWorkflowEventRowSerializer(_StrictObjectSerializer):
    """Publish only the safe source dates, identity, status, and blocking summary."""

    account_id = serializers.IntegerField(min_value=1)
    event_id = serializers.CharField(allow_blank=False)
    asset_code = serializers.CharField(allow_blank=True)
    title = serializers.CharField(allow_blank=True)
    event_type = serializers.CharField(allow_blank=True)
    announced_on = serializers.CharField(allow_null=True, allow_blank=True)
    record_date = serializers.CharField(allow_null=True, allow_blank=True)
    effective_date = serializers.CharField(allow_null=True, allow_blank=True)
    source_observed_at = serializers.CharField(allow_null=True, allow_blank=True)
    status = serializers.CharField(allow_blank=True)
    blocking_reason = serializers.CharField(allow_null=True, allow_blank=True)

    def _validate_exact_types(self, data: Mapping[str, object]) -> None:
        """Require exact public strings and integer row account binding."""
        if type(data.get("account_id")) is not int:
            raise serializers.ValidationError({"account_id": "必须为整数。"})
        for key, value in data.items():
            if key == "account_id":
                continue
            if value is not None and type(value) is not str:
                raise serializers.ValidationError({key: "必须为字符串或 null。"})


class OwnerCorporateActionWorkflowAuditReceiptRowSerializer(_StrictObjectSerializer):
    """Publish traceable receipt details without raw payloads or source hashes."""

    receipt_id = serializers.CharField(allow_blank=False)
    recorded_at = serializers.CharField(allow_blank=False)
    asset_code = serializers.CharField(allow_blank=True)
    stage_label = serializers.CharField(allow_blank=True)
    cash_delta = _StrictNullableTextField()
    share_delta = _StrictNullableTextField()
    summary = serializers.CharField(allow_blank=True)

    def _validate_exact_types(self, data: Mapping[str, object]) -> None:
        """Reject nonstring receipt identity, clock, labels, or summaries."""
        for key, value in data.items():
            if key in {"cash_delta", "share_delta"}:
                if value is not None and type(value) is not str:
                    raise serializers.ValidationError({key: "必须为金额字符串或 null。"})
            elif type(value) is not str:
                raise serializers.ValidationError({key: "必须为字符串。"})


class OwnerCorporateActionWorkflowResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Allowlist safe workflow facts and keep continuation material optional."""

    account_id = serializers.IntegerField(min_value=1)
    outcome = serializers.ChoiceField(choices=("success", "partial", "noop", "blocked", "failed"))
    summary = serializers.CharField(allow_blank=True)
    blocking_reason = serializers.CharField(allow_null=True, allow_blank=True)
    source_observed_at = serializers.CharField(allow_null=True, allow_blank=True)
    checked_at = serializers.CharField(allow_null=True, allow_blank=True)
    freshness_status = serializers.CharField()
    reliability_status = serializers.CharField()
    must_not_use_for_decision = serializers.BooleanField()
    book_cash = _StrictNullableTextField()
    spendable_cash = _StrictNullableTextField()
    net_asset_value = _StrictNullableTextField()
    dividend_receivable = _StrictNullableTextField()
    share_receivable = _StrictNullableTextField()
    tax_payable = _StrictNullableTextField()
    events = OwnerCorporateActionWorkflowEventRowSerializer(many=True)
    audit_receipts = OwnerCorporateActionWorkflowAuditReceiptRowSerializer(many=True)
    continuation = serializers.JSONField(required=False)
