from unittest.mock import Mock

from apps.ai_provider.infrastructure.adapters import AIFailoverHelper
from apps.policy.infrastructure.adapters.ai_policy_classifier import (
    create_ai_policy_classifier,
)


def test_ai_failover_helper_reports_missing_healthy_providers(mocker) -> None:
    adapter_instance = Mock()
    adapter_instance.is_available.return_value = False
    mocker.patch(
        "apps.ai_provider.infrastructure.adapters.OpenAICompatibleAdapter",
        return_value=adapter_instance,
    )

    helper = AIFailoverHelper(
        [
            {
                "name": "ds",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "secret",
                "default_model": "deepseek-chat",
            }
        ]
    )

    result = helper.chat_completion_with_failover(messages=[{"role": "user", "content": "hi"}])

    assert helper.has_available_adapters is False
    assert "ds: provider health check failed" in helper.describe_unavailable_providers()
    assert result["status"] == "error"
    assert "No healthy AI providers available" in result["error_message"]


def test_create_ai_policy_classifier_returns_none_without_healthy_provider(
    mocker, caplog
) -> None:
    caplog.set_level("WARNING")
    provider_repo = Mock()
    provider = Mock()
    provider.name = "ds"
    provider.base_url = "https://api.deepseek.com/v1"
    provider.default_model = "deepseek-chat"
    provider.priority = 10
    provider.extra_config = {}
    provider_repo.get_active_configured_system_providers.return_value = [provider]
    provider_repo.get_api_key.return_value = "secret"
    mocker.patch(
        "apps.policy.infrastructure.adapters.ai_policy_classifier.AIProviderRepository",
        return_value=provider_repo,
    )
    helper = Mock()
    helper.has_available_adapters = False
    helper.describe_unavailable_providers.return_value = "ds: provider health check failed"
    mocker.patch(
        "apps.policy.infrastructure.adapters.ai_policy_classifier.AIFailoverHelper",
        return_value=helper,
    )

    classifier = create_ai_policy_classifier()

    assert classifier is None
    assert "no healthy providers are available" in caplog.text.lower()


def test_create_ai_policy_classifier_skips_provider_without_usable_api_key(
    mocker, caplog
) -> None:
    caplog.set_level("WARNING")
    provider_repo = Mock()
    provider = Mock()
    provider.name = "ds"
    provider.base_url = "https://api.deepseek.com/v1"
    provider.default_model = "deepseek-chat"
    provider.priority = 10
    provider.extra_config = {}
    provider_repo.get_active_configured_system_providers.return_value = [provider]
    provider_repo.get_api_key.return_value = ""
    mocker.patch(
        "apps.policy.infrastructure.adapters.ai_policy_classifier.AIProviderRepository",
        return_value=provider_repo,
    )

    classifier = create_ai_policy_classifier()

    assert classifier is None
    assert "no provider credentials are usable" in caplog.text.lower()
