"""Forms for policy management pages."""

from django import forms

from apps.policy.infrastructure.models import PolicyLog, RSSSourceConfigModel, PolicyLevelKeywordModel


class PolicyEventForm(forms.ModelForm):
    class Meta:
        model = PolicyLog
        fields = ["event_date", "level", "title", "description", "evidence_url"]
        widgets = {
            "event_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 4}),
        }


class RSSSourceForm(forms.ModelForm):
    class Meta:
        model = RSSSourceConfigModel
        fields = [
            "name",
            "url",
            "category",
            "is_active",
            "fetch_interval_hours",
            "extract_content",
            "rsshub_enabled",
            "rsshub_route_path",
        ]
        widgets = {
            "fetch_interval_hours": forms.NumberInput(attrs={"min": 1, "max": 168}),
        }


class PolicyKeywordForm(forms.ModelForm):
    keywords_text = forms.CharField(
        label="关键词（逗号分隔）",
        required=True,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="例如：降准, 降息, 宽松",
    )

    class Meta:
        model = PolicyLevelKeywordModel
        fields = ["level", "category", "weight", "is_active"]
        widgets = {
            "weight": forms.NumberInput(attrs={"min": 0, "step": "0.1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.keywords:
            self.fields["keywords_text"].initial = ", ".join(self.instance.keywords)

    def clean_keywords_text(self):
        raw = self.cleaned_data["keywords_text"]
        keywords = [item.strip() for item in raw.split(",") if item.strip()]
        if not keywords:
            raise forms.ValidationError("至少填写一个关键词")
        return keywords

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.keywords = self.cleaned_data["keywords_text"]
        if commit:
            instance.save()
        return instance
