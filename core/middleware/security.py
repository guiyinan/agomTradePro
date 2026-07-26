"""Security middleware helpers for production HTTP/HTTPS posture."""

import logging
from collections.abc import Callable, Iterable
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.http import HttpRequest, HttpResponsePermanentRedirect
from django.http.response import HttpResponseBase
from django.middleware.security import SecurityMiddleware

logger = logging.getLogger(__name__)

_DEFAULT_EXEMPT_NETWORKS = (
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "::1/128",
    "fc00::/7",
)


class SelectiveSSLRedirectSecurityMiddleware(SecurityMiddleware):
    """Keep HTTPS redirect for public traffic, but allow trusted internal hosts over HTTP."""

    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponseBase],
    ) -> None:
        super().__init__(get_response)
        self._redirect_exempt_hosts = self._normalize_hosts(
            getattr(settings, "SECURE_SSL_REDIRECT_EXEMPT_HOSTS", ()),
        )
        self._redirect_exempt_networks = self._normalize_networks(
            getattr(
                settings,
                "SECURE_SSL_REDIRECT_EXEMPT_NETWORKS",
                _DEFAULT_EXEMPT_NETWORKS,
            ),
        )

    def process_request(
        self,
        request: HttpRequest,
    ) -> HttpResponsePermanentRedirect | None:
        if self.redirect and self._is_redirect_exempt_host(request):
            return None
        return super().process_request(request)

    def _is_redirect_exempt_host(self, request: HttpRequest) -> bool:
        try:
            host = self._normalize_host(request.get_host())
        except DisallowedHost:
            return False
        if not host or host not in self._redirect_exempt_hosts:
            return False

        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if isinstance(forwarded_for, str) and forwarded_for.strip():
            return False

        remote_addr = request.META.get("REMOTE_ADDR")
        if not isinstance(remote_addr, str) or not remote_addr.strip():
            return False
        try:
            source_ip = ip_address(remote_addr.strip())
        except ValueError:
            return False
        return any(source_ip in network for network in self._redirect_exempt_networks)

    @staticmethod
    def _normalize_host(value: object) -> str:
        if not isinstance(value, str):
            return ""
        raw_value = value.strip()
        if not raw_value:
            return ""
        if "://" not in raw_value:
            raw_value = f"//{raw_value}"
        parsed = urlsplit(raw_value)
        return (parsed.hostname or "").strip().lower()

    @classmethod
    def _normalize_hosts(cls, values: object) -> frozenset[str]:
        if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
            return frozenset()
        normalized_hosts = {
            normalized for value in values if (normalized := cls._normalize_host(value))
        }
        return frozenset(normalized_hosts)

    @staticmethod
    def _normalize_networks(
        values: object,
    ) -> tuple[IPv4Network | IPv6Network, ...]:
        if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
            return ()
        networks: list[IPv4Network | IPv6Network] = []
        for value in values:
            if not isinstance(value, str):
                logger.warning(
                    "Ignoring invalid SSL redirect exemption network; value_type=%s",
                    type(value).__name__,
                )
                continue
            try:
                networks.append(ip_network(value.strip(), strict=False))
            except ValueError:
                logger.warning("Ignoring invalid SSL redirect exemption network")
        return tuple(networks)
