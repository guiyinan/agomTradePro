"""Forms for policy management pages."""

from __future__ import annotations

from types import SimpleNamespace

from django import forms

from .serializers import (
    POLICY_LEVEL_CHOICES,
    RSS_PARSER_TYPE_CHOICES,
    RSS_PROXY_TYPE_CHOICES,
    RSS_SOURCE_CATEGORY_CHOICES,
    RSSHUB_FORMAT_CHOICES,
)


class PolicyEventForm(forms.Form):
    event_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    level = forms.ChoiceField(choices=POLICY_LEVEL_CHOICES)
    title = forms.CharField(max_length=200)
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}))
    evidence_url = forms.URLField(max_length=500)

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance or SimpleNamespace(pk=None)

    def to_payload(self) -> dict:
        return dict(self.cleaned_data)


class RSSSourceForm(forms.Form):
    name = forms.CharField(max_length=100)
    category = forms.ChoiceField(choices=RSS_SOURCE_CATEGORY_CHOICES)
    is_active = forms.BooleanField(required=False, initial=True)
    fetch_interval_hours = forms.IntegerField(
        min_value=1,
        max_value=168,
        initial=6,
        widget=forms.NumberInput(attrs={"min": 1, "max": 168}),
    )
    extract_content = forms.BooleanField(required=False)
    timeout_seconds = forms.IntegerField(
        min_value=5,
        max_value=120,
        initial=30,
        widget=forms.NumberInput(attrs={"min": 5, "max": 120}),
    )
    retry_times = forms.IntegerField(
        min_value=0,
        max_value=10,
        initial=3,
        widget=forms.NumberInput(attrs={"min": 0, "max": 10}),
    )
    url = forms.URLField(max_length=500, required=False)
    parser_type = forms.ChoiceField(choices=RSS_PARSER_TYPE_CHOICES, initial="feedparser")
    rsshub_enabled = forms.BooleanField(required=False)
    rsshub_route_path = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "/csrc/news/bwj"}),
    )
    rsshub_use_global_config = forms.BooleanField(required=False, initial=True)
    rsshub_custom_base_url = forms.URLField(
        max_length=500,
        required=False,
        widget=forms.URLInput(attrs={"placeholder": "http://127.0.0.1:1200"}),
    )
    rsshub_custom_access_key = forms.CharField(max_length=200, required=False)
    rsshub_format = forms.ChoiceField(choices=RSSHUB_FORMAT_CHOICES, required=False)
    proxy_enabled = forms.BooleanField(required=False)
    proxy_host = forms.CharField(max_length=200, required=False)
    proxy_port = forms.IntegerField(
        min_value=1,
        max_value=65535,
        required=False,
        widget=forms.NumberInput(attrs={"min": 1, "max": 65535}),
    )
    proxy_type = forms.ChoiceField(choices=RSS_PROXY_TYPE_CHOICES, initial="http")
    proxy_username = forms.CharField(max_length=100, required=False)
    proxy_password = forms.CharField(max_length=200, required=False)

    def __init__(self, *args, instance=None, **kwargs):
        initial = kwargs.pop("initial", {})
        self.instance = instance or SimpleNamespace(pk=None)
        if instance is not None:
            initial = {
                "name": instance.name,
                "category": instance.category,
                "is_active": instance.is_active,
                "fetch_interval_hours": instance.fetch_interval_hours,
                "extract_content": instance.extract_content,
                "timeout_seconds": instance.timeout_seconds,
                "retry_times": instance.retry_times,
                "url": instance.url,
                "parser_type": instance.parser_type,
                "rsshub_enabled": instance.rsshub_enabled,
                "rsshub_route_path": instance.rsshub_route_path,
                "rsshub_use_global_config": instance.rsshub_use_global_config,
                "rsshub_custom_base_url": instance.rsshub_custom_base_url,
                "rsshub_custom_access_key": instance.rsshub_custom_access_key,
                "rsshub_format": instance.rsshub_format,
                "proxy_enabled": instance.proxy_enabled,
                "proxy_host": instance.proxy_host,
                "proxy_port": instance.proxy_port,
                "proxy_type": instance.proxy_type,
                "proxy_username": instance.proxy_username,
                "proxy_password": instance.proxy_password,
                **initial,
            }
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        rsshub_enabled = cleaned_data.get("rsshub_enabled")
        url = cleaned_data.get("url")
        rsshub_route_path = cleaned_data.get("rsshub_route_path")

        if rsshub_enabled and not rsshub_route_path:
            self.add_error("rsshub_route_path", "启用 RSSHub 模式时必须填写路由路径")
        if not rsshub_enabled and not url:
            self.add_error("url", "非 RSSHub 模式下必须填写 RSS URL")

        return cleaned_data

    def to_payload(self) -> dict:
        return dict(self.cleaned_data)


class PolicyKeywordForm(forms.Form):
    level = forms.ChoiceField(choices=POLICY_LEVEL_CHOICES)
    keywords_text = forms.CharField(
        label="关键词（逗号分隔）",
        required=True,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="例如：降准, 降息, 宽松",
    )
    weight = forms.IntegerField(
        min_value=0,
        initial=1,
        widget=forms.NumberInput(attrs={"min": 0, "step": "0.1"}),
    )
    category = forms.CharField(max_length=50, required=False)
    is_active = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, instance=None, **kwargs):
        initial = kwargs.pop("initial", {})
        self.instance = instance or SimpleNamespace(pk=None, keywords=[])
        if instance is not None:
            initial = {
                "level": instance.level,
                "keywords_text": ", ".join(instance.keywords or []),
                "weight": instance.weight,
                "category": instance.category or "",
                "is_active": instance.is_active,
                **initial,
            }
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

    def clean_keywords_text(self):
        raw = self.cleaned_data["keywords_text"]
        keywords = [item.strip() for item in raw.split(",") if item.strip()]
        if not keywords:
            raise forms.ValidationError("至少填写一个关键词")
        return keywords

    def to_payload(self) -> dict:
        return {
            "level": self.cleaned_data["level"],
            "keywords": self.cleaned_data["keywords_text"],
            "weight": self.cleaned_data["weight"],
            "category": self.cleaned_data["category"] or None,
            "is_active": self.cleaned_data["is_active"],
        }
