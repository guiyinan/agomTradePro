import json

from django import forms

from ..infrastructure.models import AIProviderConfig


class AIProviderConfigForm(forms.ModelForm):
    extra_config_text = forms.CharField(
        label="额外配置(JSON)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text='可选，例如 {"timeout": 30, "max_retries": 2}',
    )
    api_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text="编辑时留空表示不修改",
    )

    class Meta:
        model = AIProviderConfig
        fields = [
            "name",
            "provider_type",
            "is_active",
            "priority",
            "base_url",
            "api_key",
            "default_model",
            "daily_budget_limit",
            "monthly_budget_limit",
            "description",
            "extra_config_text",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["extra_config_text"].initial = json.dumps(
                self.instance.extra_config or {}, ensure_ascii=False, indent=2
            )
            self.fields["api_key"].required = False
        else:
            self.fields["api_key"].required = True

    def clean_extra_config_text(self):
        raw = self.cleaned_data.get("extra_config_text", "").strip()
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"JSON 格式错误: {exc}") from exc
        if not isinstance(value, dict):
            raise forms.ValidationError("extra_config 必须是 JSON 对象")
        return value

    def clean(self):
        cleaned = super().clean()
        if self.instance and self.instance.pk and not cleaned.get("api_key"):
            cleaned["api_key"] = self.instance.api_key
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.extra_config = self.cleaned_data.get("extra_config_text", {})
        if commit:
            instance.save()
        return instance
