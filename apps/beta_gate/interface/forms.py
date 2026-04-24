"""Interface-layer forms for Beta Gate configuration."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from django import forms
from django.utils import timezone


@dataclass(frozen=True)
class GateConfigFormData:
    """Validated Beta Gate config data for application persistence."""

    pk: Any | None
    config_id: str
    risk_profile: str
    is_active: bool
    effective_date: date
    expires_at: date | None
    regime_constraints: dict[str, Any]
    policy_constraints: dict[str, Any]
    portfolio_constraints: dict[str, Any]


class GateConfigForm(forms.Form):
    """Validate Beta Gate config input without importing ORM models."""

    RISK_PROFILE_CHOICES = [
        ("CONSERVATIVE", "保守型"),
        ("BALANCED", "平衡型"),
        ("AGGRESSIVE", "激进型"),
    ]
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

    config_id = forms.CharField(label="配置 ID", max_length=64)
    risk_profile = forms.ChoiceField(label="风险画像", choices=RISK_PROFILE_CHOICES)
    is_active = forms.BooleanField(label="是否激活", required=False)
    effective_date = forms.DateField(label="生效日期")
    expires_at = forms.DateField(label="过期日期", required=False)
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

    def __init__(self, *args, **kwargs):
        self.instance = kwargs.pop("instance", None)
        super().__init__(*args, **kwargs)
        self._configure_widgets()
        if self.instance and getattr(self.instance, "pk", None):
            self._apply_instance_initial()
        else:
            self._apply_create_initial()

    def save(self, commit=True) -> GateConfigFormData:
        """Return validated data for the application service."""

        if not self.is_valid():
            raise ValueError("Cannot save invalid GateConfigForm")

        return GateConfigFormData(
            pk=getattr(self.instance, "pk", None),
            config_id=self.cleaned_data["config_id"],
            risk_profile=self.cleaned_data["risk_profile"],
            is_active=bool(self.cleaned_data.get("is_active")),
            effective_date=self.cleaned_data["effective_date"],
            expires_at=self.cleaned_data.get("expires_at"),
            regime_constraints=self.cleaned_data.get("regime_constraints_text", {}),
            policy_constraints=self.cleaned_data.get("policy_constraints_text", {}),
            portfolio_constraints=self.cleaned_data.get("portfolio_constraints_text", {}),
        )

    def _configure_widgets(self) -> None:
        for field_name in [
            "regime_constraints_text",
            "policy_constraints_text",
            "portfolio_constraints_text",
        ]:
            self.fields[field_name].widget.attrs.update(
                {
                    "class": "json-input",
                    "data-json-assistant": "1",
                    "data-json-example": json.dumps(
                        self.JSON_EXAMPLES[field_name],
                        ensure_ascii=False,
                    ),
                }
            )

    def _apply_instance_initial(self) -> None:
        self.initial.update(
            {
                "config_id": self.instance.config_id,
                "risk_profile": self.instance.risk_profile,
                "is_active": self.instance.is_active,
                "effective_date": self.instance.effective_date,
                "expires_at": self.instance.expires_at,
                "regime_constraints_text": json.dumps(
                    self.instance.regime_constraints or {},
                    ensure_ascii=False,
                    indent=2,
                ),
                "policy_constraints_text": json.dumps(
                    self.instance.policy_constraints or {},
                    ensure_ascii=False,
                    indent=2,
                ),
                "portfolio_constraints_text": json.dumps(
                    self.instance.portfolio_constraints or {},
                    ensure_ascii=False,
                    indent=2,
                ),
            }
        )

    def _apply_create_initial(self) -> None:
        self.initial["config_id"] = f"cfg-{uuid.uuid4().hex[:10]}"
        self.initial["effective_date"] = timezone.now().date()
        for field_name, example in self.JSON_EXAMPLES.items():
            self.initial[field_name] = json.dumps(
                example,
                ensure_ascii=False,
                indent=2,
            )

    def _parse_json_field(self, field_name: str) -> dict[str, Any]:
        raw = self.cleaned_data.get(field_name, "")
        raw = raw.strip() if isinstance(raw, str) else raw
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"{field_name} JSON 格式错误: {exc}") from exc
        if not isinstance(value, dict):
            raise forms.ValidationError(f"{field_name} 必须是 JSON 对象")
        return value

    def clean_regime_constraints_text(self) -> dict[str, Any]:
        return self._parse_json_field("regime_constraints_text")

    def clean_policy_constraints_text(self) -> dict[str, Any]:
        return self._parse_json_field("policy_constraints_text")

    def clean_portfolio_constraints_text(self) -> dict[str, Any]:
        return self._parse_json_field("portfolio_constraints_text")
