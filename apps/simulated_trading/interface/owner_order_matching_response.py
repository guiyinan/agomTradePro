"""Public JSON contracts for recording an existing order's daily decision."""

from __future__ import annotations

from rest_framework import serializers

from apps.simulated_trading.application.owner_order_matching import OwnerOrderMatchRecorded

from .owner_order_operation_response import JsonObject


class OwnerOrderMatchRequestSerializer(serializers.Serializer[JsonObject]):
    """Document the selected trading day and explicit confirmation."""

    session_date = serializers.DateField(input_formats=["%Y-%m-%d"])
    confirmed = serializers.BooleanField(required=True)


class OwnerOrderMatchResponseSerializer(serializers.Serializer[JsonObject]):
    """Expose a saved decision without claiming that its fill has been posted."""

    success = serializers.BooleanField()
    outcome = serializers.ChoiceField(choices=("success",))
    account_id = serializers.IntegerField(min_value=1)
    order_id = serializers.IntegerField(min_value=1)
    session_date = serializers.DateField()
    decision_recorded = serializers.BooleanField()
    decision_outcome = serializers.ChoiceField(choices=("matched", "no_match"))
    matched_quantity = serializers.CharField()
    matched_price = serializers.CharField(allow_null=True)
    reason_code = serializers.CharField()
    replayed = serializers.BooleanField()


def order_matched_payload(operation: OwnerOrderMatchRecorded) -> JsonObject:
    """Render only the exact decision; hide internal operation and source keys."""
    if type(operation) is not OwnerOrderMatchRecorded:
        raise TypeError("owner match result has an invalid type")
    operation.__post_init__()
    decision = operation.decision
    result = decision.result
    return {
        "success": True,
        "outcome": "success",
        "account_id": operation.account_id,
        "order_id": operation.order_id,
        "session_date": decision.command.session_date.isoformat(),
        "decision_recorded": True,
        "decision_outcome": result.outcome.value,
        "matched_quantity": str(result.matched_quantity),
        "matched_price": str(result.matched_price) if result.matched_price is not None else None,
        "reason_code": result.reason_code,
        "replayed": decision.replayed,
    }
