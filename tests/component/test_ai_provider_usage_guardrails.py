from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError

from apps.ai_provider.infrastructure.models import (
    AIProviderConfig,
    AIUsageLog,
    AIUserFallbackQuota,
)
from apps.ai_provider.infrastructure.repositories import (
    AIUsageRepository,
    AIUserFallbackQuotaRepository,
)


@pytest.fixture
def provider(db) -> AIProviderConfig:
    return AIProviderConfig.objects.create(
        name="usage-guardrail-provider",
        provider_type="custom",
        base_url="https://example.invalid/v1",
        default_model="gpt-4o-mini",
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides",
    [
        {"prompt_tokens": -1},
        {"completion_tokens": -1},
        {"total_tokens": 1},
        {"estimated_cost": -0.01},
        {"estimated_cost": float("nan")},
        {"response_time_ms": -1},
        {"status": "unknown"},
        {"provider_scope": "unknown"},
    ],
)
def test_usage_repository_rejects_invalid_accounting_before_write(
    provider,
    overrides,
) -> None:
    payload = {
        "provider": provider,
        "model": "gpt-4o-mini",
        "prompt_tokens": 2,
        "completion_tokens": 3,
        "total_tokens": 5,
        "estimated_cost": 0.01,
        "response_time_ms": 100,
        "status": "success",
        "provider_scope": "system_global",
    }
    payload.update(overrides)

    with pytest.raises(ValueError):
        AIUsageRepository().log_usage(**payload)

    assert AIUsageLog.objects.count() == 0
    provider.refresh_from_db()
    assert provider.last_used_at is None


@pytest.mark.django_db
def test_usage_log_and_last_used_update_are_atomic(provider, mocker) -> None:
    mocker.patch.object(provider, "save", side_effect=DatabaseError("write failed"))

    with pytest.raises(DatabaseError, match="write failed"):
        AIUsageRepository().log_usage(
            provider=provider,
            model="gpt-4o-mini",
            prompt_tokens=2,
            completion_tokens=3,
            total_tokens=5,
            estimated_cost=0.01,
            response_time_ms=100,
            status="success",
        )

    assert AIUsageLog.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("daily_limit", "monthly_limit"),
    [
        (Decimal("-1"), Decimal("10")),
        (Decimal("1"), Decimal("NaN")),
    ],
)
def test_fallback_quota_rejects_invalid_limits_before_write(
    daily_limit,
    monthly_limit,
) -> None:
    user = get_user_model().objects.create_user(username=f"quota-{daily_limit}-{monthly_limit}")

    with pytest.raises(ValueError, match="finite nonnegative"):
        AIUserFallbackQuotaRepository().upsert_for_user(
            user=user,
            daily_limit=daily_limit,
            monthly_limit=monthly_limit,
        )

    assert not AIUserFallbackQuota.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_recent_usage_limit_is_bounded() -> None:
    with pytest.raises(ValueError, match="between 1 and 1000"):
        AIUsageRepository().get_recent_logs(limit=0)
