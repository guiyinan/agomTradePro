from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.ai_provider.infrastructure.models import (
    AIProviderConfig,
    AIUsageLog,
    AIUserFallbackQuota,
)


def _provider(**overrides):
    values = {
        "name": "model-boundary-provider",
        "scope": "system",
        "provider_type": "custom",
        "base_url": "https://example.invalid/v1",
        "api_key": "sk-test",
        "default_model": "gpt-4o-mini",
    }
    values.update(overrides)
    return AIProviderConfig(**values)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"scope": "user"}, "user providers require an owner"),
        ({"base_url": "https://user:secret@example.invalid/v1"}, "without credentials"),
        ({"priority": True}, "positive integer"),
        ({"daily_budget_limit": Decimal("NaN")}, "finite and non-negative"),
        (
            {"daily_budget_limit": 11, "monthly_budget_limit": 10},
            "monthly budget cannot be below the daily budget",
        ),
        ({"extra_config": {"api_key": "secret"}}, "credentials are not allowed"),
        ({"extra_config": {"timeout": 301}}, "extra_config.timeout is invalid"),
        ({"extra_config": {"temperature": float("inf")}}, "must be finite"),
    ],
)
def test_provider_direct_write_rejects_invalid_governance_data(overrides, message):
    with pytest.raises(ValidationError, match=message):
        _provider(**overrides).save()

    assert AIProviderConfig.objects.count() == 0


@pytest.mark.django_db
def test_provider_direct_write_rejects_system_owner_and_detaches_extra_config():
    user = get_user_model().objects.create_user(username="provider-owner")
    with pytest.raises(ValidationError, match="system providers cannot have an owner"):
        _provider(owner_user=user).save()

    caller_config = {"timeout": 15, "supported_models": ["model-a"]}
    provider = _provider(name="detached-config", extra_config=caller_config)
    provider.save()
    caller_config["timeout"] = 200
    caller_config["supported_models"].append("model-b")

    assert provider.extra_config == {"timeout": 15, "supported_models": ["model-a"]}
    provider.refresh_from_db()
    assert provider.extra_config == {"timeout": 15, "supported_models": ["model-a"]}


@pytest.mark.django_db
def test_usage_direct_write_validates_attribution_and_accounting():
    _provider().save()
    saved_provider = AIProviderConfig.objects.get(name="model-boundary-provider")

    with pytest.raises(ValidationError, match="personal usage attribution is invalid"):
        AIUsageLog.objects.create(
            provider=saved_provider,
            provider_scope="personal",
            quota_charged=False,
            model="gpt-4o-mini",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            estimated_cost=0,
            response_time_ms=1,
            status="success",
        )
    with pytest.raises(ValidationError, match="total_tokens cannot be below"):
        AIUsageLog.objects.create(
            provider=saved_provider,
            provider_scope="system_global",
            quota_charged=False,
            model="gpt-4o-mini",
            prompt_tokens=2,
            completion_tokens=2,
            total_tokens=3,
            estimated_cost=0,
            response_time_ms=1,
            status="success",
        )


@pytest.mark.django_db
def test_usage_evidence_redacts_credentials_and_rejects_instance_mutation():
    provider = _provider()
    provider.save()
    log = AIUsageLog.objects.create(
        provider=provider,
        provider_scope="system_global",
        quota_charged=False,
        model="gpt-4o-mini",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        estimated_cost=Decimal("0.001"),
        response_time_ms=4,
        status="error",
        error_message="token=top-secret postgres://alice:password@db.internal/main",
        request_metadata={
            "authorization": "Bearer top-secret",
            "nested": {"password": "database-password"},
            "url": "https://user:password@example.invalid/path",
        },
    )

    assert "top-secret" not in log.error_message
    assert "password@" not in log.error_message
    assert log.request_metadata["authorization"] == "***"
    assert log.request_metadata["nested"]["password"] == "***"
    assert "password@" not in log.request_metadata["url"]

    log.total_tokens = 3
    with pytest.raises(ValidationError, match="immutable"):
        log.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        log.delete()


@pytest.mark.django_db
def test_fallback_quota_rejects_invalid_direct_write():
    user = get_user_model().objects.create_user(username="quota-owner")

    with pytest.raises(ValidationError, match="monthly limit cannot be below daily limit"):
        AIUserFallbackQuota.objects.create(user=user, daily_limit=11, monthly_limit=10)
    with pytest.raises(ValidationError, match="finite and non-negative"):
        AIUserFallbackQuota.objects.create(
            user=user,
            daily_limit=Decimal("NaN"),
            monthly_limit=100,
        )
