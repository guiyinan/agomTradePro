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
    assert (
        b"/tui/?screen=ai-ops.system-providers&amp;action=ai-ops.system-ai-logs"
        in response.content
    )


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
    assert (
        b"/tui/?screen=ai-ops.system-providers&amp;action=ai-ops.list-system-providers"
        in response.content
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("scope", "is_admin", "detail_action", "update_action", "screen"),
    [
        (
            "system",
            True,
            "ai-ops.system-provider-detail",
            "ai-ops.update-system-provider",
            "ai-ops.system-providers",
        ),
        (
            "user",
            False,
            "ai-ops.my-provider-detail",
            "ai-ops.update-my-provider",
            "ai-ops.providers",
        ),
    ],
)
def test_provider_detail_and_edit_publish_scope_aware_tui_deep_links(
    client,
    page_admin,
    scope,
    is_admin,
    detail_action,
    update_action,
    screen,
):
    user = (
        page_admin
        if is_admin
        else get_user_model().objects.create_user(
            username="provider-page-user",
            email="provider-page-user@example.com",
            password="testpass123",
        )
    )
    provider = AIProviderConfig.objects.create(
        name=f"{scope}-provider",
        scope=scope,
        owner_user=None if scope == "system" else user,
        provider_type="openai",
        is_active=True,
        priority=10,
        base_url=f"https://{scope}.example.invalid/v1",
        api_key="sk-test",
        default_model="gpt-4o-mini",
    )
    client.force_login(user)

    detail_response = client.get(reverse("ai_provider:detail", args=[provider.id]))
    edit_response = client.get(reverse("ai_provider:edit", args=[provider.id]))

    assert detail_response.status_code == 200
    assert edit_response.status_code == 200
    detail_href = (
        f"/tui/?screen={screen}&amp;action={detail_action}"
        f"&amp;provider_id={provider.id}"
    ).encode()
    edit_href = (
        f"/tui/?screen={screen}&amp;action={update_action}"
        f"&amp;provider_id={provider.id}"
    ).encode()
    assert detail_href in detail_response.content
    assert edit_href in edit_response.content


@pytest.mark.django_db
def test_personal_provider_and_log_pages_publish_user_tui_tasks(client):
    user = get_user_model().objects.create_user(
        username="provider-self-service-user",
        email="provider-self-service@example.com",
        password="testpass123",
    )
    client.force_login(user)

    provider_response = client.get(reverse("ai_provider:my-providers"))
    logs_response = client.get(f"{reverse('ai_provider:logs')}?status=success&limit=25")

    assert provider_response.status_code == 200
    assert (
        b"/tui/?screen=ai-ops.providers&amp;action=ai-ops.list-my-providers"
        in provider_response.content
    )
    assert logs_response.status_code == 200
    assert (
        b"/tui/?screen=ai-ops.providers&amp;action=ai-ops.my-ai-logs"
        b"&amp;status=success&amp;limit=25"
        in logs_response.content
    )


@pytest.mark.django_db
def test_quota_page_publishes_admin_tui_task(client, page_admin):
    client.force_login(page_admin)

    response = client.get(reverse("ai_provider:quota-manage"))

    assert response.status_code == 200
    assert (
        b"/tui/?screen=ai-ops.user-quotas&amp;action=ai-ops.list-user-quotas"
        in response.content
    )
