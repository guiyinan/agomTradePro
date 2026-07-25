import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.ai_provider.infrastructure.models import AIProviderConfig


@pytest.fixture
def page_admin(db):
    return get_user_model().objects.create_superuser(
        username="provider-page-admin",
        email="provider-page-admin@example.com",
        password="testpass123",
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("query", "expected_limit"),
    [
        ("provider=bad&limit=not-a-number&status=bogus", 100),
        ("provider=-1&limit=-5", 100),
        ("provider=999999&limit=999999", 500),
    ],
)
def test_usage_log_page_normalizes_untrusted_filters(
    client,
    page_admin,
    query,
    expected_limit,
):
    client.force_login(page_admin)

    response = client.get(f"{reverse('ai_provider:logs')}?{query}")

    assert response.status_code == 200
    assert response.context["filter_limit"] == expected_limit
    assert response.context["filter_status"] is None


@pytest.mark.django_db
def test_system_management_page_includes_inactive_provider(client, page_admin):
    inactive = AIProviderConfig.objects.create(
        name="inactive-system-provider",
        scope="system",
        provider_type="openai",
        is_active=False,
        priority=10,
        base_url="https://inactive.example.invalid/v1",
        api_key="sk-test",
        default_model="gpt-4o-mini",
    )
    client.force_login(page_admin)

    response = client.get(reverse("ai_provider:manage"))

    assert response.status_code == 200
    assert inactive.id in {provider.id for provider in response.context["providers"]}
