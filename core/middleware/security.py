"""Security middleware helpers for production HTTP/HTTPS posture."""

from urllib.parse import urlsplit

from django.conf import settings
from django.middleware.security import SecurityMiddleware


class SelectiveSSLRedirectSecurityMiddleware(SecurityMiddleware):
    """Keep HTTPS redirect for public traffic, but allow trusted internal hosts over HTTP."""

    def __init__(self, get_response):
        super().__init__(get_response)
        exempt_hosts = getattr(settings, "SECURE_SSL_REDIRECT_EXEMPT_HOSTS", ())
        self._redirect_exempt_hosts = {
            self._normalize_host(host)
            for host in exempt_hosts
            if self._normalize_host(host)
        }

    def process_request(self, request):
        if self.redirect and self._is_redirect_exempt_host(request):
            return None
        return super().process_request(request)

    def _is_redirect_exempt_host(self, request) -> bool:
        host = self._normalize_host(
            request.META.get("HTTP_HOST") or request.META.get("SERVER_NAME") or ""
        )
        return bool(host and host in self._redirect_exempt_hosts)

    @staticmethod
    def _normalize_host(value: str) -> str:
        raw_value = (value or "").strip()
        if not raw_value:
            return ""
        if "://" not in raw_value:
            raw_value = f"//{raw_value}"
        parsed = urlsplit(raw_value)
        return (parsed.hostname or "").strip().lower()
