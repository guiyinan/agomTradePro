"""Explicit DRF request serializers for broker execution APIs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from rest_framework import serializers


class PreviewCommitSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate the shared preview/commit envelope."""

    preview_only = serializers.BooleanField(default=True)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    idempotency_key = serializers.CharField(required=False, allow_blank=False, max_length=128)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.get("preview_only", True) and not attrs.get("idempotency_key"):
            raise serializers.ValidationError({"idempotency_key": "Required for commit."})
        return attrs


class OrderActionSerializer(PreviewCommitSerializer):
    """Validate preview/commit order actions with optimistic concurrency."""

    expected_version = serializers.IntegerField(min_value=0, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        if not attrs.get("preview_only", True) and "expected_version" not in attrs:
            raise serializers.ValidationError(
                {"expected_version": "Required for order-action commit."}
            )
        return attrs


class KillSwitchSerializer(PreviewCommitSerializer):
    """Validate account/global stop and resume requests."""

    account_id = serializers.IntegerField(min_value=0, default=0)
    active = serializers.BooleanField()
    reason = serializers.CharField(max_length=1000)
    reauth = serializers.DictField(required=False, write_only=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        if (
            not attrs.get("preview_only", True)
            and not attrs.get("active", False)
            and not isinstance(attrs.get("reauth"), dict)
        ):
            raise serializers.ValidationError(
                {"reauth": "Password reauthentication is required for resume."}
            )
        reauth = attrs.get("reauth")
        if isinstance(reauth, dict):
            if set(reauth) != {"method", "credential"}:
                raise serializers.ValidationError(
                    {"reauth": "Only method and credential are accepted."}
                )
            if str(reauth.get("method") or "").lower() != "password":
                raise serializers.ValidationError(
                    {"reauth": "Only password reauthentication is supported."}
                )
            if not str(reauth.get("credential") or ""):
                raise serializers.ValidationError({"reauth": "Password credential is required."})
        return attrs


class AdvisorDraftSerializer(PreviewCommitSerializer):
    """Validate current advisor-sheet draft generation."""

    account_id = serializers.IntegerField(min_value=1)
    expected_plan_digest = serializers.RegexField(
        r"^[0-9a-f]{64}$",
        required=False,
        allow_blank=False,
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        if not attrs.get("preview_only", True) and not attrs.get("expected_plan_digest"):
            raise serializers.ValidationError({"expected_plan_digest": "Required for commit."})
        return attrs


class ReconciliationResolutionSerializer(PreviewCommitSerializer):
    """Validate reconciliation resolution workflow."""

    resolution = serializers.ChoiceField(
        choices=["accept_broker_fact", "manual_adjustment", "verified_no_change", "escalate"]
    )
    reason = serializers.CharField(max_length=1000)


class AgentBindingSerializer(PreviewCommitSerializer):
    """Validate an Agent/account binding."""

    user_id = serializers.IntegerField(min_value=1)
    account_id = serializers.IntegerField(min_value=1)
    agent_id = serializers.RegexField(r"^[A-Za-z0-9._-]{3,64}$")
    display_name = serializers.CharField(required=False, max_length=100)
    broker_account_ref = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=128,
        write_only=True,
    )
    broker_account_mask = serializers.CharField(required=False, max_length=32)
    account_type = serializers.ChoiceField(choices=["STOCK"], default="STOCK")
    is_active = serializers.BooleanField(default=True)
    reason = serializers.CharField(max_length=1000)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        if attrs.get("is_active", True) and not attrs.get("broker_account_ref"):
            raise serializers.ValidationError(
                {"broker_account_ref": "Required when activating a binding."}
            )
        return attrs


class AccountAccessSerializer(PreviewCommitSerializer):
    """Validate an administrator-managed account permission grant."""

    user_id = serializers.IntegerField(min_value=1)
    account_id = serializers.IntegerField(min_value=1)
    can_approve = serializers.BooleanField(default=False)
    can_trade = serializers.BooleanField(default=False)
    is_active = serializers.BooleanField(default=True)
    reason = serializers.CharField(max_length=1000)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        if attrs.get("is_active", True) and not (
            attrs.get("can_approve", False) or attrs.get("can_trade", False)
        ):
            raise serializers.ValidationError("An active grant must allow approval or trading.")
        return attrs


class CredentialRotateSerializer(PreviewCommitSerializer):
    """Validate one-time Agent credential creation."""

    agent_id = serializers.CharField(max_length=64)
    scopes = serializers.ListField(
        child=serializers.CharField(max_length=64), allow_empty=False, max_length=16
    )
    account_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=50,
    )
    expires_at = serializers.DateTimeField()


class CredentialRevokeSerializer(PreviewCommitSerializer):
    """Validate immediate Agent credential revocation."""

    reason = serializers.CharField(max_length=1000)


class ConnectionSyncSerializer(PreviewCommitSerializer):
    """Validate an asynchronous Agent connection/full-sync request."""

    agent_id = serializers.RegexField(r"^[A-Za-z0-9._-]{3,64}$")
    reason = serializers.CharField(max_length=1000)


class ExecutionSettingsSerializer(PreviewCommitSerializer):
    """Validate account execution limits and allow-list."""

    auto_execution_enabled = serializers.BooleanField(required=False)
    max_single_order_amount = serializers.DecimalField(
        max_digits=18, decimal_places=2, min_value=0, required=False
    )
    daily_order_amount_limit = serializers.DecimalField(
        max_digits=18, decimal_places=2, min_value=0, required=False
    )
    max_position_count = serializers.IntegerField(min_value=1, max_value=1000, required=False)
    max_snapshot_age_seconds = serializers.IntegerField(
        min_value=10, max_value=3600, required=False
    )
    price_deviation_limit_pct = serializers.DecimalField(
        max_digits=7, decimal_places=4, min_value=0, max_value=1, required=False
    )
    allowed_trading_windows = serializers.ListField(
        child=serializers.RegexField(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$"),
        required=False,
        min_length=1,
        max_length=8,
    )
    enforce_trading_session = serializers.BooleanField(required=False)
    allowed_symbols = serializers.ListField(
        child=serializers.CharField(max_length=32), required=False, max_length=1000
    )
    reason = serializers.CharField(max_length=1000)


class AgentHeartbeatSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate Agent health payload."""

    contract_version = serializers.ChoiceField(choices=["1.0"])
    observed_at = serializers.CharField(required=False, max_length=64)
    qmt_connected = serializers.BooleanField()
    account_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        max_length=50,
    )
    agent_version = serializers.CharField(max_length=32)
    qmt_version = serializers.CharField(required=False, allow_blank=True, max_length=64)
    dry_run = serializers.BooleanField(default=True)
    message = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate_observed_at(self, value: str) -> str:
        """Require an explicit timezone without replacing the Agent source clock."""

        try:
            observed_at = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise serializers.ValidationError("observed_at must be an ISO datetime") from exc
        if observed_at.tzinfo is None:
            raise serializers.ValidationError("observed_at must include a timezone")
        return observed_at.isoformat()


class AgentLeaseSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate Agent lease request."""

    contract_version = serializers.ChoiceField(choices=["1.0"])
    limit = serializers.IntegerField(min_value=1, max_value=50, default=10)
    lease_seconds = serializers.IntegerField(min_value=10, max_value=120, default=30)


class AgentSubmittingSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate pre-submit acknowledgement."""

    contract_version = serializers.ChoiceField(choices=["1.0"])
    client_order_id = serializers.UUIDField()
    lease_token = serializers.CharField(max_length=256)


class AgentFillSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate one immutable fill fact inside an Agent event."""

    broker_account_ref = serializers.CharField(required=False, max_length=128)
    broker_trade_id = serializers.CharField(max_length=128)
    quantity = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        min_value=Decimal("0.0001"),
    )
    price = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        min_value=Decimal("0.0001"),
    )
    occurred_at = serializers.DateTimeField()
    payload = serializers.DictField(required=False)


class AgentEventSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate one normalized broker event."""

    event_id = serializers.CharField(max_length=96)
    client_order_id = serializers.UUIDField()
    event_type = serializers.CharField(max_length=64)
    status = serializers.CharField(max_length=32, required=False, allow_blank=True)
    occurred_at = serializers.DateTimeField()
    broker_order_id = serializers.CharField(required=False, allow_blank=True, max_length=128)
    payload = serializers.DictField(required=False)
    fill = AgentFillSerializer(required=False)


class AgentEventsSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate a bounded event batch."""

    contract_version = serializers.ChoiceField(choices=["1.0"])
    events = serializers.ListField(
        child=AgentEventSerializer(),
        allow_empty=False,
        max_length=200,
    )


class AgentPositionSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate one broker position snapshot."""

    asset_code = serializers.CharField(max_length=32)
    quantity = serializers.DecimalField(max_digits=20, decimal_places=4, min_value=0)
    available_quantity = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        min_value=0,
    )
    payload = serializers.DictField(required=False)


class AgentSnapshotOrderSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate one broker order fact used only for reconciliation."""

    broker_order_id = serializers.CharField(max_length=128)
    client_order_id = serializers.CharField(required=False, allow_blank=True, max_length=128)
    asset_code = serializers.CharField(max_length=32)
    side = serializers.ChoiceField(choices=["BUY", "SELL", "UNKNOWN"])
    quantity = serializers.DecimalField(max_digits=20, decimal_places=4, min_value=0)
    traded_quantity = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        min_value=0,
        default=Decimal("0"),
    )
    limit_price = serializers.DecimalField(max_digits=20, decimal_places=4, required=False)
    status = serializers.CharField(max_length=32)


class AgentSnapshotTradeSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate one immutable broker trade fact used for reconciliation."""

    broker_trade_id = serializers.CharField(max_length=128)
    broker_order_id = serializers.CharField(max_length=128)
    client_order_id = serializers.CharField(required=False, allow_blank=True, max_length=128)
    asset_code = serializers.CharField(max_length=32)
    quantity = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        min_value=Decimal("0.0001"),
    )
    price = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        min_value=Decimal("0.0001"),
    )
    occurred_at = serializers.DateTimeField(required=False)


class AgentSnapshotSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate account and position snapshots."""

    contract_version = serializers.ChoiceField(choices=["1.0"])
    account_id = serializers.IntegerField(min_value=1)
    captured_at = serializers.DateTimeField()
    cash_available = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        min_value=0,
    )
    total_asset = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        min_value=0,
    )
    positions = serializers.ListField(
        child=AgentPositionSerializer(),
        max_length=5000,
    )
    orders = serializers.ListField(
        child=AgentSnapshotOrderSerializer(),
        required=False,
        max_length=5000,
    )
    trades = serializers.ListField(
        child=AgentSnapshotTradeSerializer(),
        required=False,
        max_length=5000,
    )
    payload = serializers.DictField(required=False)


class AgentCommandsSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate command lease request."""

    contract_version = serializers.ChoiceField(choices=["1.0"])
    limit = serializers.IntegerField(min_value=1, max_value=50, default=20)


class AgentCommandCompleteSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate one leased command result."""

    contract_version = serializers.ChoiceField(choices=["1.0"])
    command_id = serializers.UUIDField()
    success = serializers.BooleanField()
    result = serializers.DictField(required=False)
