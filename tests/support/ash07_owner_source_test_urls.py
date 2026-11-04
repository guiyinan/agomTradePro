"""Minimal authenticated API surface for the isolated ASH07 source smoke."""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token
from django.urls import include, path
from django.views.decorators.csrf import ensure_csrf_cookie


@ensure_csrf_cookie
def csrf_bootstrap(request: HttpRequest) -> JsonResponse:
    """Issue a Django-managed CSRF cookie and its matching token to test clients."""

    return JsonResponse({"csrf_token": get_token(request)})


urlpatterns = [
    path("csrf/bootstrap/", csrf_bootstrap, name="test-csrf-bootstrap"),
    path(
        "api/account/",
        include(
            ("apps.account.interface.api_urls", "account_api"),
            namespace="api_account",
        ),
    ),
    path(
        "api/simulated-trading/",
        include(
            ("apps.simulated_trading.interface.api_urls", "simulated_trading_api"),
            namespace="api_simulated_trading",
        ),
    ),
    path(
        "api/data-center/",
        include(
            ("apps.data_center.interface.api_urls", "api_data_center"),
            namespace="api_data_center",
        ),
    ),
]
