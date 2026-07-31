from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.account.application import interface_services as account_interface_services
from apps.account.application.volatility_use_cases import VolatilityAnalysisUseCase
from apps.account.domain.services import VolatilityMetrics
from apps.account.infrastructure.models import (
    AccountProfileModel,
    AssetCategoryModel,
    CapitalFlowModel,
    CurrencyModel,
    ExchangeRateModel,
    PortfolioModel,
    PortfolioObserverGrantModel,
    PositionModel,
    SystemSettingsModel,
    TransactionModel,
    UserAccessTokenModel,
)


@pytest.fixture
def auth_user(db):
    user = get_user_model().objects.create_user(
        username="account_api_user",
        password="testpass123",
        email="account@example.com",
    )
    AccountProfileModel.objects.update_or_create(
        user=user,
        defaults={
            "display_name": "Account API User",
            "initial_capital": Decimal("1000000.00"),
            "approval_status": "approved",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
        },
    )
    return user


@pytest.fixture
def admin_user(db):
    user = get_user_model().objects.create_superuser(
        username="account_api_admin",
        password="testpass123",
        email="admin@example.com",
    )
    AccountProfileModel.objects.update_or_create(
        user=user,
        defaults={
            "display_name": "Account API Admin",
            "initial_capital": Decimal("1000000.00"),
            "approval_status": "approved",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
            "rbac_role": "admin",
        },
    )
    return user


@pytest.fixture
def admin_authenticated_client(api_client, admin_user):
    api_client.force_authenticate(user=admin_user)
    return api_client


@pytest.mark.django_db
def test_account_health_contract(authenticated_client):
    response = authenticated_client.get("/api/account/health/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["service"] == "account"


@pytest.mark.django_db
def test_account_profile_and_password_self_service_contract(
    authenticated_client,
    auth_user,
):
    profile_response = authenticated_client.get("/api/account/profile/")

    assert profile_response.status_code == 200
    assert profile_response.json()["email"] == "account@example.com"

    wrong_password = authenticated_client.post(
        "/api/account/profile/password/",
        {
            "current_password": "wrong-password",
            "new_password": "A-different-password-2026!",
        },
        format="json",
    )
    assert wrong_password.status_code == 403

    changed = authenticated_client.post(
        "/api/account/profile/password/",
        {
            "current_password": "testpass123",
            "new_password": "A-different-password-2026!",
        },
        format="json",
    )
    assert changed.status_code == 200
    assert changed.json() == {"success": True, "message": "密码已更新"}
    auth_user.refresh_from_db()
    assert auth_user.check_password("A-different-password-2026!") is True


@pytest.mark.django_db
def test_account_self_service_tui_screen_exposes_password_and_ledger_tasks(
    authenticated_client,
):
    response = authenticated_client.get("/api/tui/screens/account.self-service/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["screen"]["key"] == "account.self-service"
    action_by_key = {action["key"]: action for action in payload["actions"]}
    assert set(action_by_key) >= {
        "account-settings.read-profile",
        "account-settings.update-profile",
        "account-settings.change-password",
        "account-settings.list-capital-flows",
        "account-settings.create-capital-flow",
        "account-settings.delete-capital-flow",
        "account-settings.list-trading-costs",
        "account-settings.create-trading-cost",
    }
    password_fields = action_by_key["account-settings.change-password"]["fields"]
    assert {field["input_type"] for field in password_fields} == {"password"}


@pytest.mark.django_db
def test_account_volatility_history_uses_domain_metric_fields(
    authenticated_client,
    auth_user,
    monkeypatch,
):
    """The chart contract must project the actual VolatilityMetrics fields."""

    authenticated_client.force_login(auth_user)
    monkeypatch.setattr(
        account_interface_services,
        "get_active_portfolio_for_user",
        lambda _user_id: SimpleNamespace(id=17),
    )
    analysis = SimpleNamespace(
        portfolio_id=17,
        current_volatility_30d=0.20,
        current_volatility_60d=0.18,
        current_volatility_90d=0.16,
        target_volatility=0.15,
        adjustment_result=SimpleNamespace(
            should_reduce=True,
            reduction_reason="above target",
            suggested_position_multiplier=0.75,
        ),
        volatility_history=[
            VolatilityMetrics(
                daily_volatility=0.01,
                annualized_volatility=0.1587,
                window_days=30,
                as_of_date=date(2026, 7, 22),
            )
        ],
    )
    monkeypatch.setattr(
        VolatilityAnalysisUseCase,
        "analyze_portfolio_volatility",
        lambda self, *, portfolio_id, user_id: analysis,
    )

    response = authenticated_client.get("/api/account/volatility/")

    assert response.status_code == 200
    history = response.json()["data"]["history"]
    assert history == [
        {
            "date": "2026-07-22",
            "daily_volatility": 0.01,
            "rolling_volatility_30d": 0.1587,
            "annualized_volatility": 0.1587,
        }
    ]


@pytest.mark.django_db
def test_account_tui_volatility_projects_percentage_chart_rows(
    authenticated_client,
    auth_user,
    monkeypatch,
):
    authenticated_client.force_login(auth_user)
    monkeypatch.setattr(
        account_interface_services,
        "get_active_portfolio_for_user",
        lambda _user_id: SimpleNamespace(id=17),
    )
    analysis = SimpleNamespace(
        portfolio_id=17,
        current_volatility_30d=0.20,
        current_volatility_60d=0.18,
        current_volatility_90d=0.16,
        target_volatility=0.15,
        adjustment_result=SimpleNamespace(
            should_reduce=True,
            reduction_reason="above target",
            suggested_position_multiplier=0.75,
        ),
        volatility_history=[
            VolatilityMetrics(
                daily_volatility=0.01,
                annualized_volatility=0.1587,
                window_days=30,
                as_of_date=date(2026, 7, 22),
            )
        ],
    )
    monkeypatch.setattr(
        VolatilityAnalysisUseCase,
        "analyze_portfolio_volatility",
        lambda self, *, portfolio_id, user_id: analysis,
    )

    response = authenticated_client.get("/api/account/tui/volatility/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["volatility_30d_percent"] == 20.0
    assert payload["target_percent"] == 15.0
    assert payload["suggested_multiplier_percent"] == 75.0
    assert payload["history"] == [
        {
            "date": "2026-07-22",
            "annualized_volatility_percent": 15.87,
            "target_percent": 15.0,
            "target_upper_percent": 18.0,
            "target_lower_percent": 12.0,
        }
    ]


@pytest.mark.django_db
def test_account_tui_volatility_returns_explicit_empty_state(
    authenticated_client,
    auth_user,
    monkeypatch,
):
    authenticated_client.force_login(auth_user)
    monkeypatch.setattr(
        account_interface_services,
        "get_active_portfolio_for_user",
        lambda _user_id: None,
    )

    response = authenticated_client.get("/api/account/tui/volatility/")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "has_portfolio": False,
        "message": "暂无活跃投资组合",
        "history": [],
    }


@pytest.mark.django_db
def test_account_mcp_self_contract(authenticated_client, auth_user):
    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.allow_token_plaintext_view = True
    settings_obj.save(update_fields=["allow_token_plaintext_view", "updated_at"])
    UserAccessTokenModel.create_token(
        user=auth_user,
        name="sdk-token",
        created_by=auth_user,
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )

    response = authenticated_client.get("/api/account/mcp/self/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["username"] == auth_user.username
    assert payload["mcp_enabled"] is True
    assert payload["active_token_count"] == 1
    assert payload["preferred_token"]["name"] == "sdk-token"
    assert payload["preferred_token"]["display_token"]
    assert payload["current_token_display"]
    assert payload["agent_bootstrap_token_ready"] is True
    assert payload["route_endpoint"].endswith("/api/ai-capability/route/")
    assert payload["web_endpoint"].endswith("/api/ai-capability/web/")
    assert payload["capability_endpoint"].endswith("/api/ai-capability/capabilities/")
    assert "Capability Catalog" in payload["agent_bootstrap_prompt"]
    assert payload["token_access_level_choices"][0]["value"] == "read_only"


@pytest.mark.django_db
def test_account_mcp_self_uses_configured_https_origin_instead_of_request_ip(
    authenticated_client,
    auth_user,
    settings,
):
    settings.APP_BASE_URL = "https://demo.agomtrade.pro/"
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "62.171.144.39"]
    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.allow_token_plaintext_view = True
    settings_obj.save(update_fields=["allow_token_plaintext_view", "updated_at"])
    UserAccessTokenModel.create_token(
        user=auth_user,
        name="canonical-https-token",
        created_by=auth_user,
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )

    response = authenticated_client.get(
        "/api/account/mcp/self/",
        HTTP_HOST="62.171.144.39",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["base_url"] == "https://demo.agomtrade.pro"
    assert payload["route_endpoint"].startswith("https://demo.agomtrade.pro/")
    assert payload["access_package"]["transport_security"] == "https"
    assert payload["access_package"]["certificate_validation"] == "required"
    assert payload["self_service_state"] == "ready"


def test_mcp_public_origin_falls_back_to_production_https_domain(settings):
    settings.APP_BASE_URL = ""
    settings.DEBUG = False
    settings.PUBLIC_HTTPS_ENABLED = True
    settings.ALLOWED_HOSTS = ["62.171.144.39", "demo.agomtrade.pro", "localhost"]

    base_url = account_interface_services.resolve_mcp_public_base_url("http://62.171.144.39")

    assert base_url == "https://demo.agomtrade.pro"


@pytest.mark.django_db
def test_admin_user_access_governance_contract_and_mutations(
    admin_authenticated_client,
    admin_user,
):
    user = get_user_model().objects.create_user(
        username="pending_governed_user",
        password="testpass123",
        email="pending@example.com",
        is_active=False,
    )
    profile, _ = AccountProfileModel.objects.update_or_create(
        user=user,
        defaults={
            "display_name": "Pending Governed User",
            "initial_capital": Decimal("1000000.00"),
            "approval_status": "pending",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
        },
    )

    list_response = admin_authenticated_client.get(
        "/api/account/admin/users/",
        {"approval_status": "pending", "q": "governed"},
    )

    assert list_response.status_code == 200
    assert list_response["Content-Type"].startswith("application/json")
    payload = list_response.json()
    assert payload["total_count"] == 1
    assert payload["rows"][0]["user_id"] == user.id
    assert payload["rows"][0]["approval_status"] == "pending"
    assert {row["value"] for row in payload["role_choices"]} >= {"admin", "read_only"}

    approve_response = admin_authenticated_client.post(
        f"/api/account/admin/users/{user.id}/approve/",
        {},
        format="json",
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["success"] is True
    user.refresh_from_db()
    profile.refresh_from_db()
    assert user.is_active is True
    assert profile.approval_status == "approved"
    assert profile.approved_by_id == admin_user.id

    role_response = admin_authenticated_client.post(
        f"/api/account/admin/users/{user.id}/role/",
        {"rbac_role": "analyst"},
        format="json",
    )
    assert role_response.status_code == 200
    profile.refresh_from_db()
    assert profile.rbac_role == "analyst"

    reset_response = admin_authenticated_client.post(
        f"/api/account/admin/users/{user.id}/reset/",
        {},
        format="json",
    )
    assert reset_response.status_code == 200
    profile.refresh_from_db()
    assert profile.approval_status == "pending"

    reject_response = admin_authenticated_client.post(
        f"/api/account/admin/users/{user.id}/reject/",
        {"rejection_reason": "身份材料待补充"},
        format="json",
    )
    assert reject_response.status_code == 200
    profile.refresh_from_db()
    assert profile.approval_status == "rejected"
    assert profile.rejection_reason == "身份材料待补充"


@pytest.mark.django_db
def test_user_access_governance_requires_admin(authenticated_client):
    response = authenticated_client.get("/api/account/admin/users/")

    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/json")


@pytest.mark.django_db
def test_user_access_governance_tui_screen_exposes_task_actions(
    admin_authenticated_client,
):
    response = admin_authenticated_client.get("/api/tui/screens/identity-access.user-governance/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["screen"]["key"] == "identity-access.user-governance"
    assert payload["screen"]["audience"] == "admin"
    assert payload["screen"]["user_experience"]["primary_task"]
    assert payload["screen"]["default_action_key"] == "identity-access.user-list"
    assert {action["key"] for action in payload["actions"]} >= {
        "identity-access.user-list",
        "identity-access.approve-user",
        "identity-access.reject-user",
        "identity-access.reset-user",
        "identity-access.set-user-role",
    }


@pytest.mark.django_db
def test_account_mcp_self_exposes_one_canonical_access_package(
    authenticated_client,
    auth_user,
):
    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.allow_token_plaintext_view = True
    settings_obj.save(update_fields=["allow_token_plaintext_view", "updated_at"])
    UserAccessTokenModel.create_token(
        user=auth_user,
        name="recommended-token",
        created_by=auth_user,
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )

    response = authenticated_client.get("/api/account/mcp/self/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["self_service_state"] == "ready"
    access_package = payload["access_package"]
    assert access_package["token"]
    assert access_package["route_endpoint"].endswith("/api/ai-capability/route/")
    assert access_package["capability_catalog_endpoint"].endswith(
        "/api/ai-capability/capabilities/"
    )
    assert access_package["agent_prompt"]
    assert access_package["environment_statement"]
    assert payload["recommended_token_id"]
    assert sum(bool(row["is_recommended"]) for row in payload["access_tokens"]) == 1
    for row in payload["access_tokens"]:
        assert "plaintext" not in row
        assert "display_token" not in row
        assert "token" not in row


@pytest.mark.django_db
def test_account_mcp_self_prefers_a_recoverable_token_over_a_newer_legacy_preview(
    authenticated_client,
    auth_user,
):
    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.allow_token_plaintext_view = True
    settings_obj.save(update_fields=["allow_token_plaintext_view", "updated_at"])
    recoverable_token, recoverable_key = UserAccessTokenModel.create_token(
        user=auth_user,
        name="recoverable-token",
        created_by=auth_user,
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )
    legacy_token, _ = UserAccessTokenModel.create_token(
        user=auth_user,
        name="newer-legacy-preview",
        created_by=auth_user,
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )
    legacy_token.key_encrypted = ""
    legacy_token.save(update_fields=["key_encrypted", "updated_at"])

    response = authenticated_client.get("/api/account/mcp/self/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["self_service_state"] == "ready"
    assert payload["recommended_token_id"] == recoverable_token.id
    assert payload["access_package"]["token"] == recoverable_key
    assert "..." not in payload["access_package"]["token"]


@pytest.mark.django_db
def test_account_mcp_self_marks_loopback_access_as_same_machine_only(auth_user):
    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.allow_token_plaintext_view = True
    settings_obj.save(update_fields=["allow_token_plaintext_view", "updated_at"])
    UserAccessTokenModel.create_token(
        user=auth_user,
        name="local-token",
        created_by=auth_user,
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )

    payload = account_interface_services.build_self_mcp_api_payload(
        auth_user.id,
        base_url="http://127.0.0.1:8000",
    )

    assert payload["access_package"]["same_machine_only"] is True
    assert payload["access_package"]["transport_security"] == "local_http"
    assert "同一台机器" in payload["access_package"]["environment_statement"]


@pytest.mark.django_db
def test_account_mcp_self_blocks_remote_http_access_package(auth_user):
    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.allow_token_plaintext_view = True
    settings_obj.save(update_fields=["allow_token_plaintext_view", "updated_at"])
    UserAccessTokenModel.create_token(
        user=auth_user,
        name="remote-http-token",
        created_by=auth_user,
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )

    payload = account_interface_services.build_self_mcp_api_payload(
        auth_user.id,
        base_url="http://203.0.113.10",
    )

    assert payload["self_service_state"] == "unavailable"
    assert payload["self_service_blocking_reason"] == "https_required"
    assert payload["access_package"]["transport_security"] == "insecure_http"


@pytest.mark.django_db
def test_account_mcp_self_uses_bounded_state_machine(auth_user):
    no_token = account_interface_services.build_self_mcp_api_payload(
        auth_user.id,
        base_url="https://example.test",
    )
    assert no_token["self_service_state"] == "no_token"

    profile = auth_user.account_profile
    profile.mcp_enabled = False
    profile.save(update_fields=["mcp_enabled", "updated_at"])
    disabled = account_interface_services.build_self_mcp_api_payload(
        auth_user.id,
        base_url="https://example.test",
    )
    assert disabled["self_service_state"] == "disabled"

    profile.mcp_enabled = True
    profile.save(update_fields=["mcp_enabled", "updated_at"])
    UserAccessTokenModel.create_token(
        user=auth_user,
        name="unavailable-token",
        created_by=auth_user,
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )
    unavailable = account_interface_services.build_self_mcp_api_payload(
        auth_user.id,
        base_url="https://example.test",
        routing_available=False,
        catalog_available=True,
    )
    assert unavailable["self_service_state"] == "unavailable"

    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.allow_token_plaintext_view = False
    settings_obj.save(update_fields=["allow_token_plaintext_view", "updated_at"])
    unavailable_without_plaintext = account_interface_services.build_self_mcp_api_payload(
        auth_user.id,
        base_url="https://example.test",
    )
    assert unavailable_without_plaintext["self_service_state"] == "unavailable"
    assert (
        unavailable_without_plaintext["self_service_blocking_reason"] == "token_plaintext_disabled"
    )
    assert unavailable_without_plaintext["access_package"]["token"] == ""


@pytest.mark.django_db
def test_account_mcp_self_reports_encryption_key_mismatch(auth_user):
    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.allow_token_plaintext_view = True
    settings_obj.save(update_fields=["allow_token_plaintext_view", "updated_at"])
    token, _ = UserAccessTokenModel.create_token(
        user=auth_user,
        name="mismatched-token",
        created_by=auth_user,
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )
    token.key_encrypted = "not-decryptable-with-current-key"
    token.save(update_fields=["key_encrypted", "updated_at"])

    payload = account_interface_services.build_self_mcp_api_payload(
        auth_user.id,
        base_url="https://example.test",
    )

    assert payload["self_service_state"] == "unavailable"
    assert payload["self_service_blocking_reason"] == "token_decryption_failed"
    assert payload["access_package"]["token"] == ""


@pytest.mark.django_db
def test_account_mcp_verify_is_read_only_and_bounded(
    authenticated_client,
    auth_user,
    monkeypatch,
):
    _, raw_token = UserAccessTokenModel.create_token(
        user=auth_user,
        name="verify-token",
        created_by=auth_user,
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )
    token_count_before = UserAccessTokenModel.objects.filter(user=auth_user).count()

    monkeypatch.setattr(
        "apps.ai_capability.application.interface_services.inspect_mcp_access_readiness",
        lambda: {
            "routing_available": True,
            "catalog_available": True,
            "capability_count": 12,
        },
    )

    response = authenticated_client.get("/api/ai-capability/mcp-access/verify/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] in {"ready", "unavailable"}
    assert [check["key"] for check in payload["checks"]] == [
        "token",
        "transport",
        "routing",
        "catalog",
    ]
    assert all(check["status"] in {"ready", "unavailable"} for check in payload["checks"])
    assert raw_token not in str(payload)
    assert UserAccessTokenModel.objects.filter(user=auth_user).count() == token_count_before


@pytest.mark.django_db
def test_account_mcp_verify_reports_partial_readiness_without_ai_execution(
    authenticated_client,
    auth_user,
    monkeypatch,
):
    UserAccessTokenModel.create_token(
        user=auth_user,
        name="partial-readiness-token",
        created_by=auth_user,
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )
    monkeypatch.setattr(
        "apps.ai_capability.application.interface_services.inspect_mcp_access_readiness",
        lambda: {
            "routing_available": False,
            "catalog_available": True,
            "capability_count": 12,
        },
    )

    response = authenticated_client.get("/api/ai-capability/mcp-access/verify/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "unavailable"
    assert {item["key"]: item["status"] for item in payload["checks"]} == {
        "token": "ready",
        "transport": "ready",
        "routing": "unavailable",
        "catalog": "ready",
    }


@pytest.mark.django_db
def test_account_mcp_self_create_token_returns_copy_payload(authenticated_client):
    response = authenticated_client.post(
        "/api/account/mcp/tokens/",
        {"token_name": "tui-self", "access_level": "read_write"},
        format="json",
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["success"] is True
    assert payload["token_payload"]["token_name"] == "tui-self"
    assert payload["token_payload"]["access_level"] == "read_write"
    assert payload["created_agent_prompt"]["agent_bootstrap_token_ready"] is True
    assert payload["self_service"]["active_token_count"] == 1


@pytest.mark.django_db
def test_account_admin_mcp_users_contract(admin_authenticated_client, auth_user, admin_user):
    UserAccessTokenModel.create_token(
        user=auth_user,
        name="managed-token",
        created_by=admin_user,
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )

    response = admin_authenticated_client.get("/api/account/admin/mcp/users/?without_token=false")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_users"] >= 1
    row = next(item for item in payload["rows"] if item["user_id"] == auth_user.id)
    assert row["username"] == auth_user.username
    assert row["has_token"] is True
    assert row["token_count"] == 1
    assert row["tokens"][0]["name"] == "managed-token"


@pytest.mark.django_db
def test_account_admin_create_mcp_token_returns_prompt(
    admin_authenticated_client,
    auth_user,
):
    response = admin_authenticated_client.post(
        f"/api/account/admin/mcp/users/{auth_user.id}/tokens/",
        {"token_name": "admin-issued", "access_level": "read_only"},
        format="json",
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["success"] is True
    assert payload["token_payload"]["token_name"] == "admin-issued"
    assert payload["created_agent_prompt"]["agent_bootstrap_token_ready"] is True
    assert payload["user_detail"]["user_id"] == auth_user.id
    assert payload["user_detail"]["active_token_count"] == 1


@pytest.mark.django_db
def test_account_mcp_self_revoke_rejects_nonpositive_token_id(
    authenticated_client,
):
    response = authenticated_client.post("/api/account/mcp/tokens/0/revoke/")

    assert response.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/account/admin/mcp/users/0/", None),
        (
            "post",
            "/api/account/admin/mcp/users/0/tokens/",
            {"token_name": "invalid-target", "access_level": "read_only"},
        ),
        ("post", "/api/account/admin/mcp/users/0/tokens/revoke/", None),
        ("post", "/api/account/admin/mcp/tokens/0/revoke/", None),
        ("post", "/api/account/admin/mcp/users/0/toggle/", None),
    ],
)
def test_account_admin_mcp_mutations_reject_nonpositive_path_ids(
    admin_authenticated_client,
    method,
    path,
    payload,
):
    request_method = getattr(admin_authenticated_client, method)
    response = request_method(path, payload or {}, format="json")

    assert response.status_code == 400


@pytest.mark.django_db
def test_account_user_search_short_query_returns_empty(authenticated_client):
    response = authenticated_client.get("/api/account/users/search/?q=a")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["results"] == []


@pytest.mark.django_db
def test_account_sizing_context_rejects_invalid_portfolio_id(authenticated_client):
    response = authenticated_client.get("/api/account/sizing-context/?portfolio_id=bad")

    assert response.status_code == 400
    assert response.json()["detail"] == "portfolio_id 必须为整数"


@pytest.mark.django_db
def test_account_portfolio_allocation_returns_404_for_missing_portfolio(authenticated_client):
    response = authenticated_client.get("/api/account/portfolios/999999/allocation/")

    assert response.status_code == 404
    payload = response.json()
    assert payload["success"] is False
    assert "Portfolio not found" in payload["error"]


@pytest.mark.django_db
def test_account_portfolio_allocation_category_contract(authenticated_client, auth_user):
    portfolio = PortfolioModel.objects.create(user=auth_user, name="API Portfolio", is_active=True)
    category = AssetCategoryModel.objects.create(
        code="allocation_equity",
        name="权益",
        level=1,
        path="权益",
        is_active=True,
    )
    PositionModel.objects.create(
        portfolio=portfolio,
        asset_code="510300.SH",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=10,
        avg_cost=Decimal("4.0000"),
        current_price=Decimal("4.2000"),
        market_value=Decimal("42.00"),
        unrealized_pnl=Decimal("2.00"),
        unrealized_pnl_pct=5.0,
        category=category,
    )

    response = authenticated_client.get(f"/api/account/portfolios/{portfolio.id}/allocation/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["dimension"] == "category"
    assert payload["data"] == [
        {
            "category_path": "权益",
            "amount": "42.00",
            "percentage": 100.0,
        }
    ]


@pytest.mark.django_db
def test_account_category_admin_writes_materialized_tree_fields(
    admin_authenticated_client,
):
    root_response = admin_authenticated_client.post(
        "/api/account/categories/",
        {"code": "api_root", "name": "基金"},
        format="json",
    )
    assert root_response.status_code == 201
    root = AssetCategoryModel.objects.get(code="api_root")
    assert (root.level, root.path) == (1, "基金")

    child_response = admin_authenticated_client.post(
        "/api/account/categories/",
        {"code": "api_child", "name": "债券基金", "parent": root.id},
        format="json",
    )
    assert child_response.status_code == 201
    child = AssetCategoryModel.objects.get(code="api_child")
    assert (child.level, child.path) == (2, "基金/债券基金")

    rename_response = admin_authenticated_client.patch(
        f"/api/account/categories/{root.id}/",
        {"name": "公募基金"},
        format="json",
    )
    assert rename_response.status_code == 200
    child.refresh_from_db()
    assert child.path == "公募基金/债券基金"

    cycle_response = admin_authenticated_client.patch(
        f"/api/account/categories/{root.id}/",
        {"parent": child.id},
        format="json",
    )
    assert cycle_response.status_code == 400


@pytest.mark.django_db
def test_account_category_roots_contract(authenticated_client):
    root = AssetCategoryModel.objects.create(
        code="fund_root",
        name="基金",
        level=1,
        path="基金",
        is_active=True,
        sort_order=1,
    )
    AssetCategoryModel.objects.create(
        code="bond_fund",
        name="债券基金",
        parent=root,
        level=2,
        path="基金/债券基金",
        is_active=True,
        sort_order=1,
    )

    response = authenticated_client.get("/api/account/categories/roots/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"][0]["code"] == "fund_root"


@pytest.mark.django_db
def test_account_currency_base_contract(authenticated_client):
    CurrencyModel.objects.create(
        code="USD",
        name="美元",
        symbol="$",
        is_base=False,
        is_active=True,
        precision=2,
    )
    CurrencyModel.objects.create(
        code="CNY",
        name="人民币",
        symbol="¥",
        is_base=True,
        is_active=True,
        precision=2,
    )

    response = authenticated_client.get("/api/account/currencies/base/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == "CNY"
    assert payload["is_base"] is True


@pytest.mark.django_db
def test_account_exchange_rate_latest_contract(authenticated_client):
    usd = CurrencyModel.objects.create(
        code="USD",
        name="美元",
        symbol="$",
        is_base=False,
        is_active=True,
        precision=2,
    )
    cny = CurrencyModel.objects.create(
        code="CNY",
        name="人民币",
        symbol="¥",
        is_base=True,
        is_active=True,
        precision=2,
    )
    ExchangeRateModel.objects.create(
        from_currency=usd,
        to_currency=cny,
        rate=Decimal("7.123400"),
        effective_date=date(2026, 4, 1),
    )

    response = authenticated_client.get("/api/account/exchange-rates/latest/usd/cny/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["from_currency_code"] == "USD"
    assert payload["to_currency_code"] == "CNY"
    assert Decimal(str(payload["rate"])) == Decimal("7.123400")
    assert payload["effective_date"] == "2026-04-01"
    assert payload["freshness_status"] == "stale"
    assert payload["staleness_days"] > 1
    assert payload["is_stale"] is True
    assert payload["must_not_use_for_decision"] is True
    assert payload["blocked_reason"] == "exchange_rate_stale"


@pytest.mark.django_db
def test_account_exchange_rate_latest_marks_current_observation_fresh(
    authenticated_client,
):
    usd = CurrencyModel.objects.create(
        code="USD",
        name="美元",
        symbol="$",
        is_base=False,
        is_active=True,
        precision=2,
    )
    cny = CurrencyModel.objects.create(
        code="CNY",
        name="人民币",
        symbol="¥",
        is_base=True,
        is_active=True,
        precision=2,
    )
    ExchangeRateModel.objects.create(
        from_currency=usd,
        to_currency=cny,
        rate=Decimal("7.123400"),
        effective_date=timezone.localdate(),
    )

    response = authenticated_client.get("/api/account/exchange-rates/latest/usd/cny/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["freshness_status"] == "fresh"
    assert payload["staleness_days"] == 0
    assert payload["is_stale"] is False
    assert payload["must_not_use_for_decision"] is False
    assert payload["blocked_reason"] == ""


@pytest.mark.django_db
def test_account_exchange_rate_convert_rejects_stale_implicit_latest_rate(
    authenticated_client,
):
    usd = CurrencyModel.objects.create(
        code="USD",
        name="美元",
        symbol="$",
        is_base=False,
        is_active=True,
        precision=2,
    )
    cny = CurrencyModel.objects.create(
        code="CNY",
        name="人民币",
        symbol="¥",
        is_base=True,
        is_active=True,
        precision=2,
    )
    ExchangeRateModel.objects.create(
        from_currency=usd,
        to_currency=cny,
        rate=Decimal("7.123400"),
        effective_date=date(2026, 4, 1),
    )

    response = authenticated_client.post(
        "/api/account/exchange-rates/convert/",
        {
            "amount": "100.00",
            "from_currency": "USD",
            "to_currency": "CNY",
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["success"] is False
    assert "stale" in response.json()["error"]


@pytest.mark.django_db
def test_account_exchange_rate_convert_rejects_future_implicit_latest_rate(
    authenticated_client,
):
    usd = CurrencyModel.objects.create(
        code="USD",
        name="美元",
        symbol="$",
        is_base=False,
        is_active=True,
        precision=2,
    )
    cny = CurrencyModel.objects.create(
        code="CNY",
        name="人民币",
        symbol="¥",
        is_base=True,
        is_active=True,
        precision=2,
    )
    ExchangeRateModel.objects.create(
        from_currency=usd,
        to_currency=cny,
        rate=Decimal("7.123400"),
        effective_date=timezone.localdate() + timedelta(days=1),
    )

    response = authenticated_client.post(
        "/api/account/exchange-rates/convert/",
        {
            "amount": "100.00",
            "from_currency": "USD",
            "to_currency": "CNY",
        },
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["blocked_reason"] == "exchange_rate_future_dated"
    assert payload["must_not_use_for_decision"] is True


@pytest.mark.django_db
def test_account_exchange_rate_admin_rejects_invalid_currency_pair(
    admin_authenticated_client,
):
    usd = CurrencyModel.objects.create(
        code="USD",
        name="美元",
        symbol="$",
        is_base=True,
        is_active=True,
        precision=2,
    )
    inactive = CurrencyModel.objects.create(
        code="ZZZ",
        name="停用币种",
        symbol="Z",
        is_base=False,
        is_active=False,
        precision=2,
    )

    same_pair = admin_authenticated_client.post(
        "/api/account/exchange-rates/",
        {
            "from_currency": usd.id,
            "to_currency": usd.id,
            "rate": "1.000000",
            "effective_date": "2026-04-01",
        },
        format="json",
    )
    inactive_pair = admin_authenticated_client.post(
        "/api/account/exchange-rates/",
        {
            "from_currency": usd.id,
            "to_currency": inactive.id,
            "rate": "1.000000",
            "effective_date": "2026-04-01",
        },
        format="json",
    )

    assert same_pair.status_code == 400
    assert inactive_pair.status_code == 400
    assert not ExchangeRateModel.objects.exists()


@pytest.mark.django_db
def test_account_exchange_rate_convert_contract(authenticated_client):
    usd = CurrencyModel.objects.create(
        code="USD",
        name="美元",
        symbol="$",
        is_base=False,
        is_active=True,
        precision=2,
    )
    cny = CurrencyModel.objects.create(
        code="CNY",
        name="人民币",
        symbol="¥",
        is_base=True,
        is_active=True,
        precision=2,
    )
    ExchangeRateModel.objects.create(
        from_currency=usd,
        to_currency=cny,
        rate=Decimal("7.123400"),
        effective_date=date(2026, 4, 1),
    )

    response = authenticated_client.post(
        "/api/account/exchange-rates/convert/",
        {
            "amount": "100.00",
            "from_currency": "USD",
            "to_currency": "CNY",
            "date": "2026-04-01",
        },
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert Decimal(str(payload["converted_amount"])) == Decimal("712.340000")
    assert Decimal(str(payload["rate_used"])) == Decimal("7.123400")
    assert payload["rate_date"] == "2026-04-01"


@pytest.mark.django_db
def test_account_exchange_rate_convert_rejects_unregistered_identity_pair(
    authenticated_client,
):
    response = authenticated_client.post(
        "/api/account/exchange-rates/convert/",
        {
            "amount": "100.00",
            "from_currency": "ghost",
            "to_currency": "ghost",
        },
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_account_portfolio_allocation_currency_contract(authenticated_client, auth_user):
    usd = CurrencyModel.objects.create(
        code="USD",
        name="美元",
        symbol="$",
        is_base=False,
        is_active=True,
        precision=2,
    )
    cny = CurrencyModel.objects.create(
        code="CNY",
        name="人民币",
        symbol="¥",
        is_base=True,
        is_active=True,
        precision=2,
    )
    portfolio = PortfolioModel.objects.create(
        user=auth_user,
        name="Currency Allocation Portfolio",
        is_active=True,
        base_currency=cny,
    )
    PositionModel.objects.create(
        portfolio=portfolio,
        asset_code="SPY",
        asset_class="equity",
        region="US",
        cross_border="cross_border",
        shares=10,
        avg_cost=Decimal("50.0000"),
        current_price=Decimal("52.0000"),
        market_value=Decimal("520.00"),
        unrealized_pnl=Decimal("20.00"),
        unrealized_pnl_pct=4.0,
        currency=usd,
    )
    ExchangeRateModel.objects.create(
        from_currency=usd,
        to_currency=cny,
        rate=Decimal("7.200000"),
        effective_date=timezone.localdate(),
    )

    response = authenticated_client.get(
        f"/api/account/portfolios/{portfolio.id}/allocation/?dimension=currency"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["dimension"] == "currency"
    assert payload["base_currency"] == "CNY"
    assert payload["data"][0]["currency_code"] == "USD"


@pytest.mark.django_db
def test_account_currency_allocation_rejects_missing_fx_rate(
    authenticated_client,
    auth_user,
):
    usd = CurrencyModel.objects.create(
        code="USD",
        name="美元",
        symbol="$",
        is_base=False,
        is_active=True,
        precision=2,
    )
    cny = CurrencyModel.objects.create(
        code="CNY",
        name="人民币",
        symbol="¥",
        is_base=True,
        is_active=True,
        precision=2,
    )
    portfolio = PortfolioModel.objects.create(
        user=auth_user,
        name="Missing FX Portfolio",
        is_active=True,
        base_currency=cny,
    )
    PositionModel.objects.create(
        portfolio=portfolio,
        asset_code="SPY",
        asset_class="equity",
        region="US",
        cross_border="cross_border",
        shares=1,
        avg_cost=Decimal("500.0000"),
        current_price=Decimal("520.0000"),
        market_value=Decimal("520.00"),
        unrealized_pnl=Decimal("20.00"),
        unrealized_pnl_pct=4.0,
        currency=usd,
    )

    response = authenticated_client.get(
        f"/api/account/portfolios/{portfolio.id}/allocation/?dimension=currency"
    )

    assert response.status_code == 400
    assert "No exchange rate found" in response.json()["error"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    ["?dimension=sector", "?dimension=category&unexpected=1"],
)
def test_account_allocation_rejects_ambiguous_dimension(
    authenticated_client,
    auth_user,
    query,
):
    portfolio = PortfolioModel.objects.create(
        user=auth_user,
        name="Strict Allocation Portfolio",
        is_active=True,
    )

    response = authenticated_client.get(
        f"/api/account/portfolios/{portfolio.id}/allocation/{query}"
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_account_observer_positions_allows_observer_without_as_observer_query_param(
    authenticated_client, auth_user
):
    owner = get_user_model().objects.create_user(
        username="observer_owner",
        password="testpass123",
        email="owner@example.com",
    )
    AccountProfileModel.objects.update_or_create(
        user=owner,
        defaults={
            "display_name": "Observer Owner",
            "initial_capital": Decimal("500000.00"),
            "approval_status": "approved",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
        },
    )
    portfolio = PortfolioModel.objects.create(user=owner, name="Observer Portfolio", is_active=True)
    PositionModel.objects.create(
        portfolio=portfolio,
        asset_code="000001.SZ",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=100,
        avg_cost=Decimal("10.0000"),
        current_price=Decimal("12.0000"),
        market_value=Decimal("1200.00"),
        unrealized_pnl=Decimal("200.00"),
        unrealized_pnl_pct=20.0,
    )
    grant = PortfolioObserverGrantModel.objects.create(
        owner_user_id=owner,
        observer_user_id=auth_user,
        expires_at=timezone.now() + timedelta(days=7),
    )

    response = authenticated_client.get(f"/api/account/observer-grants/{grant.id}/positions/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["positions"][0]["asset_code"] == "000001.SZ"
    assert payload["data"]["positions"][0]["asset_name"] == "000001.SZ"


@pytest.mark.django_db
def test_account_observer_detail_allows_observer_without_as_observer_query_param(
    authenticated_client, auth_user
):
    owner = get_user_model().objects.create_user(
        username="detail_owner",
        password="testpass123",
        email="detail-owner@example.com",
    )
    grant = PortfolioObserverGrantModel.objects.create(
        owner_user_id=owner,
        observer_user_id=auth_user,
        expires_at=timezone.now() + timedelta(days=7),
    )

    response = authenticated_client.get(f"/api/account/observer-grants/{grant.id}/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(grant.id)
    assert payload["observer_username"] == auth_user.username


@pytest.mark.django_db
def test_account_observer_positions_forbid_owner_view(authenticated_client, auth_user):
    observer = get_user_model().objects.create_user(
        username="positions_observer",
        password="testpass123",
        email="positions-observer@example.com",
    )
    grant = PortfolioObserverGrantModel.objects.create(
        owner_user_id=auth_user,
        observer_user_id=observer,
        expires_at=timezone.now() + timedelta(days=7),
    )

    response = authenticated_client.get(f"/api/account/observer-grants/{grant.id}/positions/")

    assert response.status_code == 403
    payload = response.json()
    assert payload["success"] is False
    assert "无权查看" in payload["error"]


@pytest.mark.django_db
def test_account_observer_detail_rejects_invalid_uuid(authenticated_client):
    response = authenticated_client.get("/api/account/observer-grants/not-a-uuid/")

    assert response.status_code == 400
    assert response.json()["error"] == "授权 ID 格式无效"


@pytest.mark.django_db
def test_account_observer_positions_reject_invalid_uuid(authenticated_client):
    response = authenticated_client.get("/api/account/observer-grants/not-a-uuid/positions/")

    assert response.status_code == 400
    assert response.json()["error"] == "授权 ID 格式无效"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    [
        {"as_observer": "2"},
        {"status": "unknown"},
        {"owner_id": "1"},
    ],
)
def test_account_observer_list_rejects_ambiguous_scope_query(
    authenticated_client,
    query,
):
    response = authenticated_client.get("/api/account/observer-grants/", query)

    assert response.status_code == 400


@pytest.mark.django_db
def test_account_observer_detail_forbids_unrelated_user(
    authenticated_client,
):
    owner = get_user_model().objects.create_user(
        username="unrelated-grant-owner",
        password="testpass123",
    )
    observer = get_user_model().objects.create_user(
        username="unrelated-grant-observer",
        password="testpass123",
    )
    grant = PortfolioObserverGrantModel.objects.create(
        owner_user_id=owner,
        observer_user_id=observer,
        expires_at=timezone.now() + timedelta(days=7),
    )

    response = authenticated_client.get(f"/api/account/observer-grants/{grant.id}/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_account_transaction_create_returns_403_for_foreign_position(authenticated_client):
    other_user = get_user_model().objects.create_user(
        username="foreign_position_owner",
        password="testpass123",
        email="foreign-position@example.com",
    )
    portfolio = PortfolioModel.objects.create(
        user=other_user, name="Foreign Portfolio", is_active=True
    )
    position = PositionModel.objects.create(
        portfolio=portfolio,
        asset_code="600000.SH",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=200,
        avg_cost=Decimal("9.0000"),
        current_price=Decimal("9.5000"),
        market_value=Decimal("1900.00"),
        unrealized_pnl=Decimal("100.00"),
        unrealized_pnl_pct=5.0,
    )

    response = authenticated_client.post(
        "/api/account/transactions/",
        {
            "portfolio": portfolio.id,
            "position": position.id,
            "action": "buy",
            "asset_code": "600000.SH",
            "shares": 10,
            "price": "9.5000",
            "commission": "1.00",
            "notes": "edge case",
            "traded_at": timezone.now().isoformat(),
        },
        format="json",
    )

    assert response.status_code == 403
    payload = response.json()
    message = str(payload.get("detail") or payload.get("error") or payload)
    assert "无权为此持仓创建交易记录" in message


@pytest.mark.django_db
def test_account_capital_flow_create_returns_404_for_foreign_portfolio(authenticated_client):
    other_user = get_user_model().objects.create_user(
        username="foreign_portfolio_owner",
        password="testpass123",
        email="foreign-portfolio@example.com",
    )
    portfolio = PortfolioModel.objects.create(
        user=other_user, name="Foreign Capital Portfolio", is_active=True
    )

    response = authenticated_client.post(
        "/api/account/capital-flows/",
        {
            "portfolio": portfolio.id,
            "flow_type": "deposit",
            "amount": "1000.00",
            "flow_date": "2026-04-02",
            "notes": "foreign portfolio",
        },
        format="json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_account_transaction_create_returns_403_for_foreign_portfolio_without_position(
    authenticated_client,
):
    """省略可选持仓时也必须验证组合归属。"""
    other_user = get_user_model().objects.create_user(
        username="foreign_transaction_portfolio_owner",
        password="testpass123",
    )
    portfolio = PortfolioModel.objects.create(
        user=other_user,
        name="Foreign Transaction Portfolio",
    )

    response = authenticated_client.post(
        "/api/account/transactions/",
        {
            "portfolio": portfolio.id,
            "action": "buy",
            "asset_code": "600000.SH",
            "shares": 10,
            "price": "9.5000",
            "commission": "1.00",
            "traded_at": timezone.now().isoformat(),
        },
        format="json",
    )

    assert response.status_code == 403
    assert not TransactionModel.objects.filter(portfolio=portfolio).exists()


@pytest.mark.django_db
def test_account_transaction_create_rejects_position_asset_mismatch(
    authenticated_client,
    auth_user,
):
    portfolio = PortfolioModel.objects.create(user=auth_user, name="Owned Portfolio")
    position = PositionModel.objects.create(
        portfolio=portfolio,
        asset_code="600000.SH",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=200,
        avg_cost=Decimal("9.0000"),
        current_price=Decimal("9.5000"),
        market_value=Decimal("1900.00"),
        unrealized_pnl=Decimal("100.00"),
        unrealized_pnl_pct=5.0,
    )

    response = authenticated_client.post(
        "/api/account/transactions/",
        {
            "portfolio": portfolio.id,
            "position": position.id,
            "action": "buy",
            "asset_code": "000001.SZ",
            "shares": 10,
            "price": "9.5000",
            "commission": "1.00",
            "traded_at": timezone.now().isoformat(),
        },
        format="json",
    )

    assert response.status_code == 400
    assert not TransactionModel.objects.filter(portfolio=portfolio).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("shares", "NaN"),
        ("commission", "-0.01"),
        ("traded_at", (timezone.now() + timedelta(days=1)).isoformat()),
    ],
)
def test_account_transaction_create_rejects_invalid_financial_values(
    authenticated_client,
    auth_user,
    field,
    value,
):
    portfolio = PortfolioModel.objects.create(user=auth_user, name=f"Invalid {field}")
    payload = {
        "portfolio": portfolio.id,
        "action": "buy",
        "asset_code": "600000.SH",
        "shares": 10,
        "price": "9.5000",
        "commission": "1.00",
        "traded_at": timezone.now().isoformat(),
    }
    payload[field] = value

    response = authenticated_client.post(
        "/api/account/transactions/",
        payload,
        format="json",
    )

    assert response.status_code == 400
    assert not TransactionModel.objects.filter(portfolio=portfolio).exists()


@pytest.mark.django_db
def test_account_transaction_records_are_append_only(authenticated_client, auth_user):
    portfolio = PortfolioModel.objects.create(user=auth_user, name="Append Only")
    transaction = TransactionModel.objects.create(
        portfolio=portfolio,
        action="buy",
        asset_code="600000.SH",
        shares=10,
        price=Decimal("9.5000"),
        notional=Decimal("95.00"),
        traded_at=timezone.now(),
    )

    patch_response = authenticated_client.patch(
        f"/api/account/transactions/{transaction.id}/",
        {"notes": "rewritten"},
        format="json",
    )
    delete_response = authenticated_client.delete(f"/api/account/transactions/{transaction.id}/")

    assert patch_response.status_code == 405
    assert delete_response.status_code == 405
    transaction.refresh_from_db()
    assert transaction.notes == ""


@pytest.mark.django_db
def test_account_transaction_create_uses_decimal_notional(
    authenticated_client,
    auth_user,
):
    portfolio = PortfolioModel.objects.create(user=auth_user, name="Decimal Notional")

    response = authenticated_client.post(
        "/api/account/transactions/",
        {
            "portfolio": portfolio.id,
            "action": "buy",
            "asset_code": "600000.SH",
            "shares": 0.1,
            "price": "0.1000",
            "commission": "0.00",
            "traded_at": timezone.now().isoformat(),
        },
        format="json",
    )

    assert response.status_code == 201
    transaction = TransactionModel.objects.get(portfolio=portfolio)
    assert transaction.notional == Decimal("0.01")


@pytest.mark.django_db
def test_account_capital_flow_update_is_not_allowed(authenticated_client, auth_user):
    portfolio = PortfolioModel.objects.create(user=auth_user, name="Flow Ledger")
    flow = CapitalFlowModel.objects.create(
        user=auth_user,
        portfolio=portfolio,
        flow_type="deposit",
        amount=Decimal("1000.00"),
        flow_date=date(2026, 4, 2),
    )

    response = authenticated_client.patch(
        f"/api/account/capital-flows/{flow.id}/",
        {"amount": "1.00"},
        format="json",
    )

    assert response.status_code == 405
    flow.refresh_from_db()
    assert flow.amount == Decimal("1000.00")


@pytest.mark.django_db
def test_account_capital_flow_create_and_delete_remain_supported(
    authenticated_client,
    auth_user,
):
    portfolio = PortfolioModel.objects.create(user=auth_user, name="Flow Lifecycle")

    create_response = authenticated_client.post(
        "/api/account/capital-flows/",
        {
            "portfolio": portfolio.id,
            "flow_type": "deposit",
            "amount": "1000.00",
            "flow_date": "2026-04-02",
            "notes": "initial capital",
        },
        format="json",
    )

    assert create_response.status_code == 201
    flow = CapitalFlowModel.objects.get(portfolio=portfolio)
    assert flow.user == auth_user
    delete_response = authenticated_client.delete(f"/api/account/capital-flows/{flow.id}/")
    assert delete_response.status_code == 204
    assert not CapitalFlowModel.objects.filter(id=flow.id).exists()
