"""Explicit JSON fields for owner-attested evidence eligibility settings."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from rest_framework import serializers

from apps.simulated_trading.application.fee_correction_policy import FeeCorrectionPolicyCommand

from .m1_risk_policy_serializers import ExplicitAwareDateTimeField


class FeeCorrectionPolicyRequestSerializer(serializers.Serializer[dict[str, Any]]):
    """Require explicit replacement settings without coercing consent or identity."""

    expected_version = serializers.IntegerField(min_value=0)
    enabled = serializers.BooleanField()
    allow_operator_attested_upload = serializers.BooleanField()
    ledger_currency = serializers.CharField(max_length=3, allow_blank=True, trim_whitespace=False)
    valid_from = ExplicitAwareDateTimeField(allow_null=True)
    valid_until = ExplicitAwareDateTimeField(allow_null=True)
    attestation_acknowledged = serializers.BooleanField()

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Reject extra actor fields and ambiguous JSON booleans or versions."""

        if not isinstance(data, Mapping) or set(data) - set(self.fields):
            raise serializers.ValidationError({"non_field_errors": ["请求只允许明示的策略字段。"]})
        for name in ("enabled", "allow_operator_attested_upload", "attestation_acknowledged"):
            if name in data and type(data[name]) is not bool:
                raise serializers.ValidationError({name: "必须为 JSON 布尔值。"})
        if "expected_version" in data and type(data["expected_version"]) is not int:
            raise serializers.ValidationError({"expected_version": "必须为 JSON 整数。"})
        if "ledger_currency" in data and type(data["ledger_currency"]) is not str:
            raise serializers.ValidationError({"ledger_currency": "必须为币种字符串。"})
        return cast(dict[str, Any], super().to_internal_value(data))

    def to_command(self, account_id: int) -> FeeCorrectionPolicyCommand:
        """Narrow validated HTTP data before crossing the Application boundary."""

        data = self.validated_data
        return FeeCorrectionPolicyCommand(
            account_id=account_id,
            expected_version=cast(int, data["expected_version"]),
            enabled=cast(bool, data["enabled"]),
            allow_operator_attested_upload=cast(bool, data["allow_operator_attested_upload"]),
            ledger_currency=cast(str, data["ledger_currency"]),
            valid_from=cast(datetime | None, data["valid_from"]),
            valid_until=cast(datetime | None, data["valid_until"]),
            attestation_acknowledged=cast(bool, data["attestation_acknowledged"]),
        )


class FeeCorrectionPolicyStateSerializer(serializers.Serializer[dict[str, Any]]):
    """Expose policy state and the limited assurance that the owner may enable."""

    account_id = serializers.IntegerField()
    version = serializers.IntegerField()
    enabled = serializers.BooleanField()
    allow_operator_attested_upload = serializers.BooleanField()
    ledger_currency = serializers.CharField(allow_blank=True)
    valid_from = serializers.DateTimeField(allow_null=True)
    valid_until = serializers.DateTimeField(allow_null=True)
    updated_by_id = serializers.IntegerField(allow_null=True)
    assurance_class = serializers.CharField()
    assurance_notice = serializers.CharField()


class FeeCorrectionPolicyResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Document the policy response independently of persistence models."""

    success = serializers.BooleanField()
    policy = FeeCorrectionPolicyStateSerializer()
