import json
import uuid

from django import forms
from django.db.models import Max

from ..infrastructure.models import GateConfigModel


class GateConfigForm(forms.ModelForm):
    regime_constraints_text = forms.CharField(
        label="Regime 约束(JSON)",
        widget=forms.Textarea(attrs={"rows": 6}),
        required=False,
    )
    policy_constraints_text = forms.CharField(
        label="Policy 约束(JSON)",
        widget=forms.Textarea(attrs={"rows": 6}),
        required=False,
    )
    portfolio_constraints_text = forms.CharField(
        label="组合约束(JSON)",
        widget=forms.Textarea(attrs={"rows": 6}),
        required=False,
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

