import json

from django import forms


class _BaseProviderForm(forms.Form):
    EXTRA_CONFIG_EXAMPLE = {
        "timeout": 30,
        "max_retries": 2,
        "temperature": 0.2,
        "max_tokens": 1200,
        "response_format": "json",
    }

    name = forms.CharField(label="配置名称", max_length=50)
    provider_type = forms.ChoiceField(
        label="提供商类型",
        choices=[
            ("openai", "OpenAI"),
            ("deepseek", "DeepSeek"),
            ("qwen", "通义千问"),
            ("moonshot", "Moonshot"),
            ("custom", "自定义"),
        ],
    )
    is_active = forms.BooleanField(label="启用", required=False)
    priority = forms.IntegerField(label="优先级", min_value=1, initial=10)
    base_url = forms.URLField(label="API Base URL")
    api_key = forms.CharField(
        label="API Key",
        required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text="编辑时留空表示不修改",
    )
    default_model = forms.CharField(label="默认模型", max_length=50)
    api_mode = forms.ChoiceField(
        label="API 模式",
        choices=[
            ("dual", "Dual"),
            ("responses_only", "Responses Only"),
            ("chat_only", "Chat Only"),
        ],
        initial="dual",
    )
    fallback_enabled = forms.BooleanField(label="允许回退", required=False, initial=True)
    description = forms.CharField(label="描述", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    extra_config_text = forms.CharField(
        label="额外配置(JSON)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="可选。建议字段：timeout、max_retries、temperature、max_tokens",
    )

    def __init__(self, *args, provider=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.provider = provider
        self.fields["extra_config_text"].widget.attrs.update(
            {
                "class": "json-input",
                "data-json-assistant": "1",
                "data-json-example": json.dumps(self.EXTRA_CONFIG_EXAMPLE, ensure_ascii=False),
            }
        )

        if provider is not None:
            self.initial.setdefault("name", provider.name)
            self.initial.setdefault("provider_type", provider.provider_type)
            self.initial.setdefault("is_active", provider.is_active)
            self.initial.setdefault("priority", provider.priority)
            self.initial.setdefault("base_url", provider.base_url)
            self.initial.setdefault("default_model", provider.default_model)
            self.initial.setdefault("api_mode", provider.api_mode)
            self.initial.setdefault("fallback_enabled", provider.fallback_enabled)
            self.initial.setdefault("description", provider.description or "")
            self.initial.setdefault(
                "extra_config_text",
                json.dumps(provider.extra_config or {}, ensure_ascii=False, indent=2),
            )
            self.fields["api_key"].required = False
        else:
            self.fields["api_key"].required = True
            self.initial.setdefault(
                "extra_config_text",
                json.dumps(self.EXTRA_CONFIG_EXAMPLE, ensure_ascii=False, indent=2),
            )

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


class AIProviderConfigForm(_BaseProviderForm):
    daily_budget_limit = forms.DecimalField(label="每日预算限制", required=False, min_value=0, decimal_places=2)
    monthly_budget_limit = forms.DecimalField(label="每月预算限制", required=False, min_value=0, decimal_places=2)

    def __init__(self, *args, provider=None, **kwargs):
        super().__init__(*args, provider=provider, **kwargs)
        if provider is not None:
            self.initial.setdefault("daily_budget_limit", provider.daily_budget_limit)
            self.initial.setdefault("monthly_budget_limit", provider.monthly_budget_limit)


class PersonalAIProviderConfigForm(_BaseProviderForm):
    pass


class UserFallbackQuotaForm(forms.Form):
    daily_limit = forms.DecimalField(label="每日额度", required=False, min_value=0, decimal_places=2)
    monthly_limit = forms.DecimalField(label="每月额度", required=False, min_value=0, decimal_places=2)
    is_active = forms.BooleanField(label="启用额度", required=False, initial=True)
    admin_note = forms.CharField(label="备注", required=False, widget=forms.Textarea(attrs={"rows": 2}))
