"""Forms for macro configuration pages."""

from django import forms

from apps.macro.infrastructure.models import DataSourceConfig


class DataSourceConfigForm(forms.ModelForm):
    class Meta:
        model = DataSourceConfig
        fields = [
            "name",
            "source_type",
            "is_active",
            "priority",
            "api_endpoint",
            "api_key",
            "api_secret",
            "description",
        ]
        widgets = {
            "priority": forms.NumberInput(attrs={"min": 0, "max": 999}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }
