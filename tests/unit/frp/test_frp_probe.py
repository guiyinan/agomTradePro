"""Focused checks for the bounded FRP deployment and probe tooling."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from scripts.frp_probe import (
    DEFAULT_COMPOSE_FILE,
    DEFAULT_MAINLAND_CONFIG,
    DEFAULT_VISITOR_CONFIG,
    _build_session,
    _validate_compose,
    _validate_toml_config,
    main,
    run_read_only_probe,
    validate_templates,
)


def _set_frp_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide non-secret test values for rendering the tracked templates."""

    monkeypatch.setenv("FRP_SERVER_ADDR", "frps.example.test")
    monkeypatch.setenv("FRP_SERVER_PORT", "7001")
    monkeypatch.setenv("FRP_STCP_SECRET", "test-stcp-secret")
    monkeypatch.setenv("FRP_HTTP_PROXY_USER", "test-proxy-user")
    monkeypatch.setenv("FRP_HTTP_PROXY_PASSWORD", "test-proxy-password")


def test_tracked_templates_validate_with_explicit_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rendered configs and the private compose topology pass together."""

    _set_frp_environment(monkeypatch)
    reports = validate_templates(
        visitor_config=DEFAULT_VISITOR_CONFIG,
        mainland_config=DEFAULT_MAINLAND_CONFIG,
        compose_file=DEFAULT_COMPOSE_FILE,
    )

    assert [report.role for report in reports] == ["visitor", "mainland", "compose"]
    assert all(report.ok for report in reports)


def test_compose_requires_frp_values_and_region_labels(tmp_path: Path) -> None:
    """The opt-in override fails closed for missing connection values."""

    source = DEFAULT_COMPOSE_FILE.read_text(encoding="utf-8")
    unsafe = source
    for variable in ("FRP_SERVER_ADDR", "FRP_SERVER_PORT", "FRP_STCP_SECRET"):
        marker = f"${{{variable}:?{variable} is required when frp-egress profile is enabled}}"
        unsafe = unsafe.replace(marker, f"${{{variable}:-}}")
    compose = tmp_path / "compose.yml"
    compose.write_text(unsafe, encoding="utf-8")

    report = _validate_compose(compose)
    codes = {issue.code for issue in report.issues}

    assert not report.ok
    assert codes == {"required_env_placeholder"}
    assert "deployment_region_missing" not in codes


def test_validation_blocks_when_template_environment_is_unset(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Valid examples with absent operator values are external blocks."""

    for name in (
        "FRP_SERVER_ADDR",
        "FRP_SERVER_PORT",
        "FRP_STCP_SECRET",
        "FRP_HTTP_PROXY_USER",
        "FRP_HTTP_PROXY_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)

    assert (
        main(
            [
                "validate",
                "--visitor-config",
                str(DEFAULT_VISITOR_CONFIG),
                "--mainland-config",
                str(DEFAULT_MAINLAND_CONFIG),
                "--compose-file",
                str(DEFAULT_COMPOSE_FILE),
                "--json",
            ]
        )
        == 2
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked_external"
    assert output["blocked_reason"] == "template_environment_unset"


def test_validator_rejects_public_visitor_and_inline_credentials(tmp_path: Path) -> None:
    """A copied config cannot weaken bind isolation or credential handling."""

    config = tmp_path / "visitor.toml"
    config.write_text(
        """
serverAddr = "frps.example.test"
serverPort = 7000
[auth]
method = "token"
token = "literal-token"
[auth.tokenSource]
type = "file"
[auth.tokenSource.file]
path = "/run/secrets/frp_auth_token"
[transport]
protocol = "tcp"
[transport.tls]
enable = true
[[visitors]]
name = "egress_http_proxy_visitor"
type = "stcp"
enabled = true
serverName = "egress_http_proxy"
secretKey = "literal-secret"
bindAddr = "127.0.0.1"
bindPort = 18080
""".strip(),
        encoding="utf-8",
    )

    report = _validate_toml_config(config, role="visitor")
    codes = {issue.code for issue in report.issues}

    assert not report.ok
    assert {"inline_auth_token", "literal_secret", "visitor_bind_not_private_network"} <= codes


class _FakeResponse:
    """Implement the response subset consumed by ``_fetch``."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status_code = status
        self.headers = {"Content-Type": "application/json"}
        self.raw = self

    def close(self) -> None:
        """Release the fake response."""

    def read(self, _limit: int) -> bytes:
        return self.body


class _FakeSession:
    """Return deterministic IP, raw, and hfq responses without network I/O."""

    def __init__(self, responses: Mapping[str, bytes]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, float, bool, bool]] = []

    def get(
        self, url: str, *, timeout: float, allow_redirects: bool, stream: bool
    ) -> _FakeResponse:
        self.calls.append((url, timeout, allow_redirects, stream))
        return _FakeResponse(self.responses[url])


def test_probe_reports_actual_ip_and_both_history_modes_without_proxy_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe stays read-only and never serializes proxy credentials."""

    monkeypatch.setenv("NO_PROXY", "*")
    ip_url = "https://ip.example.test/ip"
    raw_url = "https://data.example.test/raw"
    hfq_url = "https://data.example.test/hfq"
    session = _FakeSession(
        {
            ip_url: b'{"ip":"203.0.113.9"}',
            raw_url: b'{"data":{"klines":["2025-01-01,1","2025-01-02,2"]}}',
            hfq_url: b'{"data":{"klines":["2025-01-01,3","2025-01-02,4"]}}',
        }
    )
    factory_proxies: list[str] = []

    def factory(proxy_url: str) -> _FakeSession:
        factory_proxies.append(proxy_url)
        return session

    report = run_read_only_probe(
        "http://probe-user:super-secret@example.test:8080",
        ip_url=ip_url,
        raw_url=raw_url,
        hfq_url=hfq_url,
        allow_custom_host=True,
        session_factory=factory,
    )

    serialized = json.dumps(report, sort_keys=True)
    assert report["probe_status"] == "success"
    assert report["outbound_ip"] == "203.0.113.9"
    assert "super-secret" not in serialized
    assert report["proxy"] == {
        "configured": True,
        "credentials_redacted": True,
        "host": "example.test",
        "port": 8080,
        "scheme": "http",
    }
    assert factory_proxies == ["http://probe-user:super-secret@example.test:8080"]
    assert [call[0] for call in session.calls] == [ip_url, raw_url, hfq_url]
    assert all(call[2:] == (False, True) for call in session.calls)
    requests = report["requests"]
    assert isinstance(requests, list)
    assert [item["name"] for item in requests if isinstance(item, dict)] == [
        "outbound_ip",
        "raw_history",
        "hfq_history",
    ]


def test_requests_session_ignores_ambient_no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """An ambient NO_PROXY wildcard cannot force direct provider requests."""

    monkeypatch.setenv("NO_PROXY", "*")
    session = _build_session("http://visitor.example.test:18080")

    assert session.trust_env is False
    assert session.proxies == {
        "http": "http://visitor.example.test:18080",
        "https": "http://visitor.example.test:18080",
    }


def test_probe_command_reports_missing_external_proxy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing connection credentials are an explicit external block."""

    monkeypatch.delenv("FRP_EGRESS_PROXY_URL", raising=False)

    assert main(["probe", "--json"]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["probe_status"] == "blocked_external"
    assert output["blocked_reason"] == "missing_proxy_url"
    assert output["required_env"] == "FRP_EGRESS_PROXY_URL"
    assert output["side_effects"]["credentials_exposed"] is False
