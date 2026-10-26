"""Flat owner input for the existing typed M1 publication use case."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from rest_framework import serializers

from apps.risk_center.domain.m1_rebalance_risk_policy import (
    M1RiskCondition,
    RiskApplicability,
)
from apps.simulated_trading.application.m1_rebalance_risk_policy import (
    OwnerM1RiskPolicyPublishRequest,
)
from apps.simulated_trading.interface.m1_risk_policy_serializers import (
    ExplicitAwareDateTimeField,
)


class _M1PercentageInputField(serializers.DecimalField):
    """Treat an intentionally blank visible percentage box as an absent value."""

    def run_validation(self, data: object = serializers.empty) -> Decimal | None:
        """Accept a blank form control while retaining DRF decimal bounds."""

        normalized = None if type(data) is str and not data.strip() else data
        result = super().run_validation(normalized)
        if result is None or type(result) is Decimal:
            return result
        raise serializers.ValidationError("percentage must be a decimal or blank")


class OwnerM1RiskPolicyFlatPublishSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate flat TUI controls, then reuse the nested API-to-Application mapper."""

    strategy_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    effective_from = ExplicitAwareDateTimeField()
    effective_until = ExplicitAwareDateTimeField()
    reason = serializers.CharField(allow_blank=False, max_length=2000)

    max_single_position_applicability = serializers.ChoiceField(
        choices=tuple(item.value for item in RiskApplicability)
    )
    max_single_position_limit_pct = _M1PercentageInputField(
        max_digits=6,
        decimal_places=3,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        required=False,
        allow_null=True,
    )
    max_single_position_not_applicable_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
    )

    max_total_position_applicability = serializers.ChoiceField(
        choices=tuple(item.value for item in RiskApplicability)
    )
    max_total_position_limit_pct = _M1PercentageInputField(
        max_digits=6,
        decimal_places=3,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        required=False,
        allow_null=True,
    )
    max_total_position_not_applicable_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
    )

    max_stop_loss_applicability = serializers.ChoiceField(
        choices=tuple(item.value for item in RiskApplicability)
    )
    max_stop_loss_limit_pct = _M1PercentageInputField(
        max_digits=6,
        decimal_places=3,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        required=False,
        allow_null=True,
    )
    max_stop_loss_not_applicable_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
    )

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Check each flat condition and require a positive aware interval."""

        effective_from = attrs.get("effective_from")
        effective_until = attrs.get("effective_until")
        if (
            type(effective_from) is not datetime
            or type(effective_until) is not datetime
            or effective_from.tzinfo is None
            or effective_until.tzinfo is None
            or effective_from.utcoffset() is None
            or effective_until.utcoffset() is None
            or effective_from >= effective_until
        ):
            raise serializers.ValidationError("effective window must be aware and increasing")
        reason = attrs.get("reason")
        if type(reason) is not str or not reason.strip():
            raise serializers.ValidationError("owner reason is required")
        for dimension in ("max_single_position", "max_total_position", "max_stop_loss"):
            _flat_condition(attrs, dimension)
        return attrs

    def to_application_request(self) -> OwnerM1RiskPolicyPublishRequest:
        """Map visible controls to the exact existing typed publication request."""

        if not self.is_valid():
            raise AssertionError("flat serializer must be valid before conversion")
        attrs = cast(dict[str, object], self.validated_data)
        return OwnerM1RiskPolicyPublishRequest(
            strategy_id=cast(int | None, attrs.get("strategy_id")),
            effective_from=cast(datetime, attrs["effective_from"]),
            effective_until=cast(datetime, attrs["effective_until"]),
            reason=cast(str, attrs["reason"]).strip(),
            max_single_position=_typed_condition(attrs, "max_single_position"),
            max_total_position=_typed_condition(attrs, "max_total_position"),
            max_stop_loss=_typed_condition(attrs, "max_stop_loss"),
        )


def _flat_condition(attrs: dict[str, object], dimension: str) -> dict[str, object]:
    """Build one validated nested condition without inventing any risk value."""

    state = attrs.get(f"{dimension}_applicability")
    limit = attrs.get(f"{dimension}_limit_pct")
    raw_reason = attrs.get(f"{dimension}_not_applicable_reason")
    reason = raw_reason.strip() if isinstance(raw_reason, str) else ""

    if state == RiskApplicability.APPLICABLE.value:
        if type(limit) is not Decimal or reason:
            raise serializers.ValidationError(
                {dimension: "适用时须填写百分数，且不能填写不适用原因。"}
            )
        return {"applicability": state, "limit_pct": limit}
    if state == RiskApplicability.NOT_APPLICABLE.value:
        if limit is not None or not reason:
            raise serializers.ValidationError({dimension: "选择不适用时须填写原因，且百分数留空。"})
        return {"applicability": state, "not_applicable_reason": reason}
    if state == RiskApplicability.UNKNOWN.value:
        if limit is not None or reason:
            raise serializers.ValidationError(
                {dimension: "选择未知时，百分数和不适用原因都须留空。"}
            )
        return {"applicability": state}
    raise serializers.ValidationError({dimension: "请选择适用状态。"})


def _typed_condition(attrs: dict[str, object], dimension: str) -> M1RiskCondition:
    """Build the existing Domain value object from validated visible controls."""

    value = _flat_condition(attrs, dimension)
    state = RiskApplicability(cast(str, value["applicability"]))
    limit = value.get("limit_pct")
    reason = value.get("not_applicable_reason")
    return M1RiskCondition(
        applicability=state,
        limit_pct=cast(Decimal | None, limit),
        not_applicable_reason=cast(str | None, reason),
    )


__all__: tuple[str, ...] = ("OwnerM1RiskPolicyFlatPublishSerializer",)
