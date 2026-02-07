import json
import uuid

from django import forms
from django.db.models import Max

from ..infrastructure.models import GateConfigModel


class GateConfigForm(forms.ModelForm):
    JSON_EXAMPLES = {
        "regime_constraints_text": {
            "current_regime": "Recovery",
            "confidence": 0.72,
            "allowed_asset_classes": ["a_股票", "港股", "黄金"],
        },
        "policy_constraints_text": {
            "current_level": 2,
            "max_risk_exposure": 70,
            "hard_exclusions": ["期货", "高杠杆ETF"],
        },
        "portfolio_constraints_text": {
            "max_positions": 8,
            "max_single_position_weight": 20,
            "max_concentration_ratio": 55,
        },
    }

    regime_constraints_text = forms.CharField(
        label="Regime 约束(JSON)",
        widget=forms.Textarea(attrs={"rows": 6}),
        required=False,
        help_text="字段建议：current_regime(市场状态)、confidence(0~1)、allowed_asset_classes(允许资产类别数组)",
    )
    policy_constraints_text = forms.CharField(
        label="Policy 约束(JSON)",
        widget=forms.Textarea(attrs={"rows": 6}),
        required=False,
        help_text="字段建议：current_level(档位)、max_risk_exposure(最大风险暴露%)、hard_exclusions(硬排除列表)",
    )
    portfolio_constraints_text = forms.CharField(
        label="组合约束(JSON)",
        widget=forms.Textarea(attrs={"rows": 6}),
        required=False,
        help_text="字段建议：max_positions(最多持仓数)、max_single_position_weight(单仓上限%)、max_concentration_ratio(集中度上限%)",
    )

    class Meta:
        model = GateConfigModel
        fields = [
            "config_id",
            "risk_profile",
            "is_active",
            "effective_date",
            "expires_at",
            "regime_constraints_text",
            "policy_constraints_text",
            "portfolio_constraints_text",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in [
            "regime_constraints_text",
            "policy_constraints_text",
            "portfolio_constraints_text",
        ]:
            self.fields[field_name].widget.attrs.update(
                {
                    "class": "json-input",
                    "data-json-assistant": "1",
                    "data-json-example": json.dumps(self.JSON_EXAMPLES[field_name], ensure_ascii=False),
                }
            )
        if self.instance and self.instance.pk:
            self.fields["regime_constraints_text"].initial = json.dumps(
                self.instance.regime_constraints or {}, ensure_ascii=False, indent=2
            )
            self.fields["policy_constraints_text"].initial = json.dumps(
                self.instance.policy_constraints or {}, ensure_ascii=False, indent=2
            )
            self.fields["portfolio_constraints_text"].initial = json.dumps(
                self.instance.portfolio_constraints or {}, ensure_ascii=False, indent=2
            )
        else:
            self.fields["config_id"].initial = f"cfg-{uuid.uuid4().hex[:10]}"
            for field_name in self.JSON_EXAMPLES:
                self.fields[field_name].initial = json.dumps(
                    self.JSON_EXAMPLES[field_name],
                    ensure_ascii=False,
                    indent=2,
                )

    def _parse_json_field(self, field_name):
        raw = self.cleaned_data.get(field_name, "").strip()
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"{field_name} JSON 格式错误: {exc}") from exc
        if not isinstance(value, dict):
            raise forms.ValidationError(f"{field_name} 必须是 JSON 对象")
        return value

    def clean_regime_constraints_text(self):
        return self._parse_json_field("regime_constraints_text")

    def clean_policy_constraints_text(self):
        return self._parse_json_field("policy_constraints_text")

    def clean_portfolio_constraints_text(self):
        return self._parse_json_field("portfolio_constraints_text")

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.regime_constraints = self.cleaned_data.get("regime_constraints_text", {})
        instance.policy_constraints = self.cleaned_data.get("policy_constraints_text", {})
        instance.portfolio_constraints = self.cleaned_data.get("portfolio_constraints_text", {})

        if not self.instance or not self.instance.pk:
            max_version = GateConfigModel._default_manager.aggregate(max_v=Max("version")).get("max_v") or 0
            instance.version = max_version + 1

        if commit:
            instance.save()
        return instance

