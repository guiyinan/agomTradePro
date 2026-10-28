"""Bounded JSON inputs and explicit receipts for fee evidence and corrections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from rest_framework import serializers

from apps.simulated_trading.application.fee_correction import FeeCorrectionRequest
from apps.simulated_trading.application.fee_correction_confirmation import (
    FeeCorrectionConfirmationCommand,
)
from apps.simulated_trading.application.fee_correction_evidence import (
    MAX_UPLOAD_BYTES,
    FeeCorrectionEvidenceUploadCommand,
)
from apps.simulated_trading.application.fee_correction_preview import (
    FeeCorrectionPreviewCommand,
    FeeCorrectionRecoveryPreviewCommand,
)
from apps.simulated_trading.application.fee_correction_recovery import (
    FeeCorrectionRecoveryCommand,
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


class _FeeEvidenceMaterialSerializer(_StrictFeeInputSerializer):
    """Accept UTF-8 CSV text without trimming, newline conversion or lossy decoding."""

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


class FeeEvidenceUploadRequestSerializer(_FeeEvidenceMaterialSerializer):
    """Bind material to the caller's explicit correction revision."""

    expected_revision = serializers.IntegerField(min_value=0)
    expected_predecessor_id = serializers.IntegerField(min_value=1, allow_null=True)

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


class FeeCorrectionPreviewRequestSerializer(_FeeEvidenceMaterialSerializer):
    """Accept original material while the owner service binds the ledger revision."""

    def to_command(
        self, *, account_id: int, trade_id: int, idempotency_key: str
    ) -> FeeCorrectionPreviewCommand:
        """Narrow the validated material without accepting financial or actor fields."""

        return FeeCorrectionPreviewCommand(
            account_id=account_id,
            trade_id=trade_id,
            idempotency_key=idempotency_key,
            original_filename=cast(str, self.validated_data["original_filename"]),
            content=cast(str, self.validated_data["csv_text"]).encode("utf-8"),
            attestation_acknowledged=cast(bool, self.validated_data["attestation_acknowledged"]),
        )


class FeeCorrectionRecoveryPreviewRequestSerializer(_StrictFeeInputSerializer):
    """Select one existing immutable material without accepting a ledger key."""

    source_locator = serializers.CharField(max_length=36, trim_whitespace=False)

    def to_command(
        self, *, account_id: int, trade_id: int, idempotency_key: str
    ) -> FeeCorrectionRecoveryPreviewCommand:
        """Bind the exact stored source to this request's transport key."""

        return FeeCorrectionRecoveryPreviewCommand(
            account_id=account_id,
            trade_id=trade_id,
            idempotency_key=idempotency_key,
            source_locator=cast(str, self.validated_data["source_locator"]),
        )


class FeeCorrectionRecoveryQuerySerializer(serializers.Serializer[dict[str, Any]]):
    """Parse only the documented bounded recovery page parameters."""

    limit = serializers.IntegerField(required=False, default=20, min_value=1, max_value=100)
    cursor = serializers.CharField(required=False, max_length=36, trim_whitespace=False)

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Reject unknown and repeated query parameters instead of choosing one."""

        if not isinstance(data, Mapping) or set(data) - set(self.fields):
            raise serializers.ValidationError(
                {"non_field_errors": ["费用更正恢复查询包含未知参数或不是对象。"]}
            )
        getlist = getattr(data, "getlist", None)
        if callable(getlist) and any(len(getlist(name)) != 1 for name in data):
            raise serializers.ValidationError(
                {"non_field_errors": ["费用更正恢复查询参数不能重复。"]}
            )
        return cast(dict[str, Any], super().to_internal_value(data))

    def to_command(self, *, account_id: int, trade_id: int) -> FeeCorrectionRecoveryCommand:
        """Bind paging input to the path's account and trade identity."""

        return FeeCorrectionRecoveryCommand(
            account_id=account_id,
            trade_id=trade_id,
            limit=cast(int, self.validated_data["limit"]),
            cursor=cast(str | None, self.validated_data.get("cursor")),
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


class FeeCorrectionConfirmationRequestSerializer(_StrictFeeInputSerializer):
    """Accept only the server-prepared opaque confirmation context."""

    confirmation_token = serializers.CharField(max_length=32768, trim_whitespace=False)

    def to_command(
        self, *, account_id: int, trade_id: int, idempotency_key: str
    ) -> FeeCorrectionConfirmationCommand:
        """Bind the hidden context to path scope and the original request header."""

        return FeeCorrectionConfirmationCommand(
            account_id=account_id,
            trade_id=trade_id,
            idempotency_key=idempotency_key,
            confirmation_token=cast(str, self.validated_data["confirmation_token"]),
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
    message = serializers.CharField(required=False)


class FeeCorrectionHeadSerializer(serializers.Serializer[dict[str, Any]]):
    """Expose validated version state and optional exact-key readback."""

    account_id = serializers.IntegerField()
    trade_id = serializers.IntegerField()
    revision = serializers.IntegerField()
    expected_predecessor_id = serializers.IntegerField(allow_null=True)
    as_of = serializers.DateTimeField()
    request_receipt = FeeCorrectionReceiptSerializer(allow_null=True)


class FeeCorrectionHeadQuerySerializer(serializers.Serializer[dict[str, Any]]):
    """Accept one optional immutable evidence locator for read-only recovery."""

    source_locator = serializers.UUIDField(required=False)

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Reject undocumented query fields instead of silently ignoring them."""

        if not isinstance(data, Mapping) or set(data) - set(self.fields):
            raise serializers.ValidationError(
                {"non_field_errors": ["费用更正查询包含未知字段或不是对象。"]}
            )
        return cast(dict[str, Any], super().to_internal_value(data))


class FeeCorrectionHeadResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Describe the owned trade's correction head without exposing private evidence."""

    success = serializers.BooleanField()
    outcome = serializers.ChoiceField(choices=("success", "partial"))
    message = serializers.CharField()
    head = FeeCorrectionHeadSerializer()


class FeeCorrectionRecoveryItemSerializer(serializers.Serializer[dict[str, Any]]):
    """Expose a bounded recovery classification without the ledger key or raw source."""

    source_locator = serializers.CharField()
    content_sha256 = serializers.CharField()
    payload_sha256 = serializers.CharField()
    stored_at = serializers.DateTimeField()
    expected_revision = serializers.IntegerField()
    expected_predecessor_id = serializers.IntegerField(allow_null=True)
    binding_policy_version = serializers.IntegerField()
    current_policy_version = serializers.IntegerField(allow_null=True)
    state = serializers.ChoiceField(choices=("completed", "unresolved", "fenced", "unknown"))
    reason_code = serializers.CharField(allow_null=True)


class FeeCorrectionRecoveryPageSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialize one owner-visible recovery page and its explicit continuation cursor."""

    account_id = serializers.IntegerField()
    trade_id = serializers.IntegerField()
    items = FeeCorrectionRecoveryItemSerializer(many=True)
    has_more = serializers.BooleanField()
    next_cursor = serializers.CharField(allow_null=True)


class FeeCorrectionRecoveryResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Describe successful discovery separately from each material's lifecycle state."""

    success = serializers.BooleanField()
    outcome = serializers.ChoiceField(choices=("success",))
    recovery = FeeCorrectionRecoveryPageSerializer()


class _FeeComponentsSerializer(serializers.Serializer[dict[str, Any]]):
    """Render exact Domain fee values as decimal strings, never JSON floats."""

    commission = serializers.DecimalField(max_digits=15, decimal_places=2, coerce_to_string=True)
    transfer_fee = serializers.DecimalField(max_digits=15, decimal_places=2, coerce_to_string=True)
    stamp_duty = serializers.DecimalField(max_digits=15, decimal_places=2, coerce_to_string=True)


class _FeeDeltaSerializer(_FeeComponentsSerializer):
    """Render the signed cash impact using the same exact monetary representation."""

    total_fee_delta = serializers.DecimalField(
        max_digits=15, decimal_places=2, coerce_to_string=True
    )
    cash_delta = serializers.DecimalField(max_digits=15, decimal_places=2, coerce_to_string=True)


class FeeCorrectionPreviewSerializer(serializers.Serializer[dict[str, Any]]):
    """Expose verified amounts and their original binding without authorizing posting."""

    account_id = serializers.IntegerField()
    trade_id = serializers.IntegerField()
    asset_code = serializers.CharField()
    ledger_currency = serializers.CharField()
    expected_revision = serializers.IntegerField()
    expected_predecessor_id = serializers.IntegerField(allow_null=True)
    source_locator = serializers.CharField()
    content_sha256 = serializers.CharField()
    payload_sha256 = serializers.CharField()
    assurance_class = serializers.CharField()
    source_observed_at = serializers.DateTimeField()
    verified_at = serializers.DateTimeField()
    stored_at = serializers.DateTimeField()
    as_of = serializers.DateTimeField()
    previous_fee_components = _FeeComponentsSerializer()
    revised_fee_components = _FeeComponentsSerializer()
    delta = _FeeDeltaSerializer()


class _FeeConfirmationInputSerializer(serializers.Serializer[dict[str, Any]]):
    """Document the server-generated hidden scope and opaque confirmation token."""

    account_id = serializers.CharField()
    trade_id = serializers.CharField()
    confirmation_token = serializers.CharField()


class _FeeConfirmationContinuationSerializer(serializers.Serializer[dict[str, Any]]):
    """Expose the fixed confirmation action and its original UTC expiry."""

    action_key = serializers.ChoiceField(choices=("simulated-trading.fee-correction-confirm",))
    input = _FeeConfirmationInputSerializer()
    expires_at = serializers.CharField()


class FeeCorrectionPreviewResponseSerializer(serializers.Serializer[dict[str, Any]]):
    """Separate a non-posted preview from the receipt of an already completed request."""

    success = serializers.BooleanField()
    outcome = serializers.ChoiceField(choices=("success", "noop"))
    status = serializers.ChoiceField(choices=("preview", "already_applied"))
    preview = FeeCorrectionPreviewSerializer(allow_null=True)
    receipt = FeeCorrectionReceiptSerializer(allow_null=True)
    assurance_notice = serializers.CharField()
    message = serializers.CharField()
    continuation = _FeeConfirmationContinuationSerializer(required=False)
