import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.cache import cache
from django.test import RequestFactory, override_settings
from rest_framework.test import APIClient


@pytest.mark.django_db
class TestApiAuthHardening:
    def test_alpha_api_requires_authentication(self):
        client = APIClient()
        response = client.get("/api/alpha/health/")
        assert response.status_code in [401, 403]

    def test_factor_api_requires_authentication(self):
        client = APIClient()
        response = client.get("/api/factor/")
        assert response.status_code in [401, 403]

    def test_rotation_api_requires_authentication(self):
        client = APIClient()
        response = client.get("/api/rotation/recommendation/?strategy=momentum")
        assert response.status_code in [401, 403]

    def test_authenticated_alpha_factor_rotation_not_rejected_by_auth(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(username="security_guard", password="StrongPass123!")
        client = APIClient()
        client.force_authenticate(user=user)

        alpha_resp = client.get("/api/alpha/health/")
        factor_resp = client.get("/api/factor/")
        rotation_resp = client.get("/api/rotation/recommendation/?strategy=momentum")

        assert alpha_resp.status_code not in [401, 403]
        assert factor_resp.status_code not in [401, 403]
        assert rotation_resp.status_code not in [401, 403]


@pytest.mark.django_db
class TestLoginLockoutGuardrail:
    @override_settings(LOGIN_LOCKOUT_MAX_ATTEMPTS=2, LOGIN_LOCKOUT_WINDOW_SECONDS=60)
    def test_lockout_blocks_correct_password_after_repeated_failures(self):
        cache.clear()
        user_model = get_user_model()
        user_model.objects.create_user(username="locked_user", password="CorrectPass123!")
        request_factory = RequestFactory()

        req = request_factory.post("/account/login/", REMOTE_ADDR="127.0.0.1")
        assert authenticate(request=req, username="locked_user", password="bad-pass-1") is None
        assert authenticate(request=req, username="locked_user", password="bad-pass-2") is None

        # After reaching threshold, even correct password should be blocked during lock window.
        assert authenticate(request=req, username="locked_user", password="CorrectPass123!") is None
