"""Forms for macro configuration pages."""

from django import forms

from apps.data_center.infrastructure.models import ProviderConfigModel as DataSourceConfig


class DataSourceConfigForm(forms.ModelForm):
    class Meta:
        model = DataSourceConfig
        fields = [
            "name",
            "source_type",
            "is_active",
            "priority",
            "api_endpoint",
            "http_url",
            "api_key",
            "api_secret",
            "extra_config",
            "description",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "source_type": forms.Select(attrs={"class": "form-control"}),
            "priority": forms.NumberInput(attrs={"min": 0, "max": 999, "class": "form-control"}),
            "api_endpoint": forms.URLInput(attrs={"class": "form-control"}),
            "http_url": forms.URLInput(attrs={"class": "form-control"}),
            "api_key": forms.TextInput(attrs={"class": "form-control"}),
            "api_secret": forms.TextInput(attrs={"class": "form-control"}),
            "extra_config": forms.Textarea(attrs={"rows": 4, "class": "form-control"}),
            "description": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }
