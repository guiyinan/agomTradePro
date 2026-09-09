"""Resolve one public HTTP target and pin its address for a requests session.

The caller owns the session and must mount the returned adapter only for the
prepared target.  The URL is rewritten to the one validated address while the
original hostname is retained in the ``Host`` header and, for HTTPS, in TLS
SNI and certificate hostname validation.  Proxy hostnames are deliberately
left to the trusted proxy configuration and are never resolved here.
"""

from __future__ import annotations

import ipaddress
import math
import socket
import threading
import time
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter
from requests.models import PreparedRequest

from apps.data_center.domain.egress_routing import EgressRoutingError

_DNS_WORKERS = 4
_MIN_DNS_TIMEOUT_SECONDS = 0.01
_MAX_DNS_TIMEOUT_SECONDS = 5.0
_MAX_TARGET_URL_LENGTH = 2048
_DNS_EXECUTOR = ThreadPoolExecutor(max_workers=_DNS_WORKERS, thread_name_prefix="egress-dns")
_DNS_SLOTS = threading.BoundedSemaphore(_DNS_WORKERS)


class PublicTargetError(EgressRoutingError):
    """Raised when a target cannot be safely resolved and pinned."""


@dataclass(frozen=True, slots=True)
class ResolvedPublicTarget:
    """One validated public target with exactly one selected address."""

    url: str
    original_url: str
    scheme: str
    hostname: str
    port: int
    host_header: str
    resolved_ip: str


class PinnedAddressAdapter(HTTPAdapter):
    """Use one already-resolved address while preserving HTTPS identity."""

    def __init__(
        self,
        *,
        scheme: str,
        hostname: str,
        pinned_ip: str,
        port: int,
    ) -> None:
        self._scheme = scheme
        self._hostname = hostname
        self._pinned_ip = pinned_ip
        self._port = port
        super().__init__(pool_connections=1, pool_maxsize=1, pool_block=True, max_retries=0)

    def init_poolmanager(
        self,
        connections: int,
        maxsize: int,
        block: bool = False,
        **pool_kwargs: Any,
    ) -> None:
        """Create a session-scoped pool with the original HTTPS identity."""

        if self._scheme == "https":
            pool_kwargs["server_hostname"] = self._hostname
            pool_kwargs["assert_hostname"] = self._hostname
        super().init_poolmanager(connections, maxsize, block, **pool_kwargs)

    def proxy_manager_for(self, proxy: str, **proxy_kwargs: Any) -> Any:
        """Keep trusted proxy routing while pinning the origin TLS identity."""

        if self._scheme == "https":
            proxy_kwargs["server_hostname"] = self._hostname
            proxy_kwargs["assert_hostname"] = self._hostname
        return super().proxy_manager_for(proxy, **proxy_kwargs)

    def send(
        self,
        request: PreparedRequest,
        stream: bool = False,
        timeout: float | tuple[float, float] | tuple[float, None] | None = None,
        verify: bool | str = True,
        cert: bytes | str | tuple[bytes | str, bytes | str] | None = None,
        proxies: Mapping[str, str] | None = None,
    ) -> requests.Response:
        """Reject reuse for another address and force the original Host header."""

        try:
            parsed = urlsplit(request.url)
            request_host = parsed.hostname
            request_port = (
                parsed.port
                if parsed.port is not None
                else (443 if parsed.scheme == "https" else 80)
            )
        except ValueError as error:
            raise requests.exceptions.InvalidURL("prepared target URL is invalid") from error
        if (
            parsed.scheme != self._scheme
            or request_host != self._pinned_ip
            or request_port != self._port
            or "@" in parsed.netloc
            or parsed.fragment
        ):
            raise requests.exceptions.InvalidURL("request URL does not match pinned target")
        request.headers["Host"] = _format_host_header(self._hostname, self._port, self._scheme)
        return super().send(
            request,
            stream=stream,
            timeout=timeout,
            verify=verify,
            cert=cert,
            proxies=proxies,
        )


@dataclass(frozen=True, slots=True)
class PreparedPublicTarget:
    """A target URL and adapter that must be used together in one session."""

    url: str
    host_header: str
    adapter: PinnedAddressAdapter
    scheme: str
    hostname: str
    port: int
    resolved_ip: str


def resolve_public_target(url: str, *, dns_timeout_seconds: float = 1.0) -> ResolvedPublicTarget:
    """Resolve a public target once and return one validated address."""

    parsed, hostname, port, host_header = _parse_target_url(url)
    timeout = _validated_dns_timeout(dns_timeout_seconds)
    literal = _parse_ip_literal(hostname)
    if literal is None:
        addresses = _resolve_hostname(hostname, port, timeout)
    else:
        addresses = (literal,)
    resolved_ip = _select_public_address(addresses)
    rewritten_url = _rewrite_url(parsed, resolved_ip, port)
    return ResolvedPublicTarget(
        url=rewritten_url,
        original_url=parsed.geturl(),
        scheme=parsed.scheme,
        hostname=hostname,
        port=port,
        host_header=host_header,
        resolved_ip=resolved_ip,
    )


def prepare_public_target(url: str, *, dns_timeout_seconds: float = 1.0) -> PreparedPublicTarget:
    """Prepare one address-pinned target and its session-scoped adapter."""

    resolved = resolve_public_target(url, dns_timeout_seconds=dns_timeout_seconds)
    return PreparedPublicTarget(
        url=resolved.url,
        host_header=resolved.host_header,
        adapter=PinnedAddressAdapter(
            scheme=resolved.scheme,
            hostname=resolved.hostname,
            pinned_ip=resolved.resolved_ip,
            port=resolved.port,
        ),
        scheme=resolved.scheme,
        hostname=resolved.hostname,
        port=resolved.port,
        resolved_ip=resolved.resolved_ip,
    )


def _validated_dns_timeout(value: float) -> float:
    """Keep DNS waiting bounded even when called outside an HTTP serializer."""

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not _MIN_DNS_TIMEOUT_SECONDS <= value <= _MAX_DNS_TIMEOUT_SECONDS
    ):
        raise PublicTargetError(
            "DNS timeout is outside the supported range",
            code="EGRESS_INVALID_CONFIGURATION",
        )
    return float(value)


def _parse_target_url(url: str) -> tuple[SplitResult, str, int, str]:
    """Validate a target URL and return normalized routing fields."""

    if not isinstance(url, str):
        raise PublicTargetError("target URL must be a string", code="EGRESS_INVALID_URL")
    normalized_url = url.strip()
    if (
        not normalized_url
        or len(normalized_url) > _MAX_TARGET_URL_LENGTH
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized_url)
    ):
        raise PublicTargetError("target URL is invalid", code="EGRESS_INVALID_URL")
    try:
        parsed = urlsplit(normalized_url)
        hostname = parsed.hostname
        explicit_port = parsed.port
    except ValueError as error:
        raise PublicTargetError("target URL is invalid", code="EGRESS_INVALID_URL") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or "@" in parsed.netloc
        or "#" in normalized_url
    ):
        raise PublicTargetError("target URL is not allowed", code="EGRESS_TARGET_NOT_ALLOWED")
    normalized_hostname = hostname.strip().lower().rstrip(".")
    if not normalized_hostname or "*" in normalized_hostname or len(normalized_hostname) > 253:
        raise PublicTargetError("target host is invalid", code="EGRESS_TARGET_NOT_ALLOWED")
    port = explicit_port if explicit_port is not None else (443 if parsed.scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise PublicTargetError("target port is invalid", code="EGRESS_TARGET_NOT_ALLOWED")
    return (
        parsed,
        normalized_hostname,
        port,
        _format_host_header(normalized_hostname, port, parsed.scheme, explicit_port is not None),
    )


def _format_host_header(hostname: str, port: int, scheme: str, explicit_port: bool = True) -> str:
    """Format the original authority for the HTTP Host header."""

    host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if scheme == "https" else 80
    return f"{host}:{port}" if explicit_port and port != default_port else host


def _parse_ip_literal(hostname: str) -> str | None:
    """Return a canonical IP literal or ``None`` for a DNS hostname."""

    try:
        return ipaddress.ip_address(hostname).compressed
    except ValueError:
        return None


def _resolve_hostname(hostname: str, port: int, timeout: float) -> tuple[str, ...]:
    """Resolve DNS with bounded worker count and a request-visible deadline."""

    started = time.monotonic()
    acquired = _DNS_SLOTS.acquire(timeout=timeout)
    if not acquired:
        raise PublicTargetError(
            "target DNS concurrency is exhausted",
            code="EGRESS_DNS_CONCURRENCY_LIMIT",
        )
    try:
        future: Future[tuple[str, ...]] = _DNS_EXECUTOR.submit(_lookup_addresses, hostname, port)
    except RuntimeError as error:
        _DNS_SLOTS.release()
        raise PublicTargetError(
            "target DNS resolver is unavailable", code="EGRESS_DNS_ERROR"
        ) from error
    defer_release = False
    try:
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise FutureTimeoutError()
        return future.result(timeout=remaining)
    except FutureTimeoutError as error:
        defer_release = True
        future.add_done_callback(_release_dns_slot)
        future.cancel()
        raise PublicTargetError("target DNS lookup timed out", code="EGRESS_DNS_TIMEOUT") from error
    except (IndexError, OSError, socket.gaierror, TypeError, ValueError) as error:
        raise PublicTargetError("target DNS lookup failed", code="EGRESS_DNS_ERROR") from error
    finally:
        if not defer_release:
            _DNS_SLOTS.release()


def _release_dns_slot(_future: Future[tuple[str, ...]]) -> None:
    """Release a DNS slot after a timed-out worker eventually exits."""

    _DNS_SLOTS.release()


def _lookup_addresses(hostname: str, port: int) -> tuple[str, ...]:
    """Read stream addresses from the system resolver."""

    raw_results = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    addresses: list[str] = []
    seen: set[str] = set()
    for result in raw_results:
        sockaddr = result[4]
        if not sockaddr or not isinstance(sockaddr[0], str):
            continue
        try:
            address = ipaddress.ip_address(sockaddr[0]).compressed
        except ValueError as error:
            raise PublicTargetError(
                "target DNS answer is invalid", code="EGRESS_DNS_ERROR"
            ) from error
        if address not in seen:
            seen.add(address)
            addresses.append(address)
    return tuple(addresses)


def _select_public_address(addresses: tuple[str, ...]) -> str:
    """Reject mixed/private DNS answers and select the first public address."""

    if not addresses:
        raise PublicTargetError("target DNS answer is empty", code="EGRESS_DNS_ERROR")
    parsed_addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as error:
            raise PublicTargetError("target address is invalid", code="EGRESS_DNS_ERROR") from error
        parsed_addresses.append(parsed)
    if any(not address.is_global for address in parsed_addresses):
        raise PublicTargetError(
            "target resolves to a private address",
            code="EGRESS_PRIVATE_TARGET",
        )
    selected = next(
        (address for address in parsed_addresses if isinstance(address, ipaddress.IPv4Address)),
        parsed_addresses[0],
    )
    return selected.compressed


def _rewrite_url(parsed: SplitResult, resolved_ip: str, port: int) -> str:
    """Replace only the network address and retain path/query semantics."""

    host = f"[{resolved_ip}]" if ":" in resolved_ip else resolved_ip
    explicit_port = parsed.port is not None
    default_port = 443 if parsed.scheme == "https" else 80
    netloc = f"{host}:{port}" if explicit_port or port != default_port else host
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))


__all__ = [
    "PinnedAddressAdapter",
    "PreparedPublicTarget",
    "PublicTargetError",
    "ResolvedPublicTarget",
    "prepare_public_target",
    "resolve_public_target",
]
