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


@override_settings(
    SECURE_SSL_REDIRECT=True,
    SECURE_SSL_REDIRECT_EXEMPT_HOSTS=("web",),
)
def test_public_source_cannot_bypass_redirect_with_internal_host_header():
    request = RequestFactory().get(
        "/api/health/",
        HTTP_HOST="web:8000",
        REMOTE_ADDR="203.0.113.10",
    )

    response = _middleware().process_request(request)

    assert response is not None
    assert response.status_code == 301


@override_settings(
    SECURE_SSL_REDIRECT=True,
    SECURE_SSL_REDIRECT_EXEMPT_HOSTS=("web",),
)
def test_proxied_external_request_cannot_use_internal_host_exemption():
    request = RequestFactory().get(
        "/api/health/",
        HTTP_HOST="web:8000",
        REMOTE_ADDR="172.18.0.2",
        HTTP_X_FORWARDED_FOR="198.51.100.20",
    )

    response = _middleware().process_request(request)

    assert response is not None
    assert response.status_code == 301


@override_settings(
    SECURE_SSL_REDIRECT=True,
    SECURE_SSL_REDIRECT_EXEMPT_HOSTS=("web",),
    SECURE_SSL_REDIRECT_EXEMPT_NETWORKS=("10.42.0.0/16",),
)
def test_internal_host_requires_source_inside_configured_network():
    allowed_request = RequestFactory().get(
        "/api/health/",
        HTTP_HOST="web:8000",
        REMOTE_ADDR="10.42.1.5",
    )
    denied_request = RequestFactory().get(
        "/api/health/",
        HTTP_HOST="web:8000",
        REMOTE_ADDR="172.18.0.2",
    )
    middleware = _middleware()

    assert middleware.process_request(allowed_request) is None
    assert middleware.process_request(denied_request) is not None


@override_settings(
    SECURE_SSL_REDIRECT=True,
    SECURE_SSL_REDIRECT_EXEMPT_HOSTS=("web",),
)
def test_disallowed_host_never_receives_redirect_exemption():
    request = RequestFactory().get(
        "/api/health/",
        HTTP_HOST="web.attacker.example",
        REMOTE_ADDR="127.0.0.1",
    )

    response = _middleware().process_request(request)

    assert response is not None
    assert response.status_code == 301
