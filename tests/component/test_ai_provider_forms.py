from apps.ai_provider.interface.forms import AIProviderConfigForm


def test_provider_form_never_rerenders_submitted_api_key():
    secret = "sk-sensitive-value-that-must-not-return"
    form = AIProviderConfigForm(
        data={
            "name": "provider",
            "provider_type": "openai",
            "is_active": True,
            "priority": 10,
            "base_url": "https://example.invalid/v1",
            "api_key": secret,
            "default_model": "gpt-4o-mini",
            "api_mode": "dual",
            "fallback_enabled": True,
            "extra_config_text": "{invalid-json",
        }
    )

    assert form.is_valid() is False
    rendered = form.as_p()
    assert secret not in rendered
    assert 'name="api_key"' in rendered
