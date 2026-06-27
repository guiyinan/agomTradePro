"""DRF serializers for risk center API."""

from __future__ import annotations

from rest_framework import serializers

from apps.risk_center.domain.entities import PARAMETER_FIELDS


class RiskParameterSerializer(serializers.Serializer):
    max_total_position_pct = serializers.FloatField(
        required=False, allow_null=True, min_value=0, max_value=1
    )
    max_single_position_pct = serializers.FloatField(
        required=False, allow_null=True, min_value=0, max_value=1
    )
    max_daily_loss_pct = serializers.FloatField(
        required=False, allow_null=True, min_value=0, max_value=1
    )
    max_drawdown_pct = serializers.FloatField(
        required=False, allow_null=True, min_value=0, max_value=1
    )
    max_stop_loss_pct = serializers.FloatField(
        required=False, allow_null=True, min_value=0, max_value=1
    )
    take_profit_pct = serializers.FloatField(
        required=False, allow_null=True, min_value=0, max_value=1
    )
    min_cash_pct = serializers.FloatField(required=False, allow_null=True, min_value=0, max_value=1)
    force_stop_loss = serializers.BooleanField(required=False, allow_null=True)
    hard_exclusions = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        allow_empty=True,
    )


class RiskFloorSerializer(RiskParameterSerializer):
    name = serializers.CharField(required=False, max_length=100)
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True)


class RiskTemplateSerializer(RiskParameterSerializer):
    id = serializers.IntegerField(read_only=True)
    key = serializers.CharField(max_length=64)
    name = serializers.CharField(max_length=120)
    risk_profile = serializers.ChoiceField(
        choices=("conservative", "moderate", "aggressive", "custom"),
        default="moderate",
    )
    description = serializers.CharField(required=False, allow_blank=True, default="")
    is_active = serializers.BooleanField(required=False, default=True)
    reason = serializers.CharField(required=False, allow_blank=True)


class RiskTemplateUpdateSerializer(RiskTemplateSerializer):
    key = serializers.CharField(required=False, max_length=64)
    name = serializers.CharField(required=False, max_length=120)
    risk_profile = serializers.ChoiceField(
        required=False,
        choices=("conservative", "moderate", "aggressive", "custom"),
    )


class AccountRiskPolicySerializer(RiskParameterSerializer):
    id = serializers.IntegerField(read_only=True)
    account_id = serializers.IntegerField(min_value=1)
    template_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    risk_profile = serializers.ChoiceField(
        required=False,
        allow_null=True,
        choices=("conservative", "moderate", "aggressive", "custom"),
    )
    is_active = serializers.BooleanField(required=False, default=True)
    reason = serializers.CharField(required=False, allow_blank=True)


class AccountRiskPolicyUpdateSerializer(AccountRiskPolicySerializer):
    account_id = serializers.IntegerField(required=False, min_value=1)


class ApplyTemplateSerializer(serializers.Serializer):
    template_id = serializers.IntegerField(min_value=1)


class RiskExceptionSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    account_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    field_name = serializers.ChoiceField(choices=PARAMETER_FIELDS)
    allowed_value = serializers.JSONField()
    reason = serializers.CharField()
    expires_at = serializers.DateTimeField()
    is_active = serializers.BooleanField(required=False, default=True)


class PreTradeRiskCheckSerializer(serializers.Serializer):
    account_id = serializers.IntegerField(min_value=1)
    symbol = serializers.CharField(max_length=64)
    side = serializers.ChoiceField(choices=("buy", "sell"))
    quantity = serializers.FloatField(min_value=0)
    price = serializers.FloatField(min_value=0)
    account_equity = serializers.FloatField(min_value=0)
    total_position_value = serializers.FloatField(min_value=0)
    cash_balance = serializers.FloatField(required=False, allow_null=True, min_value=0)
    current_symbol_position_value = serializers.FloatField(
        required=False,
        default=0.0,
        min_value=0,
    )


class PostInvestmentPositionSerializer(serializers.Serializer):
    symbol = serializers.CharField(max_length=64)
    market_value = serializers.FloatField(min_value=0)
    unrealized_pnl_pct = serializers.FloatField(required=False, allow_null=True)
    current_price = serializers.FloatField(required=False, allow_null=True, min_value=0)
    avg_cost = serializers.FloatField(required=False, allow_null=True, min_value=0)


class PostInvestmentRiskCheckSerializer(serializers.Serializer):
    account_id = serializers.IntegerField(min_value=1)
    account_equity = serializers.FloatField(min_value=0)
    cash_balance = serializers.FloatField(required=False, allow_null=True, min_value=0)
    total_position_value = serializers.FloatField(required=False, allow_null=True, min_value=0)
    daily_pnl_pct = serializers.FloatField(required=False, allow_null=True)
    drawdown_pct = serializers.FloatField(required=False, allow_null=True, min_value=0, max_value=1)
    positions = serializers.ListField(
        child=PostInvestmentPositionSerializer(),
        required=False,
        allow_empty=True,
    )
