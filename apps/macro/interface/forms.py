"""Input-only forms for macro configuration compatibility pages.

This module deliberately does not bind a Django ModelForm to the Data Center
provider table.  Persistence must go through the Data Center Application
public port so credentials are encrypted and the owner boundary remains
auditable.
"""

from django import forms


class DataSourceConfigForm(forms.Form):
    """Validate provider input without exposing a direct ORM save path."""

    SOURCE_TYPE_CHOICES = (
        ("tushare", "Tushare Pro"),
        ("akshare", "AKShare"),
        ("eastmoney", "EastMoney"),
        ("qmt", "QMT (XtQuant)"),
        ("fred", "FRED"),
        ("wind", "Wind"),
        ("choice", "Choice"),
    )

    name = forms.CharField(max_length=100)
    source_type = forms.ChoiceField(choices=SOURCE_TYPE_CHOICES)
    is_active = forms.BooleanField(required=False, initial=True)
    priority = forms.IntegerField(min_value=0, max_value=999, initial=100)
    api_endpoint = forms.URLField(required=False)
    http_url = forms.URLField(required=False)
    api_key = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False))
    api_secret = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False))
    extra_config = forms.JSONField(required=False)
    description = forms.CharField(required=False, widget=forms.Textarea)

    class Meta:
        """Retain the historical class namespace for template discovery."""
