from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from core.middleware.security import SelectiveSSLRedirectSecurityMiddleware


def _middleware() -> SelectiveSSLRedirectSecurityMiddleware:
    return SelectiveSSLRedirectSecurityMiddleware(lambda request: HttpResponse("ok"))


@override_settings(
    SECURE_SSL_REDIRECT=True,
    SECURE_SSL_REDIRECT_EXEMPT_HOSTS=("127.0.0.1", "localhost", "web"),
)
def test_internal_service_host_skips_https_redirect():
    request = RequestFactory().get("/api/health/", HTTP_HOST="web:8000")

    response = _middleware().process_request(request)

    assert response is None


@override_settings(
    SECURE_SSL_REDIRECT=True,
    SECURE_SSL_REDIRECT_EXEMPT_HOSTS=("127.0.0.1", "localhost", "web"),
)
def test_public_host_still_redirects_to_https():
    request = RequestFactory().get("/api/health/", HTTP_HOST="demo.agomtrade.pro")

    response = _middleware().process_request(request)

    assert response is not None
    assert response.status_code == 301
    assert response["Location"] == "https://demo.agomtrade.pro/api/health/"
