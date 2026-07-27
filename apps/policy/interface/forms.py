"""Forms for policy management pages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from django import forms

from .serializers import (
    POLICY_LEVEL_CHOICES,
    RSS_PARSER_TYPE_CHOICES,
    RSS_PROXY_TYPE_CHOICES,
    RSS_SOURCE_CATEGORY_CHOICES,
    RSSHUB_FORMAT_CHOICES,
)


class _FormInstance(Protocol):
    """Minimum instance identity exposed to shared form templates."""

    pk: int | None


class _RSSSourceInstance(_FormInstance, Protocol):
    name: str
    category: str
    is_active: bool
    fetch_interval_hours: int
    extract_content: bool
    timeout_seconds: int
    retry_times: int
    url: str
    parser_type: str
    rsshub_enabled: bool
    rsshub_route_path: str
    rsshub_use_global_config: bool
    rsshub_custom_base_url: str
    rsshub_custom_access_key: str
    rsshub_format: str
    proxy_enabled: bool
    proxy_host: str
    proxy_port: int | None
    proxy_type: str
    proxy_username: str
    proxy_password: str


class _PolicyKeywordInstance(_FormInstance, Protocol):
    level: str
    keywords: Sequence[str]
    weight: int
    category: str | None
    is_active: bool


@dataclass
class _NewFormInstance:
    """Unsaved instance marker used by templates on create forms."""

    pk: int | None = None


class PolicyEventForm(forms.Form):
    event_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    level = forms.ChoiceField(choices=POLICY_LEVEL_CHOICES)
    title = forms.CharField(max_length=200)
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}))
    evidence_url = forms.URLField(max_length=500)

    def __init__(
        self,
        *args: Any,
        instance: _FormInstance | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.instance: _FormInstance = instance if instance is not None else _NewFormInstance()

    def to_payload(self) -> dict[str, Any]:
        """Return the validated policy-event write whitelist."""

        return {
            "event_date": self.cleaned_data["event_date"],
            "level": self.cleaned_data["level"],
            "title": self.cleaned_data["title"],
            "description": self.cleaned_data["description"],
            "evidence_url": self.cleaned_data["evidence_url"],
        }


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
        widget=forms.TextInput(
            attrs={"placeholder": "/gov/csrc/news/c100028/common_xq_list.shtml"}
        ),
    )
    rsshub_use_global_config = forms.BooleanField(required=False, initial=True)
    rsshub_custom_base_url = forms.URLField(
        max_length=500,
        required=False,
        widget=forms.URLInput(attrs={"placeholder": "http://127.0.0.1:1200"}),
    )
    rsshub_custom_access_key = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.PasswordInput(render_value=False),
    )
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
    proxy_password = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.PasswordInput(render_value=False),
    )

    def __init__(
        self,
        *args: Any,
        instance: _RSSSourceInstance | None = None,
        **kwargs: Any,
    ) -> None:
        provided_initial = kwargs.pop("initial", None)
        if provided_initial is None:
            initial: dict[str, Any] = {}
        elif isinstance(provided_initial, Mapping):
            initial = {str(key): value for key, value in provided_initial.items()}
        else:
            raise TypeError("initial must be a mapping")
        self._bound_instance = instance
        self.instance: _FormInstance = instance if instance is not None else _NewFormInstance()
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
                "rsshub_format": instance.rsshub_format,
                "proxy_enabled": instance.proxy_enabled,
                "proxy_host": instance.proxy_host,
                "proxy_port": instance.proxy_port,
                "proxy_type": instance.proxy_type,
                "proxy_username": instance.proxy_username,
                **initial,
            }
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

    def clean_rsshub_custom_access_key(self) -> str:
        """Preserve the stored RSSHub key when the masked input remains blank."""

        value = self.cleaned_data.get("rsshub_custom_access_key")
        if isinstance(value, str) and value:
            return value
        return self._bound_instance.rsshub_custom_access_key if self._bound_instance else ""

    def clean_proxy_password(self) -> str:
        """Preserve the stored proxy password when the masked input remains blank."""

        value = self.cleaned_data.get("proxy_password")
        if isinstance(value, str) and value:
            return value
        return self._bound_instance.proxy_password if self._bound_instance else ""

    def clean(self) -> dict[str, Any]:
        """Validate the selected RSS transport mode as one coherent configuration."""

        cleaned_data = super().clean() or {}
        rsshub_enabled = bool(cleaned_data.get("rsshub_enabled"))
        url = cleaned_data.get("url")
        rsshub_route_path = cleaned_data.get("rsshub_route_path")
        use_global_config = bool(cleaned_data.get("rsshub_use_global_config"))
        custom_base_url = cleaned_data.get("rsshub_custom_base_url")
        proxy_enabled = bool(cleaned_data.get("proxy_enabled"))

        if rsshub_enabled and not rsshub_route_path:
            self.add_error("rsshub_route_path", "启用 RSSHub 模式时必须填写路由路径")
        elif rsshub_enabled and (
            not isinstance(rsshub_route_path, str)
            or not rsshub_route_path.startswith("/")
            or rsshub_route_path.startswith("//")
        ):
            self.add_error("rsshub_route_path", "RSSHub 路由必须以单个 / 开头")
        if rsshub_enabled and not use_global_config and not custom_base_url:
            self.add_error("rsshub_custom_base_url", "不使用全局配置时必须填写 RSSHub 基址")
        if not rsshub_enabled and not url:
            self.add_error("url", "非 RSSHub 模式下必须填写 RSS URL")
        if proxy_enabled and not cleaned_data.get("proxy_host"):
            self.add_error("proxy_host", "启用代理时必须填写代理主机")
        if proxy_enabled and cleaned_data.get("proxy_port") is None:
            self.add_error("proxy_port", "启用代理时必须填写代理端口")

        return cleaned_data

    def to_payload(self) -> dict[str, Any]:
        """Return the validated RSS-source write whitelist."""

        return {
            "name": self.cleaned_data["name"],
            "category": self.cleaned_data["category"],
            "is_active": self.cleaned_data["is_active"],
            "fetch_interval_hours": self.cleaned_data["fetch_interval_hours"],
            "extract_content": self.cleaned_data["extract_content"],
            "timeout_seconds": self.cleaned_data["timeout_seconds"],
            "retry_times": self.cleaned_data["retry_times"],
            "url": self.cleaned_data["url"],
            "parser_type": self.cleaned_data["parser_type"],
            "rsshub_enabled": self.cleaned_data["rsshub_enabled"],
            "rsshub_route_path": self.cleaned_data["rsshub_route_path"],
            "rsshub_use_global_config": self.cleaned_data["rsshub_use_global_config"],
            "rsshub_custom_base_url": self.cleaned_data["rsshub_custom_base_url"],
            "rsshub_custom_access_key": self.cleaned_data["rsshub_custom_access_key"],
            "rsshub_format": self.cleaned_data["rsshub_format"],
            "proxy_enabled": self.cleaned_data["proxy_enabled"],
            "proxy_host": self.cleaned_data["proxy_host"],
            "proxy_port": self.cleaned_data["proxy_port"],
            "proxy_type": self.cleaned_data["proxy_type"],
            "proxy_username": self.cleaned_data["proxy_username"],
            "proxy_password": self.cleaned_data["proxy_password"],
        }


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
        widget=forms.NumberInput(attrs={"min": 0, "step": "1"}),
    )
    category = forms.CharField(max_length=50, required=False)
    is_active = forms.BooleanField(required=False, initial=True)

    def __init__(
        self,
        *args: Any,
        instance: _PolicyKeywordInstance | None = None,
        **kwargs: Any,
    ) -> None:
        provided_initial = kwargs.pop("initial", None)
        if provided_initial is None:
            initial: dict[str, Any] = {}
        elif isinstance(provided_initial, Mapping):
            initial = {str(key): value for key, value in provided_initial.items()}
        else:
            raise TypeError("initial must be a mapping")
        self.instance: _FormInstance = instance if instance is not None else _NewFormInstance()
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

    def clean_keywords_text(self) -> list[str]:
        """Normalize Chinese/ASCII comma-separated keywords into non-empty values."""

        raw = self.cleaned_data.get("keywords_text")
        if not isinstance(raw, str):
            raise forms.ValidationError("至少填写一个关键词")
        keywords = [item.strip() for item in raw.replace("，", ",").split(",") if item.strip()]
        if not keywords:
            raise forms.ValidationError("至少填写一个关键词")
        return keywords

    def to_payload(self) -> dict[str, Any]:
        """Return the validated policy-keyword write whitelist."""

        return {
            "level": self.cleaned_data["level"],
            "keywords": self.cleaned_data["keywords_text"],
            "weight": self.cleaned_data["weight"],
            "category": self.cleaned_data["category"] or None,
            "is_active": self.cleaned_data["is_active"],
        }
