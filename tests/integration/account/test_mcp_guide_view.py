from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.account.infrastructure.models import (
    AccountProfileModel,
    SystemSettingsModel,
    UserAccessTokenModel,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


def _ensure_account_profile(user) -> None:
    AccountProfileModel.objects.get_or_create(
        user=user,
        defaults={
            "display_name": user.username,
            "risk_tolerance": "moderate",
            "approval_status": "approved",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
            "mcp_enabled": True,
        },
    )


@pytest.mark.django_db
def test_mcp_guide_view_renders_connection_contract():
    user = get_user_model().objects.create_user(
        username="mcp_guide_user",
        email="mcp-guide@example.com",
        password="testpass123",
    )
    _ensure_account_profile(user)
    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.allow_token_plaintext_view = True
    settings_obj.save()

    account = SimulatedAccountModel.objects.create(
        user=user,
        account_name="Codex测试账户",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("80000.00"),
        current_market_value=Decimal("25000.00"),
        total_value=Decimal("105000.00"),
        total_return=5.0,
        start_date=settings_obj.created_at.date(),
    )
    _, raw_key = UserAccessTokenModel.create_token(
        user=user,
        name="codex-local",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )

    client = Client()
    client.force_login(user)
    response = client.get("/account/mcp/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    content = response.content.decode("utf-8")
    assert "MCP 接入说明" in content
    assert raw_key in content
    assert "Authorization: Token" in content
    assert "只读 Token" in content
    assert "只读" in content
    assert "/api/account/profile/" in content
    assert "/api/dashboard/v1/summary/" in content
    assert "agomtradepro_mcp" in content
    assert "codex-local" in content
    assert str(account.id) in content


@pytest.mark.django_db
def test_create_self_token_view_supports_next_redirect_to_mcp_guide():
    user = get_user_model().objects.create_user(
        username="mcp_redirect_user",
        email="mcp-redirect@example.com",
        password="testpass123",
    )
    _ensure_account_profile(user)

    client = Client()
    client.force_login(user)
    response = client.post(
        "/account/settings/tokens/create/",
        {
            "token_name": "codex-redirect",
            "next": "/account/mcp/",
        },
        follow=False,
    )

    assert response.status_code == 302
    assert response["Location"] == "/account/mcp/"
    assert UserAccessTokenModel.objects.filter(
        user=user,
        is_active=True,
        name="codex-redirect",
    ).exists()
