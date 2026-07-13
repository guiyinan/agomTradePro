"""
Beta Gate DRF Serializers

硬闸门过滤的 API 序列化器。

简化版本，与现有 domain entities 兼容。
"""

import math

from rest_framework import serializers

from ..domain.entities import GateStatus, RiskProfile

REGIME_CHOICES = ("Recovery", "Overheat", "Deflation", "Stagflation")


class RiskProfileSerializer(serializers.Field):
    """风险画像序列化器"""

    def to_representation(self, obj):
        return obj.value

    def to_internal_value(self, data):
        try:
            return RiskProfile(data)
        except ValueError:
            raise serializers.ValidationError(f"Invalid risk profile: {data}") from None


class GateConfigSerializer(serializers.Serializer):
    """闸门配置序列化器（简化版）"""

    config_id = serializers.CharField(read_only=True)
    risk_profile = RiskProfileSerializer()
    version = serializers.IntegerField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    regime_constraints = serializers.DictField(read_only=True)
    policy_constraints = serializers.DictField(read_only=True)
    portfolio_constraints = serializers.DictField(read_only=True)
    effective_date = serializers.DateField(read_only=True)
    expires_at = serializers.DateField(allow_null=True, read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance):
        """转换为表示"""
        return {
            "config_id": instance.config_id,
            "risk_profile": instance.risk_profile.value,
            "version": instance.version,
            "is_active": instance.is_active,
            "regime_constraints": instance.regime_constraints,
            "policy_constraints": instance.policy_constraints,
            "portfolio_constraints": instance.portfolio_constraints,
            "effective_date": instance.effective_date.isoformat() if instance.effective_date else None,
            "expires_at": instance.expires_at.isoformat() if instance.expires_at else None,
            "created_at": instance.created_at.isoformat() if hasattr(instance, "created_at") else None,
        }


class GateConfigCreateSerializer(serializers.Serializer):
    """Validate the canonical Beta Gate config creation contract."""

    config_id = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=64,
    )
    risk_profile = serializers.ChoiceField(
        choices=[profile.value for profile in RiskProfile],
        default=RiskProfile.BALANCED.value,
    )
    allowed_regimes = serializers.ListField(
        child=serializers.ChoiceField(
            choices=("Recovery", "Overheat", "Deflation", "Stagflation")
        ),
        required=False,
        allow_empty=False,
    )
    min_confidence = serializers.FloatField(
        min_value=0.0,
        max_value=1.0,
        default=0.3,
    )
    max_policy_level = serializers.IntegerField(
        min_value=0,
        max_value=3,
        default=2,
    )
    veto_on_p3 = serializers.BooleanField(default=True)
    max_total_position = serializers.FloatField(
        min_value=0.0,
        max_value=100.0,
        default=95.0,
    )
    max_single_position = serializers.FloatField(
        min_value=0.0,
        max_value=100.0,
        default=20.0,
    )

    def validate(self, attrs):
        """Reject a single-position cap above the total-position cap."""

        if attrs["max_single_position"] > attrs["max_total_position"]:
            raise serializers.ValidationError(
                {
                    "max_single_position": (
                        "max_single_position must not exceed max_total_position"
                    )
                }
            )
        return attrs


class BetaGateTestSerializer(serializers.Serializer):
    """Validate the canonical side-effect-free Beta Gate batch evaluation input."""

    asset_codes = serializers.ListField(
        child=serializers.CharField(
            allow_blank=False,
            trim_whitespace=True,
            max_length=32,
        ),
        allow_empty=False,
        max_length=100,
    )
    asset_class = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
        max_length=64,
    )
    current_regime = serializers.ChoiceField(choices=REGIME_CHOICES)
    regime_confidence = serializers.FloatField(min_value=0.0, max_value=1.0)
    policy_level = serializers.IntegerField(min_value=0, max_value=3)
    risk_profile = serializers.ChoiceField(
        choices=[profile.value for profile in RiskProfile],
        default=RiskProfile.BALANCED.value,
    )

    def to_internal_value(self, data):
        """Reject unknown fields instead of silently accepting contract drift."""

        if not isinstance(data, dict):
            raise serializers.ValidationError("Expected an object payload.")
        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        f"Unknown fields: {', '.join(unknown_fields)}"
                    ]
                }
            )
        return super().to_internal_value(data)

    def validate_asset_codes(self, value):
        """Require unique normalized asset codes."""

        normalized = [code.strip() for code in value]
        if len(normalized) != len(set(normalized)):
            raise serializers.ValidationError("asset_codes must not contain duplicates")
        return normalized

    def validate_regime_confidence(self, value):
        """Reject non-finite values that bypass ordinary numeric range comparisons."""

        if not math.isfinite(value):
            raise serializers.ValidationError("regime_confidence must be finite")
        return value


class GateDecisionSerializer(serializers.Serializer):
    """闸门决策序列化器（简化版）"""

    decision_id = serializers.CharField(read_only=True)
    asset_code = serializers.CharField()
    asset_class = serializers.CharField()
    status = serializers.CharField(read_only=True)
    current_regime = serializers.CharField()
    policy_level = serializers.IntegerField()
    regime_confidence = serializers.FloatField()
    evaluated_at = serializers.DateTimeField(read_only=True)
    evaluation_details = serializers.DictField(read_only=True)

    def to_representation(self, instance):
        """转换为表示"""
        return {
            "decision_id": getattr(instance, "decision_id", ""),
            "asset_code": instance.asset_code,
            "asset_class": instance.asset_class,
            "status": instance.status.value,
            "current_regime": instance.current_regime,
            "policy_level": instance.policy_level,
            "regime_confidence": instance.regime_confidence,
            "evaluated_at": instance.evaluated_at.isoformat(),
            "evaluation_details": instance.evaluation_details or {},
        }

    @property
    def is_passed(self):
        """是否通过"""
        return self.status == GateStatus.PASSED

    @property
    def is_blocked(self):
        """是否被拦截"""
        return self.status.value.startswith("blocked_")


class VisibilityUniverseSerializer(serializers.Serializer):
    """可见性宇宙序列化器（简化版）"""

    snapshot_id = serializers.CharField(read_only=True)
    current_regime = serializers.CharField(read_only=True)
    policy_level = serializers.IntegerField(read_only=True)
    regime_confidence = serializers.FloatField(read_only=True)
    risk_profile = serializers.CharField(read_only=True)
    visible_asset_categories = serializers.ListField(read_only=True, child=serializers.CharField())
    visible_strategies = serializers.ListField(read_only=True, child=serializers.CharField())
    hard_exclusions = serializers.ListField(read_only=True, child=serializers.CharField())
    watch_list = serializers.ListField(read_only=True, child=serializers.CharField())
    created_at = serializers.DateTimeField(read_only=True)


class EvaluateGateRequestSerializer(serializers.Serializer):
    """评估闸门请求序列化器"""

    asset_code = serializers.CharField(help_text="资产代码")
    asset_class = serializers.CharField(help_text="资产类别")
    current_regime = serializers.CharField(help_text="当前 Regime")
    regime_confidence = serializers.FloatField(min_value=0.0, max_value=1.0)
    policy_level = serializers.IntegerField(min_value=0, max_value=4)
    current_portfolio_value = serializers.FloatField(default=0.0, min_value=0.0, required=False)
    new_position_value = serializers.FloatField(default=0.0, min_value=0.0, required=False)
    risk_profile = serializers.ChoiceField(
        choices=[rp.value for rp in RiskProfile],
        default=RiskProfile.BALANCED.value,
        required=False,
    )
