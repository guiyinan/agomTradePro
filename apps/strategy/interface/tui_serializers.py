"""Flat TUI request contracts for strategy rule conditions."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.strategy.interface.serializers import StrictStrategySerializer

_COMPARISON_OPERATORS = (">", ">=", "<", "<=", "==", "!=")
_REGIMES = ("Recovery", "Overheat", "Stagflation", "Deflation")


class StrategyTuiCreateSerializer(StrictStrategySerializer):
    """Validate the scalar strategy fields supported by Classic create."""

    name = serializers.CharField(max_length=200)
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    strategy_type = serializers.ChoiceField(
        choices=["rule_based", "script_based", "hybrid", "ai_driven"]
    )
    max_position_pct = serializers.FloatField(
        required=False,
        default=20,
        min_value=0,
        max_value=100,
    )
    max_total_position_pct = serializers.FloatField(
        required=False,
        default=95,
        min_value=0,
        max_value=100,
    )
    stop_loss_pct = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=100,
    )


class StrategyTuiUpdateSerializer(StrictStrategySerializer):
    """Validate a versioned update without changing strategy type."""

    name = serializers.CharField(required=False, max_length=200)
    description = serializers.CharField(required=False, allow_blank=True)
    max_position_pct = serializers.FloatField(required=False, min_value=0, max_value=100)
    max_total_position_pct = serializers.FloatField(
        required=False,
        min_value=0,
        max_value=100,
    )
    stop_loss_pct = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=100,
    )


def _required_text(
    attrs: dict[str, Any],
    key: str,
    *,
    message: str,
) -> str:
    """Return one required non-empty text value."""

    value = str(attrs.get(key) or "").strip()
    if not value:
        raise serializers.ValidationError({key: message})
    return value


def _required_number(
    attrs: dict[str, Any],
    key: str,
    *,
    message: str,
) -> float:
    """Return one required finite number already validated by DRF."""

    value = attrs.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise serializers.ValidationError({key: message})
    return float(value)


class StrategyTuiRuleMutationSerializer(StrictStrategySerializer):
    """Accept one rule through typed fields instead of raw JSON."""

    strategy = serializers.IntegerField(min_value=1)
    rule_name = serializers.CharField(max_length=200)
    rule_type = serializers.ChoiceField(choices=["macro", "regime", "signal", "composite"])
    operator = serializers.ChoiceField(
        choices=[
            *_COMPARISON_OPERATORS,
            "between",
            "trend",
            "in",
            "transitions",
            "exists",
            "score",
        ]
    )
    indicator = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
    )
    threshold = serializers.FloatField(required=False)
    min_value = serializers.FloatField(required=False)
    max_value = serializers.FloatField(required=False)
    direction = serializers.ChoiceField(
        required=False,
        choices=["up", "down"],
    )
    periods = serializers.IntegerField(required=False, min_value=2, max_value=24)
    regime_value = serializers.ChoiceField(required=False, choices=_REGIMES)
    regime_values = serializers.ListField(
        child=serializers.ChoiceField(choices=_REGIMES),
        required=False,
        allow_empty=False,
        max_length=4,
    )
    from_regime = serializers.ChoiceField(required=False, choices=_REGIMES)
    to_regime = serializers.ChoiceField(required=False, choices=_REGIMES)
    asset_code = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
    )
    min_score = serializers.FloatField(required=False)
    composite_logic = serializers.ChoiceField(
        required=False,
        choices=["AND", "OR"],
    )
    first_type = serializers.ChoiceField(
        required=False,
        choices=["macro", "regime", "signal"],
    )
    first_operator = serializers.ChoiceField(
        required=False,
        choices=[*_COMPARISON_OPERATORS, "exists", "score"],
    )
    first_key = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
    )
    first_value = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
    )
    second_type = serializers.ChoiceField(
        required=False,
        choices=["macro", "regime", "signal"],
    )
    second_operator = serializers.ChoiceField(
        required=False,
        choices=[*_COMPARISON_OPERATORS, "exists", "score"],
    )
    second_key = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
    )
    second_value = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
    )
    action = serializers.ChoiceField(choices=["buy", "sell", "hold", "weight"])
    weight = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=1,
    )
    target_assets = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        allow_empty=True,
        max_length=100,
    )
    priority = serializers.IntegerField(required=False, default=10, min_value=0, max_value=100)
    is_enabled = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validate only fields that apply to the selected rule type."""

        rule_type = attrs["rule_type"]
        operator = attrs["operator"]
        if rule_type == "macro":
            _required_text(attrs, "indicator", message="宏观规则必须选择指标")
            if operator in _COMPARISON_OPERATORS:
                _required_number(attrs, "threshold", message="比较规则必须填写阈值")
            elif operator == "between":
                minimum = _required_number(attrs, "min_value", message="区间规则必须填写最小值")
                maximum = _required_number(attrs, "max_value", message="区间规则必须填写最大值")
                if minimum > maximum:
                    raise serializers.ValidationError({"max_value": "最大值不得小于最小值"})
            elif operator == "trend":
                if "direction" not in attrs or "periods" not in attrs:
                    raise serializers.ValidationError({"operator": "趋势规则必须填写方向和周期数"})
            else:
                raise serializers.ValidationError({"operator": "宏观规则不支持该运算符"})
        elif rule_type == "regime":
            if operator == "==" and "regime_value" not in attrs:
                raise serializers.ValidationError(
                    {"regime_value": "Regime 精确匹配必须选择目标状态"}
                )
            if operator == "in" and not attrs.get("regime_values"):
                raise serializers.ValidationError(
                    {"regime_values": "Regime 集合匹配必须选择至少一个状态"}
                )
            if operator == "transitions" and (
                "from_regime" not in attrs or "to_regime" not in attrs
            ):
                raise serializers.ValidationError({"operator": "Regime 转换必须选择起始和目标状态"})
            if operator not in {"==", "in", "transitions"}:
                raise serializers.ValidationError({"operator": "Regime 规则不支持该运算符"})
        elif rule_type == "signal":
            _required_text(attrs, "asset_code", message="信号规则必须填写资产代码")
            if operator == "score":
                _required_number(attrs, "min_score", message="评分规则必须填写最低分")
            elif operator != "exists":
                raise serializers.ValidationError({"operator": "信号规则仅支持存在或评分判断"})
        else:
            if "composite_logic" not in attrs:
                raise serializers.ValidationError({"composite_logic": "组合规则必须选择 AND 或 OR"})
            self._build_composite_condition(attrs, prefix="first")
            self._build_composite_condition(attrs, prefix="second")
        return attrs

    @staticmethod
    def _numeric_text(value: str, *, key: str) -> float:
        """Parse a bounded TUI text value as a number."""

        try:
            return float(value)
        except ValueError as exc:
            raise serializers.ValidationError({key: "该条件值必须是数字"}) from exc

    @classmethod
    def _build_composite_condition(
        cls,
        attrs: dict[str, Any],
        *,
        prefix: str,
    ) -> dict[str, Any]:
        """Build one of two flat composite subconditions."""

        condition_type = attrs.get(f"{prefix}_type")
        operator = attrs.get(f"{prefix}_operator")
        key = str(attrs.get(f"{prefix}_key") or "").strip()
        value = str(attrs.get(f"{prefix}_value") or "").strip()
        if condition_type is None or operator is None:
            raise serializers.ValidationError(
                {f"{prefix}_type": "组合规则的两个子条件都必须完整填写"}
            )

        if condition_type == "macro":
            if not key or operator not in _COMPARISON_OPERATORS:
                raise serializers.ValidationError(
                    {f"{prefix}_key": "宏观子条件需要指标和比较运算符"}
                )
            return {
                "type": "macro",
                "operator": operator,
                "indicator": key,
                "threshold": cls._numeric_text(value, key=f"{prefix}_value"),
            }
        if condition_type == "regime":
            if operator != "==" or value not in _REGIMES:
                raise serializers.ValidationError(
                    {f"{prefix}_value": "Regime 子条件必须使用等于并选择有效状态"}
                )
            return {"type": "regime", "operator": "==", "value": value}

        if not key or operator not in {"exists", "score"}:
            raise serializers.ValidationError(
                {f"{prefix}_key": "信号子条件需要资产代码和存在/评分运算符"}
            )
        condition: dict[str, Any] = {
            "type": "signal",
            "operator": operator,
            "asset_code": key,
        }
        if operator == "score":
            condition["min_score"] = cls._numeric_text(
                value,
                key=f"{prefix}_value",
            )
        return condition

    def to_rule_payload(self) -> dict[str, Any]:
        """Translate validated flat fields into the owner serializer contract."""

        attrs = self.validated_data
        rule_type = attrs["rule_type"]
        operator = attrs["operator"]
        condition: dict[str, Any]
        if rule_type == "macro":
            condition = {
                "operator": operator,
                "indicator": attrs["indicator"],
            }
            if operator in _COMPARISON_OPERATORS:
                condition["threshold"] = attrs["threshold"]
            elif operator == "between":
                condition["min"] = attrs["min_value"]
                condition["max"] = attrs["max_value"]
            else:
                condition["direction"] = attrs["direction"]
                condition["periods"] = attrs["periods"]
        elif rule_type == "regime":
            condition = {"operator": operator}
            if operator == "==":
                condition["value"] = attrs["regime_value"]
            elif operator == "in":
                condition["values"] = attrs["regime_values"]
            else:
                condition["from"] = attrs["from_regime"]
                condition["to"] = attrs["to_regime"]
        elif rule_type == "signal":
            condition = {
                "operator": operator,
                "asset_code": attrs["asset_code"],
            }
            if operator == "score":
                condition["min_score"] = attrs["min_score"]
        else:
            condition = {
                "operator": attrs["composite_logic"],
                "conditions": [
                    self._build_composite_condition(attrs, prefix="first"),
                    self._build_composite_condition(attrs, prefix="second"),
                ],
            }

        return {
            "strategy": attrs["strategy"],
            "rule_name": attrs["rule_name"],
            "rule_type": rule_type,
            "condition_json": condition,
            "action": attrs["action"],
            "weight": attrs.get("weight"),
            "target_assets": attrs.get("target_assets", []),
            "priority": attrs["priority"],
            "is_enabled": attrs["is_enabled"],
        }


__all__ = [
    "StrategyTuiCreateSerializer",
    "StrategyTuiRuleMutationSerializer",
    "StrategyTuiUpdateSerializer",
]
