"""Bounded DNS resolution and address-pinned requests transport contracts."""

import socket
import time
from types import SimpleNamespace

import pytest
import requests

from apps.data_center.infrastructure import egress_target
from apps.data_center.infrastructure.egress_target import (
    PinnedAddressAdapter,
    PublicTargetError,
    prepare_public_target,
    resolve_public_target,
)


def _addr(address: str) -> list[tuple[int, int, int, str, tuple[str, int]]]:
    """Build one getaddrinfo-compatible result for resolver tests."""

    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (address, 443))]


def test_prepare_rewrites_target_and_preserves_original_host_and_https_identity(monkeypatch):
    """The request connects to one IP while HTTP/TLS retain the public host."""

    monkeypatch.setattr(
        egress_target.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addr("93.184.216.34"),
    )

    prepared = prepare_public_target("https://Example.com:8443/quotes?symbol=ABC")

    assert prepared.url == "https://93.184.216.34:8443/quotes?symbol=ABC"
    assert prepared.host_header == "example.com:8443"
    assert prepared.resolved_ip == "93.184.216.34"
    assert isinstance(prepared.adapter, PinnedAddressAdapter)
    assert prepared.adapter.poolmanager.connection_pool_kw["server_hostname"] == "example.com"
    assert prepared.adapter.poolmanager.connection_pool_kw["assert_hostname"] == "example.com"


def test_pinned_adapter_forces_host_header_and_rejects_reuse_for_another_target(monkeypatch):
    """An adapter cannot silently be reused for a different destination."""

    adapter = PinnedAddressAdapter(
        scheme="https", hostname="market.example.com", pinned_ip="93.184.216.34", port=443
    )
    seen: list[tuple[str, str]] = []

    def fake_send(_self, request, **_kwargs):
        seen.append((request.url, request.headers["Host"]))
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake_send)
    request = requests.Request("GET", "https://93.184.216.34/quotes").prepare()
    adapter.send(request)

    assert seen == [("https://93.184.216.34/quotes", "market.example.com")]
    other = requests.Request("GET", "https://93.184.216.35/quotes").prepare()
    with pytest.raises(requests.exceptions.InvalidURL):
        adapter.send(other)


def test_https_proxy_manager_pins_origin_tls_but_keeps_private_proxy_host(monkeypatch):
    """Proxy DNS is trusted configuration; origin TLS still uses its hostname."""

    monkeypatch.setattr(
        egress_target.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addr("93.184.216.34"),
    )
    prepared = prepare_public_target("https://market.example.com/quotes")

    manager = prepared.adapter.proxy_manager_for("http://visitor_proxy:secret@egress_visitor:18080")

    assert manager.proxy.host == "egress_visitor"
    assert manager.proxy.port == 18080
    assert manager.connection_pool_kw["server_hostname"] == "market.example.com"
    assert manager.connection_pool_kw["assert_hostname"] == "market.example.com"


def test_http_adapter_does_not_inject_tls_hostname():
    """Plain HTTP targets do not pass HTTPS-only kwargs to urllib3."""

    adapter = PinnedAddressAdapter(
        scheme="http", hostname="market.example.com", pinned_ip="93.184.216.34", port=80
    )

    assert "server_hostname" not in adapter.poolmanager.connection_pool_kw
    assert "assert_hostname" not in adapter.poolmanager.connection_pool_kw


@pytest.mark.parametrize(
    "url",
    (
        "http://user:secret@example.com/quotes",
        "http://@example.com/quotes",
        "http://example.com/quotes#fragment",
        "http://example.com:0/quotes",
        "ftp://example.com/quotes",
    ),
)
def test_target_parser_rejects_unsafe_urls(url: str):
    """Credentials, fragments, invalid ports, and schemes never reach DNS."""

    with pytest.raises(PublicTargetError) as error:
        resolve_public_target(url)

    assert error.value.code in {"EGRESS_INVALID_URL", "EGRESS_TARGET_NOT_ALLOWED"}


def test_private_or_mixed_dns_answers_are_rejected(monkeypatch):
    """Every DNS answer must be public before one address is selected."""

    monkeypatch.setattr(
        egress_target.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addr("93.184.216.34") + _addr("10.0.0.5"),
    )

    with pytest.raises(PublicTargetError) as error:
        resolve_public_target("https://market.example.com/quotes")

    assert error.value.code == "EGRESS_PRIVATE_TARGET"


def test_dns_selection_prefers_ipv4_when_all_answers_are_public(monkeypatch):
    """A single deterministic IPv4 address avoids avoidable IPv6 failures."""

    monkeypatch.setattr(
        egress_target.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _addr("2606:4700:4700::1111") + _addr("93.184.216.34"),
    )

    resolved = resolve_public_target("https://market.example.com/quotes")

    assert resolved.resolved_ip == "93.184.216.34"
    assert resolved.url == "https://93.184.216.34/quotes"


def test_dns_lookup_has_a_request_visible_deadline(monkeypatch):
    """A stuck system resolver cannot hold the caller beyond its DNS budget."""

    def slow_lookup(*_args, **_kwargs):
        time.sleep(0.2)
        return _addr("93.184.216.34")

    monkeypatch.setattr(egress_target.socket, "getaddrinfo", slow_lookup)
    started = time.monotonic()

    with pytest.raises(PublicTargetError) as error:
        resolve_public_target("https://market.example.com/quotes", dns_timeout_seconds=0.03)

    assert error.value.code == "EGRESS_DNS_TIMEOUT"
    assert time.monotonic() - started < 0.15


def test_dns_slots_fail_closed_when_no_bounded_worker_is_available(monkeypatch):
    """Resolver concurrency has an explicit bounded failure outcome."""

    monkeypatch.setattr(egress_target, "_DNS_SLOTS", egress_target.threading.BoundedSemaphore(0))

    with pytest.raises(PublicTargetError) as error:
        resolve_public_target("https://market.example.com/quotes", dns_timeout_seconds=0.01)

    assert error.value.code == "EGRESS_DNS_CONCURRENCY_LIMIT"
