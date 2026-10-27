"""Bounded JSON inputs and explicit receipts for fee evidence and corrections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from rest_framework import serializers

from apps.simulated_trading.application.fee_correction import FeeCorrectionRequest
from apps.simulated_trading.application.fee_correction_evidence import (
    MAX_UPLOAD_BYTES,
    FeeCorrectionEvidenceUploadCommand,
)


class _StrictFeeInputSerializer(serializers.Serializer[dict[str, Any]]):
    """Reject extra scope fields and coercion before interpreting financial inputs."""

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Preserve exact JSON booleans, integers and strings at this boundary."""

        if not isinstance(data, Mapping) or set(data) - set(self.fields):
            raise serializers.ValidationError(
                {"non_field_errors": ["费用请求包含未知字段或不是对象。"]}
            )
        for name, field in self.fields.items():
            if name not in data or (data[name] is None and field.allow_null):
                continue
            if isinstance(field, serializers.BooleanField) and type(data[name]) is not bool:
                raise serializers.ValidationError({name: "必须为 JSON 布尔值。"})
            if isinstance(field, serializers.IntegerField) and type(data[name]) is not int:
                raise serializers.ValidationError({name: "必须为 JSON 整数。"})
            if isinstance(field, serializers.CharField) and type(data[name]) is not str:
                raise serializers.ValidationError({name: "必须为字符串。"})
        return cast(dict[str, Any], super().to_internal_value(data))


class FeeEvidenceUploadRequestSerializer(_StrictFeeInputSerializer):
    """Accept UTF-8 CSV text without trimming, newline conversion or lossy decoding."""

    expected_revision = serializers.IntegerField(min_value=0)
    expected_predecessor_id = serializers.IntegerField(min_value=1, allow_null=True)
    original_filename = serializers.CharField(max_length=255, trim_whitespace=False)
    csv_text = serializers.CharField(max_length=MAX_UPLOAD_BYTES, trim_whitespace=False)
    attestation_acknowledged = serializers.BooleanField()

    def validate_csv_text(self, value: str) -> str:
        """Enforce the original byte budget before calling the evidence store."""

        try:
            content = value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise serializers.ValidationError("材料必须是可无损编码的 UTF-8 CSV。") from error
        if not content or len(content) > MAX_UPLOAD_BYTES:
            raise serializers.ValidationError("材料为空或超过允许的字节上限。")
        return value

    def to_command(
        self, *, account_id: int, trade_id: int, idempotency_key: str
    ) -> FeeCorrectionEvidenceUploadCommand:
        """Bind validated material to path identities and the original request key."""

        data = self.validated_data
        return FeeCorrectionEvidenceUploadCommand(
            account_id=account_id,
            trade_id=trade_id,
            expected_revision=cast(int, data["expected_revision"]),
            expected_predecessor_id=cast(int | None, data["expected_predecessor_id"]),
            idempotency_key=idempotency_key,
            original_filename=cast(str, data["original_filename"]),
            content=cast(str, data["csv_text"]).encode("utf-8"),
            attestation_acknowledged=cast(bool, data["attestation_acknowledged"]),
        )


class FeeCorrectionRequestSerializer(_StrictFeeInputSerializer):
    """Accept only a server-issued source locator and explicit prior revision."""

    source_locator = serializers.CharField(max_length=512, trim_whitespace=False)
    expected_revision = serializers.IntegerField(min_value=0)

    def to_request(
        self, *, account_id: int, trade_id: int, idempotency_key: str
    ) -> FeeCorrectionRequest:
        """Narrow the JSON request; monetary values must come from stored evidence."""

        return FeeCorrectionRequest(
            account_id=account_id,
            trade_id=trade_id,
            idempotency_key=idempotency_key,
            expected_revision=cast(int, self.validated_data["expected_revision"]),
            source_locator=cast(str, self.validated_data["source_locator"]),
        )


class FeeEvidenceReceiptSerializer(serializers.Serializer[dict[str, Any]]):
    """Describe storage identity without claiming source or posting qualification."""

    source_locator = serializers.CharField()
    content_sha256 = serializers.CharField()
    payload_sha256 = serializers.CharField()
    assurance_class = serializers.CharField()
    stored_at = serializers.DateTimeField()


class FeeEvidenceUploadResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Expose the persisted material receipt separately from a correction receipt."""

    success = serializers.BooleanField()
    evidence = FeeEvidenceReceiptSerializer()
    assurance_notice = serializers.CharField()


class FeeCorrectionReceiptSerializer(serializers.Serializer[dict[str, Any]]):
    """Expose the exact persisted correction identity and replay result."""

    event_id = serializers.IntegerField()
    account_id = serializers.IntegerField()
    trade_id = serializers.IntegerField()
    revision = serializers.IntegerField()
    payload_hash = serializers.CharField()
    replayed = serializers.BooleanField()


class FeeCorrectionResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Return the committed receipt without recomputing monetary projections."""

    success = serializers.BooleanField()
    receipt = FeeCorrectionReceiptSerializer()


class FeeCorrectionHeadSerializer(serializers.Serializer[dict[str, Any]]):
    """Expose validated version state and optional exact-key readback."""

    account_id = serializers.IntegerField()
    trade_id = serializers.IntegerField()
    revision = serializers.IntegerField()
    expected_predecessor_id = serializers.IntegerField(allow_null=True)
    as_of = serializers.DateTimeField()
    request_receipt = FeeCorrectionReceiptSerializer(allow_null=True)


class FeeCorrectionHeadResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Describe the owned trade's correction head without exposing private evidence."""

    success = serializers.BooleanField()
    head = FeeCorrectionHeadSerializer()
